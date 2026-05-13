import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

# Money and counts: disallow negatives at the model layer (admin + ORM create).
_NONNEG_MONEY = [MinValueValidator(Decimal("0"))]
_POSITIVE_MONEY = [MinValueValidator(Decimal("0.01"))]
_POSITIVE_QTY = [MinValueValidator(1)]


class Customer(models.Model):
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    preferences = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class CustomerMeasurement(models.Model):
    """Optional body / sizing profile for a customer (e.g. shirt — chest, sleeve)."""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="profile_measurements",
    )
    name = models.CharField(max_length=80)
    value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=_POSITIVE_MONEY,
    )
    unit = models.CharField(max_length=10, default="cm")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["customer_id", "name"]
        unique_together = ("customer", "name")

    def __str__(self):
        return f"{self.customer.full_name}: {self.name}"


class Employee(models.Model):
    full_name = models.CharField(max_length=120)
    role = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    phone = models.CharField(max_length=30, blank=True)
    specialty_stage = models.CharField(
        max_length=30,
        blank=True,
        help_text=(
            "Each active worker handles one pipeline stage so tickets auto-assign correctly "
            '(e.g. cutting, sewing — use “design confirmed”, “delivered”, etc. sparingly).'
        ),
    )

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    def clean(self):
        stage_codes = {s for s, _ in WorkTicket.Stage.choices}
        if self.specialty_stage and self.specialty_stage not in stage_codes:
            raise ValidationError(
                {"specialty_stage": f"Must be one of: {', '.join(sorted(stage_codes))}."}
            )
        if self.active and not (self.specialty_stage or "").strip():
            raise ValidationError(
                {
                    "specialty_stage": (
                        "Active employees must cover one pipeline stage "
                        '(pick e.g. “Cutting” or “Sewing”; turn off Active if archiving only).'
                    )
                },
            )

    def save(self, *args, **kwargs):
        """Run `clean()` on every persist so programmatic creates match admin rules."""
        self.clean()
        super().save(*args, **kwargs)


