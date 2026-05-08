from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from .models import (
    Customer,
    Delivery,
    Employee,
    Garment,
    GarmentType,
    GarmentMaterial,
    Material,
    Measurement,
    Order,
    StatusHistory,
    WorkTicket,
)


class StaffEditableModelAdmin(ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_staff or request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_staff or request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff or request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_staff or request.user.is_superuser


# ---------------------------------------------------------------------------
# Inline helpers
# ---------------------------------------------------------------------------

class MeasurementInline(TabularInline):
    model = Measurement
    extra = 1


class GarmentMaterialInline(TabularInline):
    model = GarmentMaterial
    extra = 1


class GarmentInlineForm(forms.ModelForm):
    initial_measurement_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(),
    )
    initial_measurement_name = forms.CharField(
        required=False,
        label="Initial measurement name",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Chest"}),
    )
    initial_measurement_value = forms.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=2,
        min_value=0.01,
        label="Initial measurement value",
        widget=forms.NumberInput(attrs={"placeholder": "e.g. 92.5"}),
    )
    initial_measurement_unit = forms.CharField(
        required=False,
        max_length=10,
        initial="cm",
        label="Initial measurement unit",
        widget=forms.TextInput(attrs={"placeholder": "cm"}),
    )

    class Meta:
        model = Garment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            first_measurement = self.instance.measurements.order_by("id").first()
            if first_measurement:
                self.fields["initial_measurement_id"].initial = first_measurement.id
                self.fields["initial_measurement_name"].initial = first_measurement.name
                self.fields["initial_measurement_value"].initial = first_measurement.value
                self.fields["initial_measurement_unit"].initial = first_measurement.unit

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("initial_measurement_name") or "").strip()
        value = cleaned.get("initial_measurement_value")
        unit = (cleaned.get("initial_measurement_unit") or "").strip()

        if value is not None and not name:
            self.add_error("initial_measurement_name", "Measurement name is required when providing a value.")
        if name and value is None:
            self.add_error("initial_measurement_value", "Measurement value is required when providing a name.")
        if name and not unit:
            self.add_error("initial_measurement_unit", "Measurement unit is required when providing a name.")

        return cleaned


class GarmentInline(StackedInline):
    model = Garment
    form = GarmentInlineForm
    extra = 1
    fieldsets = (
        (
            "Garment details",
            {
                "fields": (
                    ("garment_type", "primary_material"),
                    ("quantity", "color"),
                    ("unit_price",),
                    "design_notes",
                )
            },
        ),
        (
            "Initial measurement (optional)",
            {
                "description": "Captured during order entry and saved to the Measurement table.",
                "fields": (
                    "initial_measurement_id",
                    (
                        "initial_measurement_name",
                        "initial_measurement_value",
                        "initial_measurement_unit",
                    ),
                ),
            },
        ),
    )


class DeliveryInline(StackedInline):
    model = Delivery
    min_num = 1
    max_num = 1
    extra = 0
    can_delete = False
    fields = ("method", "status", "scheduled_date", "delivered_date", "final_observations")


class WorkTicketInline(TabularInline):
    """Editable ticket inline — used on GarmentAdmin."""
    model = WorkTicket
    extra = 0
    readonly_fields = ("ticket_number",)
    fields = ("ticket_number", "current_stage", "priority", "deadline", "assigned_worker")


# ---------------------------------------------------------------------------
# Catalogue / reference-data admins
# ---------------------------------------------------------------------------

@admin.register(Customer)
class CustomerAdmin(StaffEditableModelAdmin):
    list_display = ("full_name", "phone", "email", "created_at")
    list_display_links = ("full_name",)
    search_fields = ("full_name", "phone", "email")
    ordering = ("full_name",)


@admin.register(Employee)
class EmployeeAdmin(StaffEditableModelAdmin):
    list_display = ("full_name", "role", "active", "phone")
    list_filter = ("active", "role")
    search_fields = ("full_name", "role", "phone")


@admin.register(Material)
class MaterialAdmin(StaffEditableModelAdmin):
    list_display = ("name", "unit", "created_at")
    search_fields = ("name",)


@admin.register(GarmentType)
class GarmentTypeAdmin(StaffEditableModelAdmin):
    list_display = ("name", "active", "description")
    list_filter = ("active",)
    search_fields = ("name", "description")


