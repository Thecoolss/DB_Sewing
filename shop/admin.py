from django.contrib import admin, messages
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline

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


class GarmentInline(TabularInline):
    model = Garment
    extra = 1
    fields = ("garment_type", "primary_material", "quantity", "color", "design_notes")


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
        "garment",
        "assigned_worker",
        "current_stage",
        "priority",
        "deadline",
        "is_overdue",
    )
    list_filter = ("current_stage", "priority", "deadline", "assigned_worker")
    search_fields = ("ticket_number", "garment__order__reference", "garment__garment_type__name")
    inlines = (StatusHistoryInline,)
    actions = ("mark_ready_for_delivery", "mark_delivered")

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