class Material(models.Model):
    class Kind(models.TextChoices):
        FABRIC = "fabric", "Fabric / textile"
        TRIM = "trim", "Trim / lining"
        NOTIONS = "notions", "Buttons, zippers, etc."
        OTHER = "other", "Other"

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=30, default="meters")
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.FABRIC,
        help_text="Use Fabric for primary material on garments; buttons/notions belong here, not as “primary fabric”.",
    )
    price_addon = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=_NONNEG_MONEY,
        help_text="Extra charge when this material is chosen (per garment unit).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GarmentType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=_NONNEG_MONEY,
        help_text="Fixed base price for this garment type (before fabric surcharge).",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_PRODUCTION = "in_production", "In Production"
        COMPLETED = "completed", "Completed"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        DEPOSIT_PAID = "deposit_paid", "Deposit Paid"
        FULLY_PAID = "fully_paid", "Fully Paid"

    reference = models.CharField(max_length=30, unique=True, editable=False)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    assigned_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_orders",
    )
    order_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PRODUCTION,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    use_automatic_pricing = models.BooleanField(
        default=True,
        help_text="When on, order total is recalculated from garment types and fabric surcharges.",
    )
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_NONNEG_MONEY,
        help_text="Agreed total price for this order.",
    )
    deposit_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=_NONNEG_MONEY,
        help_text="Deposit amount already received.",
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-order_date", "due_date"]

    def __str__(self):
        return self.reference

    @property
    def balance_due(self):
        if self.total_price is None:
            return None
        return self.total_price - (self.deposit_paid or Decimal("0.00"))

    def computed_total_from_garments(self):
        if not self.pk:
            return Decimal("0.00")
        total = Decimal("0.00")
        for g in self.garments.all():
            total += g.line_total
        return total

    def apply_automatic_pricing(self):
        if self.use_automatic_pricing:
            self.total_price = self.computed_total_from_garments()

    def apply_payment_status(self):
        total = self.total_price
        dep = self.deposit_paid or Decimal("0.00")
        if total is None or total <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif dep <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif dep >= total:
            self.payment_status = self.PaymentStatus.FULLY_PAID
        else:
            self.payment_status = self.PaymentStatus.DEPOSIT_PAID

    def mark_fully_paid(self):
        """
        Record full payment: sets deposit to match total so balance due is €0
        and payment_status becomes Fully paid. Caller should .save().
        """
        from django.core.exceptions import ValidationError

        total = self.total_price
        if total is None or total <= 0:
            raise ValidationError(
                "Set a positive order total before marking as fully paid.",
            )
        self.deposit_paid = total
        self.apply_payment_status()

    def clean(self):
        if (
            self.order_date is not None
            and self.due_date is not None
            and self.due_date < self.order_date
        ):
            raise ValidationError({"due_date": "Due date must be on/after order date."})

        if self.assigned_employee and not self.assigned_employee.active:
            raise ValidationError(
                {"assigned_employee": "Orders can only be assigned to active employees."}
            )

        if (
            self.pk
            and self.status in {self.Status.COMPLETED, self.Status.DELIVERED}
            and self._has_active_tickets()
        ):
            raise ValidationError(
                "Completed or delivered orders cannot keep tickets in active production stages."
            )

        # Once an order is DELIVERED, it cannot be regressed (only stay DELIVERED or be CANCELLED).
        if self.pk:
            previous_status = (
                Order.objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            if (
                previous_status == self.Status.DELIVERED
                and self.status not in {self.Status.DELIVERED, self.Status.CANCELLED}
            ):
                raise ValidationError(
                    {
                        "status": "Delivered orders cannot be moved back to an earlier status.",
                    }
                )

        total = self.total_price
        dep = self.deposit_paid or Decimal("0.00")
        if total is not None and dep > total:
            raise ValidationError(
                {
                    "deposit_paid": "Deposit cannot exceed the order total.",
                },
            )

    def _has_active_tickets(self):
        terminal = {
            WorkTicket.Stage.READY_FOR_DELIVERY,
            WorkTicket.Stage.DELIVERED,
        }
        return WorkTicket.objects.filter(garment__order=self).exclude(
            current_stage__in=terminal
        ).exists()

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        previous_status = None
        if not is_new:
            previous_status = (
                Order.objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
        if not self.reference:
            self.reference = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        self.apply_automatic_pricing()
        self.apply_payment_status()
        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)
        if is_new:
            Delivery.objects.get_or_create(order=self)
        if self.status == self.Status.CANCELLED and previous_status != self.Status.CANCELLED:
            self._apply_cancellation_side_effects()

    def _apply_cancellation_side_effects(self):
        note = (
            f"Order {self.reference} was marked as CANCELLED on "
            f"{timezone.localdate().isoformat()}."
        )
        for ticket in WorkTicket.objects.filter(garment__order=self):
            existing = ticket.notes or ""
            if note in existing:
                continue
            ticket.notes = f"{existing}\n{note}".strip() if existing else note
            ticket.save(update_fields=["notes"])

        delivery = Delivery.objects.filter(order=self).first()
        if delivery:
            existing_obs = delivery.final_observations or ""
            if note not in existing_obs:
                delivery.final_observations = (
                    f"{existing_obs}\n{note}".strip() if existing_obs else note
                )
                delivery.save(update_fields=["final_observations"])


class Garment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="garments")
    garment_type = models.ForeignKey(
        GarmentType,
        on_delete=models.PROTECT,
        related_name="garments",
    )
    primary_material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="primary_garments",
        help_text="Main material chosen during order entry. Use detailed materials for quantities.",
    )
    quantity = models.PositiveIntegerField(default=1, validators=_POSITIVE_QTY)
    color = models.CharField(max_length=50, blank=True)
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_NONNEG_MONEY,
        help_text="Price per unit for this garment.",
    )
    design_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.garment_type} ({self.order.reference})"

    @property
    def line_total(self):
        base = self.garment_type.base_price or Decimal("0.00")
        addon = (
            self.primary_material.price_addon
            if self.primary_material_id
            else Decimal("0.00")
        )
        return (base + addon) * self.quantity

    def clean(self):
        if self.primary_material_id and self.primary_material.kind == Material.Kind.NOTIONS:
            raise ValidationError(
                {
                    "primary_material": (
                        "Use fabrics or textiles as primary material; buttons and small notions "
                        "belong in garment materials, not here."
                    )
                }
            )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if self.order.use_automatic_pricing:
            self.unit_price = self.line_total / self.quantity if self.quantity else self.line_total
        super().save(*args, **kwargs)
        if is_new:
            self.create_default_ticket()
        if self.order_id and self.order.use_automatic_pricing:
            o = self.order
            o.apply_automatic_pricing()
            o.apply_payment_status()
            Order.objects.filter(pk=o.pk).update(
                total_price=o.total_price,
                payment_status=o.payment_status,
            )

    def create_default_ticket(self):
        from .workflow import order_priority_to_ticket_priority, pick_employee_for_stage

        tp = order_priority_to_ticket_priority(self.order)
        worker = pick_employee_for_stage(WorkTicket.Stage.ORDER_RECEIVED) or self.order.assigned_employee
        ticket, _ = WorkTicket.objects.get_or_create(
            garment=self,
            defaults={
                "deadline": self.order.due_date,
                "current_stage": WorkTicket.Stage.ORDER_RECEIVED,
                "assigned_worker": worker,
                "priority": tp,
            },
        )
        return ticket


