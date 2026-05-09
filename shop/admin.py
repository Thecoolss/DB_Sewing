import json

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from .workflow import STAGE_TO_ROLE, order_board_progress_label, role_for_stage
from .models import (
    Customer,
    CustomerMeasurement,
    Delivery,
    Employee,
    Garment,
    GarmentType,
    GarmentMaterial,
    Material,
    Measurement,
    Order,
    StatusHistory,
    WorkflowEvent,
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
        if "primary_material" in self.fields:
            self.fields["primary_material"].queryset = Material.objects.filter(
                kind__in=[Material.Kind.FABRIC, Material.Kind.TRIM],
            ).order_by("name")
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

class CustomerMeasurementInline(TabularInline):
    model = CustomerMeasurement
    extra = 0


@admin.register(Customer)
class CustomerAdmin(StaffEditableModelAdmin):
    list_display = ("customer_widget",)
    list_display_links = None
    search_fields = ("full_name", "phone", "email")
    ordering = ("full_name",)
    inlines = (CustomerMeasurementInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_orders=Count("orders"))

    @admin.display(description="Customer")
    def customer_widget(self, obj):
        url = reverse("admin:shop_customer_change", args=[obj.pk])
        order_count = getattr(obj, "_orders", obj.orders.count())
        return format_html(
            '<div class="ss-admin-order-card"><a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__meta">Phone: {}</div>'
            '<div class="ss-admin-order-card__meta">Email: {}</div>'
            '<div class="ss-admin-order-card__meta">Orders so far: {}</div>'
            '<div class="ss-admin-order-card__hint">Open customer →</div>'
            "</a></div>",
            url,
            obj.full_name,
            obj.phone or "—",
            obj.email or "—",
            order_count,
        )


@admin.register(Employee)
class EmployeeAdmin(StaffEditableModelAdmin):
    """
    Each employee is tied to a production stage (specialty). When you pick a
    specialty, the role title is auto-filled (Cutter, Stitcher, Finisher…)
    so assignments stay logical.
    """

    list_display = ("employee_widget",)
    list_display_links = None
    list_filter = ("active", "role", "specialty_stage")
    search_fields = ("full_name", "role", "phone", "specialty_stage")

    def get_queryset(self, request):
        # Annotate with a count of currently-active tickets (not delivered).
        return (
            super()
            .get_queryset(request)
            .annotate(
                _active_tickets=Count(
                    "tickets",
                    filter=~Q(tickets__current_stage=WorkTicket.Stage.DELIVERED),
                ),
            )
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "specialty_stage":
            kwargs["widget"] = forms.Select(
                choices=[
                    ("", "— Assign a pipeline stage (required while Active) —"),
                ]
                + list(WorkTicket.Stage.choices),
            )
            kwargs["required"] = False
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # Keep job title in sync with specialty so each employee maps to a real
        # production stage. We only fill the role when it's blank (so manual
        # overrides like "Senior cutter" are preserved).
        if obj.specialty_stage and not (obj.role or "").strip():
            obj.role = role_for_stage(obj.specialty_stage)
        super().save_model(request, obj, form, change)

    @admin.display(description="Employee")
    def employee_widget(self, obj):
        url = reverse("admin:shop_employee_change", args=[obj.pk])
        specialty = (
            dict(WorkTicket.Stage.choices).get(obj.specialty_stage, "General")
            if obj.specialty_stage
            else "General"
        )
        active_tickets = getattr(obj, "_active_tickets", 0)
        status_class = "ss-priority-low" if not obj.active else ""
        active_label = "Active" if obj.active else "Inactive"
        return format_html(
            '<div class="ss-admin-order-card {}"><a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__customer">{}</div>'
            '<div class="ss-admin-order-card__meta">Specialty: {}</div>'
            '<div class="ss-admin-order-card__meta">Phone: {} · {}</div>'
            '<div class="ss-admin-order-card__meta">In progress: {} ticket{}</div>'
            '<div class="ss-admin-order-card__hint">Open employee →</div>'
            "</a></div>",
            status_class,
            url,
            obj.full_name,
            obj.role or "—",
            specialty,
            obj.phone or "—",
            active_label,
            active_tickets,
            "" if active_tickets == 1 else "s",
        )


@admin.register(Material)
class MaterialAdmin(StaffEditableModelAdmin):
    list_display = ("material_widget",)
    list_display_links = None
    list_filter = ("kind",)
    search_fields = ("name",)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_used_as_primary=Count("primary_garments"))
        )

    @admin.display(description="Material")
    def material_widget(self, obj):
        url = reverse("admin:shop_material_change", args=[obj.pk])
        used_as_primary = getattr(obj, "_used_as_primary", 0)
        return format_html(
            '<div class="ss-admin-order-card"><a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__customer">{}</div>'
            '<div class="ss-admin-order-card__meta">Sold per: {}</div>'
            '<div class="ss-admin-order-card__meta">Surcharge: €{}</div>'
            '<div class="ss-admin-order-card__meta">Primary on {} garment{}</div>'
            '<div class="ss-admin-order-card__hint">Open material →</div>'
            "</a></div>",
            url,
            obj.name,
            obj.get_kind_display(),
            obj.unit,
            obj.price_addon,
            used_as_primary,
            "" if used_as_primary == 1 else "s",
        )


