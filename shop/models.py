import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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


class Employee(models.Model):
    full_name = models.CharField(max_length=120)
    role = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Material(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=30, default="meters")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class GarmentType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

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
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-order_date", "due_date"]

    def __str__(self):
        return self.reference

    def clean(self):
        if self.due_date < self.order_date:
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

    def _has_active_tickets(self):
        terminal = {
            WorkTicket.Stage.READY_FOR_DELIVERY,
            WorkTicket.Stage.DELIVERED,
        }
        return WorkTicket.objects.filter(garment__order=self).exclude(
            current_stage__in=terminal
        ).exists()

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)


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
    quantity = models.PositiveIntegerField(default=1)
    color = models.CharField(max_length=50, blank=True)
    design_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.garment_type} ({self.order.reference})"

    def create_default_ticket(self):
        ticket, _ = WorkTicket.objects.get_or_create(
            garment=self,
            defaults={
                "deadline": self.order.due_date,
                "current_stage": WorkTicket.Stage.ORDER_RECEIVED,
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
    value = models.DecimalField(max_digits=8, decimal_places=2)
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
        READY = "ready", "Ready"
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
        max_length=10,
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

        if self.scheduled_date and self.scheduled_date < self.order.order_date:
            raise ValidationError(
                {"scheduled_date": "Scheduled delivery cannot be before the order date."}
            )

        if self.delivered_date and self.delivered_date < self.order.order_date:
            raise ValidationError(
                {"delivered_date": "Delivered date cannot be before the order date."}
            )

        # Tickets must be at least Ready-for-delivery before this delivery can be Ready/Delivered.
        if self.status in {self.Status.READY, self.Status.DELIVERED}:
            non_terminal = WorkTicket.objects.filter(garment__order=self.order).exclude(
                current_stage__in=[
                    WorkTicket.Stage.READY_FOR_DELIVERY,
                    WorkTicket.Stage.DELIVERED,
                ]
            )
            if non_terminal.exists():
                raise ValidationError(
                    {
                        "status": (
                            "Delivery cannot be marked Ready/Delivered while tickets are still "
                            "in active production stages."
                        )
                    }
                )

        # Stricter rule: closing as Delivered requires every ticket to be Delivered.
        if self.status == self.Status.DELIVERED:
            not_delivered = WorkTicket.objects.filter(garment__order=self.order).exclude(
                current_stage=WorkTicket.Stage.DELIVERED
            )
            if not_delivered.exists():
                raise ValidationError(
                    {
                        "status": (
                            "Delivery cannot be marked Delivered until every ticket reaches the "
                            "Delivered stage."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        if self.status == self.Status.DELIVERED and not self.delivered_date:
            self.delivered_date = timezone.localdate()
        super().save(*args, **kwargs)

        # Decide the order status that should mirror this delivery state.
        # NOTE: DELIVERED is terminal for the order — never roll an order out of DELIVERED.
        desired_status = None
        if self.status == self.Status.PENDING:
            if self.order.status == Order.Status.COMPLETED:
                desired_status = Order.Status.IN_PRODUCTION
        elif self.status == self.Status.READY:
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
