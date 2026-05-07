from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html, format_html_join
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
            self.add_error(
                "initial_measurement_name",
                "Measurement name is required when providing a value.",
            )

        if name and value is None:
            self.add_error(
                "initial_measurement_value",
                "Measurement value is required when providing a name.",
            )

        if name and not unit:
            self.add_error(
                "initial_measurement_unit",
                "Measurement unit is required when providing a name.",
            )

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


@admin.register(Order)
class OrderAdmin(StaffEditableModelAdmin):
    list_display = ("reference", "customer", "assigned_employee", "order_date", "due_date", "status")
    list_filter = ("status", "order_date", "due_date", "assigned_employee")
    search_fields = ("reference", "customer__full_name", "assigned_employee__full_name")
    date_hierarchy = "order_date"
    readonly_fields = ("reference", "completed_at", "measurement_overview")
    fields = (
        "reference",
        "customer",
        "assigned_employee",
        "order_date",
        "due_date",
        "status",
        "completed_at",
        "notes",
        "measurement_overview",
    )
    inlines = (GarmentInline,)
    actions = ("generate_work_tickets", "mark_as_in_production", "mark_as_completed")

    @admin.action(description="Generate missing work tickets for selected orders")
    def generate_work_tickets(self, request, queryset):
        created = 0
        for order in queryset.prefetch_related("garments__tickets"):
            for garment in order.garments.all():
                if not garment.tickets.exists():
                    garment.create_default_ticket()
                    created += 1
        self.message_user(
            request,
            f"Generated {created} missing work ticket(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Mark selected orders as In Production")
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

    @admin.action(description="Mark selected orders as Completed")
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
                    measurement = Measurement.objects.filter(
                        pk=measurement_id,
                        garment=garment,
                    ).first()
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

    @admin.display(description="Measurements on this order")
    def measurement_overview(self, obj):
        if not obj or not obj.pk:
            return "Save order first to view/edit garment measurements."

        entries = []
        garments = obj.garments.prefetch_related("measurements")
        for garment in garments:
            measurements = ", ".join(
                f"{m.name}: {m.value}{m.unit}" for m in garment.measurements.all()
            ) or "No measurements yet"
            entries.append(f"{garment.garment_type}: {measurements}")

        if not entries:
            return "No garments yet."

        return format_html_join("<br>", "{}", ((entry,) for entry in entries))


@admin.register(Garment)
class GarmentAdmin(StaffEditableModelAdmin):
    list_display = ("garment_type", "primary_material", "order", "quantity", "color")
    list_filter = ("garment_type", "primary_material", "color")
    search_fields = ("garment_type__name", "primary_material__name", "order__reference")
    inlines = (MeasurementInline, GarmentMaterialInline)
    actions = ("generate_work_tickets",)

    @admin.action(description="Generate missing work tickets for selected garments")
    def generate_work_tickets(self, request, queryset):
        created = 0
        for garment in queryset.prefetch_related("tickets"):
            if not garment.tickets.exists():
                garment.create_default_ticket()
                created += 1
        self.message_user(
            request,
            f"Generated {created} missing work ticket(s).",
            messages.SUCCESS,
        )


class StatusHistoryInline(TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("stage", "changed_by", "changed_at", "comments")
    can_delete = False


@admin.register(WorkTicket)
class WorkTicketAdmin(StaffEditableModelAdmin):
    list_display = (
        "ticket_number",
        "order_reference",
        "garment",
        "order_lead",
        "assigned_worker",
        "current_stage",
        "priority",
        "deadline",
        "is_overdue",
    )
    list_display_links = ("ticket_number", "order_reference")
    list_select_related = (
        "garment__order",
        "garment__order__assigned_employee",
        "garment__order__customer",
        "garment__garment_type",
        "assigned_worker",
    )
    list_filter = ("current_stage", "priority", "deadline", "assigned_worker")
    search_fields = (
        "ticket_number",
        "garment__order__reference",
        "garment__order__customer__full_name",
        "garment__order__assigned_employee__full_name",
        "assigned_worker__full_name",
        "garment__garment_type__name",
    )
    readonly_fields = ("order_link",)
    inlines = (StatusHistoryInline,)
    actions = ("mark_ready_for_delivery", "mark_delivered")

    @admin.display(description="Order", ordering="garment__order__reference")
    def order_reference(self, obj):
        order = obj.garment.order
        url = reverse("admin:shop_order_change", args=[order.pk])
        return format_html('<a href="{}">{}</a>', url, order.reference)

    @admin.display(
        description="Order lead",
        ordering="garment__order__assigned_employee__full_name",
    )
    def order_lead(self, obj):
        emp = obj.garment.order.assigned_employee
        return emp.full_name if emp else "—"

    @admin.display(description="Order (read-only)")
    def order_link(self, obj):
        if not obj.pk:
            return "—"
        order = obj.garment.order
        url = reverse("admin:shop_order_change", args=[order.pk])
        lead = order.assigned_employee
        lead_txt = lead.full_name if lead else "—"
        return format_html(
            '<a href="{}">{}</a> — {} — Order lead: <strong>{}</strong>',
            url,
            order.reference,
            order.customer.full_name,
            lead_txt,
        )

    def save_model(self, request, obj, form, change):
        previous_stage = None
        if change:
            previous_stage = (
                WorkTicket.objects.filter(pk=obj.pk)
                .values_list("current_stage", flat=True)
                .first()
            )
        super().save_model(request, obj, form, change)
        if previous_stage != obj.current_stage:
            latest_history = obj.status_history.first()
            if latest_history and latest_history.changed_by is None:
                latest_history.changed_by = request.user
                latest_history.save(update_fields=["changed_by"])

    @admin.action(description="Move selected tickets to Ready for Delivery")
    def mark_ready_for_delivery(self, request, queryset):
        for ticket in queryset:
            ticket.current_stage = WorkTicket.Stage.READY_FOR_DELIVERY
            ticket.save()

    @admin.action(description="Move selected tickets to Delivered")
    def mark_delivered(self, request, queryset):
        for ticket in queryset:
            ticket.current_stage = WorkTicket.Stage.DELIVERED
            ticket.save()


@admin.register(StatusHistory)
class StatusHistoryAdmin(StaffEditableModelAdmin):
    list_display = ("ticket", "stage", "changed_by", "changed_at")
    list_filter = ("stage", "changed_at")
    search_fields = ("ticket__ticket_number", "comments")


@admin.register(Delivery)
class DeliveryAdmin(StaffEditableModelAdmin):
    list_display = ("order", "method", "status", "scheduled_date", "delivered_date")
    list_filter = ("status", "method", "scheduled_date")
    search_fields = ("order__reference", "order__customer__full_name")


@admin.register(Measurement)
class MeasurementAdmin(StaffEditableModelAdmin):
    list_display = ("garment", "name", "value", "unit", "notes")
    list_filter = ("unit", "name")
    search_fields = ("garment__order__reference", "garment__garment_type__name", "name")