# ---------------------------------------------------------------------------
# Order — the main workflow hub
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(StaffEditableModelAdmin):
    list_display = (
        "reference", "customer", "assigned_employee",
        "status", "delivery_status", "due_date",
        "total_price", "deposit_paid", "balance_due_display", "payment_status",
    )
    list_display_links = ("reference",)
    list_filter = ("status", "payment_status", "delivery__status", "order_date", "due_date", "assigned_employee")
    search_fields = ("reference", "customer__full_name", "assigned_employee__full_name")
    date_hierarchy = "order_date"
    list_select_related = ("customer", "assigned_employee", "delivery")
    ordering = ("due_date", "-order_date")
    readonly_fields = ("reference", "completed_at", "balance_due_display", "measurement_overview", "ticket_overview")
    fieldsets = (
        (
            "Order",
            {
                "fields": (
                    "reference",
                    ("customer", "assigned_employee"),
                    ("order_date", "due_date"),
                    ("status", "completed_at"),
                    "notes",
                )
            },
        ),
        (
            "Pricing",
            {
                "fields": (
                    ("total_price", "deposit_paid"),
                    ("payment_status", "balance_due_display"),
                )
            },
        ),
        (
            "Measurements summary",
            {"fields": ("measurement_overview",)},
        ),
        (
            "Production tickets",
            {"fields": ("ticket_overview",)},
        ),
    )
    inlines = (GarmentInline, DeliveryInline)
    actions = ("generate_work_tickets", "mark_as_in_production", "mark_as_completed", "mark_as_delivered")

    # --- display helpers ---

    @admin.display(description="Delivery")
    def delivery_status(self, obj):
        try:
            return obj.delivery.get_status_display()
        except Exception:
            return "—"

    @admin.display(description="Balance due")
    def balance_due_display(self, obj):
        if not obj or obj.balance_due is None:
            return "—"
        return f"£{obj.balance_due:,.2f}"

    @admin.display(description="Measurements")
    def measurement_overview(self, obj):
        if not obj or not obj.pk:
            return "Save order first."
        entries = []
        for garment in obj.garments.prefetch_related("measurements"):
            measurements = ", ".join(
                f"{m.name}: {m.value}{m.unit}" for m in garment.measurements.all()
            ) or "No measurements yet"
            entries.append(f"{garment.garment_type}: {measurements}")
        return format_html_join("<br>", "{}", ((e,) for e in entries)) if entries else "No garments yet."

    @admin.display(description="Production tickets")
    def ticket_overview(self, obj):
        if not obj or not obj.pk:
            return "Save order first."
        tickets = (
            WorkTicket.objects.filter(garment__order=obj)
            .select_related("garment__garment_type", "assigned_worker")
            .order_by("deadline")
        )
        if not tickets.exists():
            return "No tickets yet — save garments first."

        rows = []
        for t in tickets:
            overdue_cell = mark_safe('<span style="color:#ef4444;font-weight:600;">Yes</span>') if t.is_overdue else "—"
            rows.append(format_html(
                "<tr>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "<td style='padding:4px 10px;'>{}</td>"
                "</tr>",
                t.ticket_number,
                t.garment.garment_type,
                t.assigned_worker or "—",
                t.get_current_stage_display(),
                t.get_priority_display(),
                t.deadline,
                overdue_cell,
            ))

        rows_html = mark_safe("".join(str(r) for r in rows))
        return mark_safe(
            "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
            "<thead><tr style='border-bottom:1px solid rgba(255,255,255,0.12);'>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Ticket</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Garment</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Worker</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Stage</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Priority</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Deadline</th>"
            "<th style='text-align:left;padding:4px 10px;opacity:.7;'>Overdue</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table>"
        )

    # --- inline save (measurements) ---

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        for inline_form in formset.forms:
            if not hasattr(inline_form, "cleaned_data"):
                continue
            if inline_form.cleaned_data.get("DELETE"):
                continue
            garment = inline_form.instance
            if not garment.pk:
                continue
            measurement_id = inline_form.cleaned_data.get("initial_measurement_id")
            name = (inline_form.cleaned_data.get("initial_measurement_name") or "").strip()
            value = inline_form.cleaned_data.get("initial_measurement_value")
            unit = (inline_form.cleaned_data.get("initial_measurement_unit") or "").strip()
            if name and value is not None:
                if measurement_id:
                    measurement = Measurement.objects.filter(pk=measurement_id, garment=garment).first()
                    if measurement:
                        measurement.name = name
                        measurement.value = value
                        measurement.unit = unit or "cm"
                        measurement.full_clean()
                        measurement.save()
                        continue
                Measurement.objects.update_or_create(
                    garment=garment,
                    name=name,
                    defaults={"value": value, "unit": unit or "cm"},
                )

    # --- bulk actions ---

    @admin.action(description="Generate missing work tickets")
    def generate_work_tickets(self, request, queryset):
        created = 0
        for order in queryset.prefetch_related("garments__tickets"):
            for garment in order.garments.all():
                if not garment.tickets.exists():
                    garment.create_default_ticket()
                    created += 1
        self.message_user(request, f"Generated {created} missing work ticket(s).", messages.SUCCESS)

    @admin.action(description="Mark as In Production")
    def mark_as_in_production(self, request, queryset):
        updated = 0
        for order in queryset:
            order.status = Order.Status.IN_PRODUCTION
            try:
                order.full_clean()
            except Exception as exc:
                self.message_user(request, f"{order}: {exc}", messages.ERROR)
                continue
            order.save()
            updated += 1
        self.message_user(request, f"Updated {updated} order(s).", messages.SUCCESS)

    @admin.action(description="Mark as Completed")
    def mark_as_completed(self, request, queryset):
        updated = 0
        for order in queryset:
            order.status = Order.Status.COMPLETED
            order.completed_at = timezone.now()
            try:
                order.full_clean()
            except Exception as exc:
                self.message_user(request, f"{order}: {exc}", messages.ERROR)
                continue
            order.save()
            updated += 1
        self.message_user(request, f"Completed {updated} order(s).", messages.SUCCESS)

    @admin.action(description="Mark as Delivered (closes tickets + delivery)")
    def mark_as_delivered(self, request, queryset):
        for order in queryset.prefetch_related("garments__tickets"):
            for garment in order.garments.all():
                for ticket in garment.tickets.all():
                    if ticket.current_stage != WorkTicket.Stage.DELIVERED:
                        ticket.current_stage = WorkTicket.Stage.DELIVERED
                        ticket.save()
            try:
                delivery = order.delivery
                if delivery.status != Delivery.Status.DELIVERED:
                    delivery.status = Delivery.Status.DELIVERED
                    delivery.delivered_date = delivery.delivered_date or timezone.localdate()
                    delivery.save()
            except Exception:
                pass
        self.message_user(request, f"Marked {queryset.count()} order(s) as delivered.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Garment — with editable ticket inline
# ---------------------------------------------------------------------------

@admin.register(Garment)
class GarmentAdmin(StaffEditableModelAdmin):
    list_display = ("garment_type", "primary_material", "order", "quantity", "color", "unit_price")
    list_filter = ("garment_type", "primary_material", "color")
    search_fields = ("garment_type__name", "primary_material__name", "order__reference")
    inlines = (MeasurementInline, GarmentMaterialInline, WorkTicketInline)
    actions = ("generate_work_tickets",)

    @admin.action(description="Generate missing work tickets")
    def generate_work_tickets(self, request, queryset):
        created = 0
        for garment in queryset.prefetch_related("tickets"):
            if not garment.tickets.exists():
                garment.create_default_ticket()
                created += 1
        self.message_user(request, f"Generated {created} missing work ticket(s).", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Work Tickets — fast stage advancement
# ---------------------------------------------------------------------------

class StatusHistoryInline(TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("stage", "changed_by", "changed_at", "comments")
    can_delete = False


@admin.register(WorkTicket)
class WorkTicketAdmin(StaffEditableModelAdmin):
    list_display = (
        "ticket_number", "garment", "assigned_worker",
        "current_stage", "priority", "deadline", "is_overdue",
    )
    list_display_links = ("ticket_number",)
    list_editable = ("current_stage", "assigned_worker")
    list_select_related = ("garment__order", "garment__garment_type", "assigned_worker")
    list_filter = ("current_stage", "priority", "deadline", "assigned_worker")
    search_fields = (
        "ticket_number",
        "garment__order__reference",
        "garment__order__customer__full_name",
        "garment__garment_type__name",
    )
    inlines = (StatusHistoryInline,)
    actions = (
        "advance_to_design_confirmed",
        "advance_to_cutting",
        "advance_to_sewing",
        "advance_to_finishing",
        "advance_to_quality_check",
        "advance_to_ready_for_delivery",
        "advance_to_delivered",
    )

    def save_model(self, request, obj, form, change):
        previous_stage = None
        if change:
            previous_stage = (
                WorkTicket.objects.filter(pk=obj.pk).values_list("current_stage", flat=True).first()
            )
        super().save_model(request, obj, form, change)
        if previous_stage != obj.current_stage:
            latest_history = obj.status_history.first()
            if latest_history and latest_history.changed_by is None:
                latest_history.changed_by = request.user
                latest_history.save(update_fields=["changed_by"])

    def _advance_stage(self, request, queryset, stage_value, stage_label):
        for ticket in queryset:
            ticket.current_stage = stage_value
            ticket.save()
        self.message_user(request, f"Advanced {queryset.count()} ticket(s) to {stage_label}.", messages.SUCCESS)

    @admin.action(description="→ Design Confirmed")
    def advance_to_design_confirmed(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.DESIGN_CONFIRMED, "Design Confirmed")

    @admin.action(description="→ Cutting")
    def advance_to_cutting(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.CUTTING, "Cutting")

    @admin.action(description="→ Sewing")
    def advance_to_sewing(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.SEWING, "Sewing")

    @admin.action(description="→ Finishing")
    def advance_to_finishing(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.FINISHING, "Finishing")

    @admin.action(description="→ Quality Check")
    def advance_to_quality_check(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.QUALITY_CHECK, "Quality Check")

    @admin.action(description="→ Ready for Delivery")
    def advance_to_ready_for_delivery(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.READY_FOR_DELIVERY, "Ready for Delivery")

    @admin.action(description="→ Delivered")
    def advance_to_delivered(self, request, queryset):
        self._advance_stage(request, queryset, WorkTicket.Stage.DELIVERED, "Delivered")


# ---------------------------------------------------------------------------
# Status History — read-only audit log
# ---------------------------------------------------------------------------

@admin.register(StatusHistory)
class StatusHistoryAdmin(StaffEditableModelAdmin):
    list_display = ("ticket", "stage", "changed_by", "changed_at")
    list_filter = ("stage", "changed_at")
    search_fields = ("ticket__ticket_number", "comments")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------

@admin.register(Delivery)
class DeliveryAdmin(StaffEditableModelAdmin):
    list_display = (
        "order", "customer_name", "method", "status",
        "scheduled_date", "delivered_date",
    )
    list_filter = ("status", "method", "scheduled_date")
    search_fields = ("order__reference", "order__customer__full_name")
    actions = ("mark_as_delivered",)

    @admin.display(description="Customer")
    def customer_name(self, obj):
        return obj.order.customer.full_name

    @admin.action(description="Mark as Delivered (closes tickets + order)")
    def mark_as_delivered(self, request, queryset):
        for delivery in queryset.select_related("order").prefetch_related(
            "order__garments__tickets"
        ):
            order = delivery.order
            for garment in order.garments.all():
                for ticket in garment.tickets.all():
                    if ticket.current_stage != WorkTicket.Stage.DELIVERED:
                        ticket.current_stage = WorkTicket.Stage.DELIVERED
                        ticket.save()
            if delivery.status != Delivery.Status.DELIVERED:
                delivery.status = Delivery.Status.DELIVERED
                delivery.delivered_date = delivery.delivered_date or timezone.localdate()
                delivery.save()
        self.message_user(request, f"Marked {queryset.count()} delivery(s) as delivered.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

@admin.register(Measurement)
class MeasurementAdmin(StaffEditableModelAdmin):
    list_display = ("garment", "name", "value", "unit", "notes")
    list_filter = ("unit", "name")
    search_fields = ("garment__order__reference", "garment__garment_type__name", "name")