class Measurement(models.Model):
    garment = models.ForeignKey(
        Garment,
        on_delete=models.CASCADE,
        related_name="measurements",
    )
    name = models.CharField(max_length=80)
    value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=_POSITIVE_MONEY,
    )
    unit = models.CharField(max_length=10, default="cm")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["garment_id", "name"]
        unique_together = ("garment", "name")

    def __str__(self):
        return f"{self.garment}: {self.name}={self.value}{self.unit}"

    def clean(self):
        if self.value <= 0:
            raise ValidationError({"value": "Measurement value must be greater than zero."})


class GarmentMaterial(models.Model):
    garment = models.ForeignKey(
        Garment,
        on_delete=models.CASCADE,
        related_name="garment_materials",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        related_name="garment_materials",
    )
    quantity = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=_NONNEG_MONEY,
    )
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["garment_id", "material__name"]
        unique_together = ("garment", "material")

    def __str__(self):
        return f"{self.material.name} for {self.garment}"

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Material quantity must be greater than zero."})


class WorkTicket(models.Model):
    class Stage(models.TextChoices):
        ORDER_RECEIVED = "order_received", "Order Received"
        DESIGN_CONFIRMED = "design_confirmed", "Design Confirmed"
        CUTTING = "cutting", "Cutting"
        SEWING = "sewing", "Sewing"
        FINISHING = "finishing", "Finishing"
        QUALITY_CHECK = "quality_check", "Quality Check"
        READY_FOR_DELIVERY = "ready_for_delivery", "Ready for Delivery"
        DELIVERED = "delivered", "Delivered"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    ticket_number = models.CharField(max_length=30, unique=True, editable=False)
    garment = models.ForeignKey(
        Garment,
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    assigned_worker = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    current_stage = models.CharField(
        max_length=30,
        choices=Stage.choices,
        default=Stage.ORDER_RECEIVED,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    deadline = models.DateField()
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["deadline", "ticket_number"]

    def __str__(self):
        return self.ticket_number

    def clean(self):
        if (
            self.garment_id
            and self.deadline
            and self.deadline < self.garment.order.order_date
        ):
            raise ValidationError(
                {"deadline": "Ticket deadline must be on/after the order date."}
            )

        if self.assigned_worker_id and not self.assigned_worker.active:
            raise ValidationError(
                {"assigned_worker": "Tickets can only be assigned to active employees."}
            )

    @property
    def is_overdue(self):
        return self.deadline < timezone.localdate() and self.current_stage not in {
            self.Stage.READY_FOR_DELIVERY,
            self.Stage.DELIVERED,
        }

    def save(self, *args, **kwargs):
        previous_stage = None
        if self.pk:
            previous_stage = (
                WorkTicket.objects.filter(pk=self.pk)
                .values_list("current_stage", flat=True)
                .first()
            )
        if not self.ticket_number:
            self.ticket_number = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        if self.current_stage == self.Stage.DELIVERED and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)

        if previous_stage is None:
            StatusHistory.objects.create(
                ticket=self,
                stage=self.current_stage,
                comments="Ticket created.",
            )
        elif previous_stage != self.current_stage:
            StatusHistory.objects.create(
                ticket=self,
                stage=self.current_stage,
                comments=f"Stage changed from {previous_stage} to {self.current_stage}.",
            )
            self._sync_order_and_delivery()

    def _sync_order_and_delivery(self):
        order = self.garment.order
        if order.status == Order.Status.CANCELLED:
            return
        stages = list(
            WorkTicket.objects.filter(garment__order=order)
            .values_list("current_stage", flat=True)
        )
        if not stages:
            return

        terminal = {self.Stage.READY_FOR_DELIVERY, self.Stage.DELIVERED}
        all_terminal = all(s in terminal for s in stages)
        all_delivered = all(s == self.Stage.DELIVERED for s in stages)

        try:
            delivery = order.delivery
        except Exception:
            return

        if all_delivered and delivery.status != Delivery.Status.DELIVERED:
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.Status.DELIVERED,
                delivered_date=timezone.localdate(),
            )
            Order.objects.filter(pk=order.pk).update(
                status=Order.Status.DELIVERED,
                completed_at=timezone.now(),
            )
        elif all_terminal and not all_delivered and delivery.status == Delivery.Status.PENDING:
            if delivery.method == Delivery.Method.PICKUP:
                new_ds = Delivery.Status.READY_FOR_PICKUP
            else:
                new_ds = Delivery.Status.OUT_FOR_DELIVERY
            Delivery.objects.filter(pk=delivery.pk).update(status=new_ds)
            if order.status not in {Order.Status.COMPLETED, Order.Status.DELIVERED}:
                Order.objects.filter(pk=order.pk).update(
                    status=Order.Status.COMPLETED,
                    completed_at=timezone.now(),
                )