@admin.register(GarmentType)
class GarmentTypeAdmin(StaffEditableModelAdmin):
    list_display = ("garment_type_widget",)
    list_display_links = None
    list_filter = ("active",)
    search_fields = ("name", "description")

    def get_queryset(self, request):
        return (
            super().get_queryset(request).annotate(_garments=Count("garments"))
        )

    @admin.display(description="Garment type")
    def garment_type_widget(self, obj):
        url = reverse("admin:shop_garmenttype_change", args=[obj.pk])
        garments = getattr(obj, "_garments", 0)
        active_label = "Active" if obj.active else "Disabled"
        active_class = "" if obj.active else "ss-priority-low"
        return format_html(
            '<div class="ss-admin-order-card {}"><a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__meta">Base price: €{}</div>'
            '<div class="ss-admin-order-card__meta">{}</div>'
            '<div class="ss-admin-order-card__meta">Used on {} garment{}</div>'
            '<div class="ss-admin-order-card__hint">Open type →</div>'
            "</a></div>",
            active_class,
            url,
            obj.name,
            obj.base_price,
            active_label,
            garments,
            "" if garments == 1 else "s",
        )


# ---------------------------------------------------------------------------
# Order — the main workflow hub
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(StaffEditableModelAdmin):
    """Changelist uses card widgets instead of a wide table (bulk actions still work)."""
    change_form_outer_before_template = "admin/shop/order/mark_fully_paid_banner.html"
    change_form_outer_after_template = "admin/shop/order/ticket_workflow.html"
    autocomplete_fields = ("customer",)
    list_display = ("order_summary_widget",)
    list_display_links = None
    list_filter = (
        "status",
        "priority",
        "payment_status",
        "delivery__status",
        "order_date",
        "due_date",
        "assigned_employee",
    )
    search_fields = ("reference", "customer__full_name", "assigned_employee__full_name")
    date_hierarchy = "order_date"
    list_select_related = ("customer", "assigned_employee", "delivery")
    ordering = ("due_date", "-order_date")
    readonly_fields = (
        "reference",
        "completed_at",
        "computed_total_display",
        "balance_due_display",
        "measurement_overview",
    )
    fieldsets = (
        (
            "Order",
            {
                "fields": (
                    "reference",
                    ("customer", "assigned_employee"),
                    ("order_date", "due_date"),
                    ("priority", "status", "completed_at"),
                    "notes",
                ),
            },
        ),
        (
            "Measurements summary",
            {"fields": ("measurement_overview",)},
        ),
        (
            "Pricing (auto-calculated — final price is editable)",
            {
                # CSS uses ss-pricing-fieldset to push this fieldset visually
                # below the Garments / Delivery inlines via flex `order`.
                "classes": ("ss-pricing-fieldset",),
                "description": (
                    "Total is the sum of garment-type base prices plus any fabric surcharge "
                    "(quantity × (base + addon)). The live total below updates as you edit "
                    "garments above; the saved value commits on Save."
                ),
                "fields": (
                    "use_automatic_pricing",
                    "computed_total_display",
                    ("total_price", "deposit_paid"),
                    ("payment_status", "balance_due_display"),
                ),
            },
        ),
    )
    inlines = (GarmentInline, DeliveryInline)

    class Media:
        js = ("admin/shop/order_pricing.js",)
    actions = (
        "generate_work_tickets",
        "mark_as_in_production",
        "mark_as_completed",
        "mark_as_delivered",
        "mark_orders_fully_paid",
    )

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        return [
            path(
                "<path:object_id>/mark-fully-paid/",
                self.admin_site.admin_view(self.mark_fully_paid_view),
                name="%s_%s_mark_fully_paid" % info,
            ),
        ] + super().get_urls()

    def mark_fully_paid_view(self, request, object_id):
        order = get_object_or_404(self.model, pk=object_id)
        if not self.has_change_permission(request, order):
            raise PermissionDenied
        if request.method != "POST":
            self.message_user(
                request,
                "Use the “Mark fully paid” button to confirm.",
                messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse("admin:shop_order_change", args=[object_id])
            )
        try:
            order.mark_fully_paid()
            order.save()
            self.message_user(
                request,
                "Order marked fully paid. Deposit now equals total — balance is €0.",
                messages.SUCCESS,
            )
        except ValidationError as exc:
            self.message_user(request, " ".join(exc.messages), messages.ERROR)
        return HttpResponseRedirect(reverse("admin:shop_order_change", args=[order.pk]))

    @admin.action(description="Mark as fully paid (deposit = total)")
    def mark_orders_fully_paid(self, request, queryset):
        ok = 0
        skipped = []
        for order in queryset:
            try:
                order.mark_fully_paid()
                order.save()
                ok += 1
            except ValidationError as exc:
                skipped.append(f"{order.reference}: {' '.join(exc.messages)}")
        if ok:
            self.message_user(request, f"Marked {ok} order(s) as fully paid.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                "Skipped: " + " | ".join(skipped[:8]),
                messages.WARNING,
            )

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        # Catalogue used by static/admin/shop/order_pricing.js to live-recalculate
        # the order total whenever the user picks a garment type, fabric, or qty.
        extra_context["pricing_catalogue_json"] = json.dumps(
            {
                "garment_types": {
                    str(pk): float(price)
                    for pk, price in GarmentType.objects.values_list("id", "base_price")
                },
                "materials": {
                    str(pk): float(addon)
                    for pk, addon in Material.objects.values_list("id", "price_addon")
                },
            }
        )
        if object_id:
            try:
                order = (
                    Order.objects.prefetch_related(
                        "garments__tickets__assigned_worker",
                        "garments__garment_type",
                    ).get(pk=object_id)
                )
                extra_context["order_tickets_workflow"] = list(
                    WorkTicket.objects.filter(garment__order=order)
                    .select_related("garment__garment_type", "assigned_worker")
                    .order_by("deadline", "ticket_number")
                )
            except Order.DoesNotExist:
                pass
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_related(self, request, form, formsets, change):
        """
        Garment inlines commit after `save_model`, so totals must be refreshed here.
        Covers add/change/remove rows and keeps payment_status aligned with garments.
        """
        super().save_related(request, form, formsets, change)
        order = form.instance
        if not isinstance(order, Order) or not order.pk:
            return
        fresh = Order.objects.get(pk=order.pk)
        if fresh.use_automatic_pricing:
            fresh.apply_automatic_pricing()
        fresh.apply_payment_status()
        fresh.save(update_fields=["total_price", "payment_status"])

    @admin.display(description="Order")
    def order_summary_widget(self, obj):
        try:
            dlabel = obj.delivery.get_status_display()
        except Delivery.DoesNotExist:
            dlabel = "—"
        progress = order_board_progress_label(obj)
        url = reverse("admin:shop_order_change", args=[obj.pk])
        price = obj.total_price if obj.total_price is not None else "—"
        balance = (
            f"{obj.balance_due:,.2f}"
            if obj.balance_due is not None
            else "—"
        )
        return format_html(
            '<div class="ss-admin-order-card ss-priority-{}">'
            '<a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__customer">{}</div>'
            '<div class="ss-admin-order-card__meta">Due {} · {} · {} priority</div>'
            '<div class="ss-admin-order-card__meta">Pipeline: {} · Delivery: {}</div>'
            '<div class="ss-admin-order-card__meta">Payment: {} · Total: €{} · Balance due: €{}</div>'
            '<div class="ss-admin-order-card__hint">Open order →</div>'
            "</a></div>",
            obj.priority,
            url,
            obj.reference,
            obj.customer.full_name if obj.customer_id else "—",
            obj.due_date,
            obj.get_status_display(),
            obj.get_priority_display(),
            progress,
            dlabel,
            obj.get_payment_status_display(),
            price,
            balance,
        )

    @admin.display(description="Calculated total (€)")
    def computed_total_display(self, obj):
        if not obj or not obj.pk:
            return "Save order first."
        total = obj.computed_total_from_garments()
        suffix = ""
        if total <= 0 and obj.garments.exists():
            suffix = (
                " — if this stays €0, edit Garment types and set a positive base price for each "
                "(e.g. Shirt, Hat)."
            )
        return f"€{total:,.2f}{suffix}"

    @admin.display(description="Balance due")
    def balance_due_display(self, obj):
        if not obj or obj.balance_due is None:
            return "—"
        return f"€{obj.balance_due:,.2f}"

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

    # --- inline save (measurements) ---

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        order = form.instance if isinstance(form.instance, Order) else None
        customer = order.customer if order and order.customer_id else None

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
                else:
                    Measurement.objects.update_or_create(
                        garment=garment,
                        name=name,
                        defaults={"value": value, "unit": unit or "cm"},
                    )

                # Mirror new measurements onto the customer profile too — only fill
                # gaps so we never overwrite a manually-set profile value.
                if customer is not None:
                    CustomerMeasurement.objects.get_or_create(
                        customer=customer,
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
    change_form_outer_after_template = "admin/shop/workticket/next_stage_panel.html"
    list_display = ("ticket_summary_widget",)
    list_display_links = None
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

    class Media:
        js = ("admin/shop/workticket_changelist_next.js",)

    @admin.display(description="Ticket")
    def ticket_summary_widget(self, obj):
        order_ref = obj.garment.order.reference
        change_url = reverse("admin:shop_workticket_change", args=[obj.pk])
        overdue = " · overdue" if obj.is_overdue else ""
        advance_url = reverse("shop:ticket_next_stage", args=[obj.pk])
        redir = reverse("admin:shop_workticket_changelist")

        # fetch() POST — no nested <form> inside Unfold's bulk-action #changelist-form (fixes row 1).
        advance_block = ""
        if obj.current_stage != WorkTicket.Stage.DELIVERED:
            advance_block = format_html(
                '<div class="sss-ticket-widget-actions ss-ticket-widget-actions">'
                '<button type="button" class="sss-wt-next-stage-btn ss-ticket-quick-next__btn" '
                'data-post-url="{}" data-next="{}">Next stage →</button>'
                "</div>",
                advance_url,
                redir,
            )

        stage_label = obj.get_current_stage_display()
        stage_bar = format_html(
            '<div class="ss-ticket-stage-bar"><span class="ss-ticket-stage-pill">{}</span></div>',
            stage_label,
        )
        card_inner = format_html(
            '{}'
            '<a class="sss-admin-order-card__link ss-admin-order-card__link" href="{}">'
            '<div class="sss-admin-order-card__ref ss-admin-order-card__ref">{}</div>'
            '<div class="sss-admin-order-card__customer ss-admin-order-card__customer">{} · Order {}</div>'
            '<div class="sss-admin-order-card__meta ss-admin-order-card__meta">Worker: {} · Due: {}{} · {}</div>'
            '<div class="sss-admin-order-card__hint ss-admin-order-card__hint">Open full ticket →</div></a>',
            stage_bar,
            change_url,
            obj.ticket_number,
            obj.garment.garment_type,
            order_ref,
            obj.assigned_worker or "— auto-assign",
            obj.deadline,
            overdue,
            obj.get_priority_display(),
        )
        return format_html(
            '<div class="ss-ticket-widget-row">'
            '<div class="sss-admin-ticket-card ss-ticket-card-wide">{}</div>'
            "{}"
            "</div>",
            card_inner,
            advance_block,
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
    list_display = ("delivery_widget",)
    list_display_links = None
    list_filter = ("status", "method", "scheduled_date")
    search_fields = ("order__reference", "order__customer__full_name")
    list_select_related = ("order", "order__customer")
    actions = ("mark_as_delivered",)

    @admin.display(description="Delivery")
    def delivery_widget(self, obj):
        url = reverse("admin:shop_delivery_change", args=[obj.pk])
        # Status colour: ready/out for delivery → priority-medium, delivered → low (calm)
        if obj.status == Delivery.Status.DELIVERED:
            klass = "ss-priority-low"
        elif obj.status in (Delivery.Status.READY_FOR_PICKUP, Delivery.Status.OUT_FOR_DELIVERY):
            klass = "ss-priority-medium"
        else:
            klass = ""
        return format_html(
            '<div class="ss-admin-order-card {}"><a class="ss-admin-order-card__link" href="{}">'
            '<div class="ss-admin-order-card__ref">{}</div>'
            '<div class="ss-admin-order-card__customer">{}</div>'
            '<div class="ss-admin-order-card__meta">Method: {}</div>'
            '<div class="ss-admin-order-card__meta">Status: {}</div>'
            '<div class="ss-admin-order-card__meta">Scheduled: {} · Delivered: {}</div>'
            '<div class="ss-admin-order-card__hint">Open delivery →</div>'
            "</a></div>",
            klass,
            url,
            obj.order.reference,
            obj.order.customer.full_name,
            obj.get_method_display(),
            obj.get_status_display(),
            obj.scheduled_date or "—",
            obj.delivered_date or "—",
        )

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


# ---------------------------------------------------------------------------
# Workflow audit (order/delivery)
# ---------------------------------------------------------------------------


@admin.register(WorkflowEvent)
class WorkflowEventAdmin(StaffEditableModelAdmin):
    """
    Read-only timeline of order/delivery changes (automatic signals).
    Use this to see status, payment, and priority updates at a glance.
    """

    list_display = ("created_at", "archived_order_ref", "order", "delivery", "ticket", "summary")
    list_filter = ("created_at",)
    search_fields = (
        "summary",
        "archived_order_ref",
        "order__reference",
        "order__customer__full_name",
    )
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "actor", "order", "delivery", "ticket", "summary", "archived_order_ref")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
