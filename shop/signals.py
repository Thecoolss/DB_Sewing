from django.db.models import Q
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from .models import Delivery, Order, WorkflowEvent, WorkTicket


@receiver(pre_save, sender=WorkTicket)
def _workticket_assign_worker_on_stage_change(sender, instance, **kwargs):
    """When the stage changes, assign the worker for the new stage automatically."""
    from .workflow import pick_employee_for_stage

    if not instance.pk:
        w = pick_employee_for_stage(instance.current_stage)
        if w:
            instance.assigned_worker = w
        return
    try:
        old_stage = (
            WorkTicket.objects.filter(pk=instance.pk)
            .values_list("current_stage", flat=True)
            .first()
        )
    except WorkTicket.DoesNotExist:
        old_stage = None
    if old_stage != instance.current_stage:
        w = pick_employee_for_stage(instance.current_stage)
        if w:
            instance.assigned_worker = w


@receiver(pre_save, sender=Order)
def _order_cache_old(sender, instance, **kwargs):
    if not instance.pk:
        instance._wf_old = None
        return
    try:
        instance._wf_old = Order.objects.get(pk=instance.pk)
    except Order.DoesNotExist:
        instance._wf_old = None


@receiver(pre_delete, sender=Order)
def _order_delete_workflow_tombstone(sender, instance, **kwargs):
    """Strip workflow audit rows tied to this order so DELETE can succeed; leave one tombstone."""
    pk = instance.pk
    ref = instance.reference or f"#{pk}"

    WorkflowEvent.objects.filter(
        Q(order_id=pk)
        | Q(delivery__order_id=pk)
        | Q(ticket__garment__order_id=pk),
    ).delete()

    WorkflowEvent.objects.create(
        archived_order_ref=ref,
        summary=(
            f"Order {ref} was permanently deleted (garments, tickets, deliveries, "
            "and linked workflow/status rows were removed with it)."
        ),
    )


@receiver(post_save, sender=Order)
def _order_log(sender, instance, created, **kwargs):
    if created:
        WorkflowEvent.objects.create(
            order=instance,
            summary=f"Order {instance.reference} created ({instance.get_status_display()}).",
        )
        return
    old = getattr(instance, "_wf_old", None)
    if not old:
        return
    parts = []
    if old.status != instance.status:
        parts.append(f"status {old.get_status_display()} → {instance.get_status_display()}")
    if old.payment_status != instance.payment_status:
        parts.append(
            f"payment {old.get_payment_status_display()} → {instance.get_payment_status_display()}"
        )
    if (old.total_price or 0) != (instance.total_price or 0) or (
        old.deposit_paid or 0
    ) != (instance.deposit_paid or 0):
        parts.append("pricing or deposit updated")
    if old.priority != instance.priority:
        parts.append(f"priority → {instance.get_priority_display()}")
    if parts:
        WorkflowEvent.objects.create(
            order=instance,
            summary="; ".join(parts),
        )


@receiver(pre_save, sender=Delivery)
def _delivery_cache_old(sender, instance, **kwargs):
    if not instance.pk:
        instance._wf_old = None
        return
    try:
        instance._wf_old = Delivery.objects.get(pk=instance.pk)
    except Delivery.DoesNotExist:
        instance._wf_old = None


@receiver(post_save, sender=Delivery)
def _delivery_log(sender, instance, created, **kwargs):
    if created:
        WorkflowEvent.objects.create(
            order=instance.order,
            delivery=instance,
            summary=f"Delivery record for {instance.order.reference} ({instance.get_method_display()}).",
        )
        return
    old = getattr(instance, "_wf_old", None)
    if old and old.status != instance.status:
        WorkflowEvent.objects.create(
            order=instance.order,
            delivery=instance,
            summary=(
                f"Delivery {instance.order.reference}: "
                f"{old.get_status_display()} → {instance.get_status_display()}"
            ),
        )