class StatusHistory(models.Model):
    ticket = models.ForeignKey(
        WorkTicket,
        on_delete=models.CASCADE,
        related_name="status_history",
    )
    stage = models.CharField(max_length=30, choices=WorkTicket.Stage.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_status_updates",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    comments = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.get_stage_display()}"


class Delivery(models.Model):
    class Method(models.TextChoices):
        PICKUP = "pickup", "Pickup"
        COURIER = "courier", "Courier"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY_FOR_PICKUP = "ready_pickup", "Ready for pickup"
        OUT_FOR_DELIVERY = "out_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="delivery",
    )
    method = models.CharField(
        max_length=10,
        choices=Method.choices,
        default=Method.PICKUP,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    scheduled_date = models.DateField(null=True, blank=True)
    delivered_date = models.DateField(null=True, blank=True)
    final_observations = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"Delivery for {self.order.reference}"

    def clean(self):
        if self.status == self.Status.DELIVERED and not self.delivered_date:
            raise ValidationError(
                {"delivered_date": "Delivered date is required once status is Delivered."}
            )

        od = getattr(self.order, "order_date", None)
        if od is not None:
            if self.scheduled_date and self.scheduled_date < od:
                raise ValidationError(
                    {"scheduled_date": "Scheduled delivery cannot be before the order date."}
                )

            if self.delivered_date and self.delivered_date < od:
                raise ValidationError(
                    {"delivered_date": "Delivered date cannot be before the order date."}
                )


    def save(self, *args, **kwargs):
        if self.status == self.Status.DELIVERED and not self.delivered_date:
            self.delivered_date = timezone.localdate()
        super().save(*args, **kwargs)

        if self.order.status == Order.Status.CANCELLED:
            return

        # Decide the order status that should mirror this delivery state.
        # NOTE: DELIVERED is terminal for the order — never roll an order out of DELIVERED.
        desired_status = None
        if self.status == self.Status.PENDING:
            if self.order.status == Order.Status.COMPLETED:
                desired_status = Order.Status.IN_PRODUCTION
        elif self.status in (
            self.Status.READY_FOR_PICKUP,
            self.Status.OUT_FOR_DELIVERY,
        ):
            if self.order.status not in {Order.Status.COMPLETED, Order.Status.DELIVERED}:
                desired_status = Order.Status.COMPLETED
        elif self.status == self.Status.DELIVERED:
            if self.order.status != Order.Status.DELIVERED:
                desired_status = Order.Status.DELIVERED

        if desired_status and desired_status != self.order.status:
            self.order.status = desired_status
            if desired_status in {
                Order.Status.COMPLETED,
                Order.Status.DELIVERED,
            } and not self.order.completed_at:
                self.order.completed_at = timezone.now()
            elif desired_status == Order.Status.IN_PRODUCTION:
                self.order.completed_at = None
            self.order.save(update_fields=["status", "completed_at"])


class WorkflowEvent(models.Model):
    """
    Append-only audit trail for important shop activity at order/delivery level.

    Each row is a short human-readable summary (who did what, when). Ticket
    stage history stays in ``StatusHistory``; this table complements that by
    recording creates/changes to orders and deliveries (e.g. status, payment,
    priority) so you can answer “what happened to this order?” without
    digging through raw rows. Django signals write most events automatically.

    When an order is deleted, related workflow rows for that job are cleared and one
    tombstone row remains with ``archived_order_ref`` marking the deletion.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_events",
    )
    ticket = models.ForeignKey(
        "WorkTicket",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_events",
    )
    delivery = models.ForeignKey(
        Delivery,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_events",
    )
    summary = models.CharField(max_length=255)
    archived_order_ref = models.CharField(
        max_length=36,
        blank=True,
        db_index=True,
        help_text="When an order is removed entirely, its reference is logged here once (tombstone row).",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Workflow event"
        verbose_name_plural = "Workflow events"

    def __str__(self):
        return self.summary
