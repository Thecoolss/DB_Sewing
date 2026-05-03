from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Customer, Order, WorkTicket


@staff_member_required
def dashboard_home(request):
    today = timezone.localdate()

    pending_qs = Order.objects.filter(status=Order.Status.DRAFT)
    in_production_qs = Order.objects.filter(status=Order.Status.IN_PRODUCTION)
    overdue_qs = Order.objects.filter(
        due_date__lt=today,
        status__in=[Order.Status.DRAFT, Order.Status.IN_PRODUCTION],
    )
    completed_qs = Order.objects.filter(status=Order.Status.COMPLETED)

    ticket_summary = (
        WorkTicket.objects.values("current_stage")
        .annotate(total=Count("id"))
        .order_by("current_stage")
    )

    stages = dict(WorkTicket.Stage.choices)
    ticket_summary_rows = [
        {"code": row["current_stage"], "label": stages.get(row["current_stage"], row["current_stage"]), "total": row["total"]}
        for row in ticket_summary
    ]

    context = {
        "nav_key": "dashboard",
        "page_title": "Operations dashboard",
        "page_subtitle": "Daily snapshot for pending workload, overdue risk, ticket mix, and the most recent orders.",
        "today": today,
        "pending_count": pending_qs.count(),
        "in_production_count": in_production_qs.count(),
        "overdue_count": overdue_qs.count(),
        "completed_count": completed_qs.count(),
        "ticket_summary": ticket_summary_rows,
        "recent_orders": Order.objects.select_related("customer").order_by("-order_date")[:10],
    }
    return render(request, "shop/dashboard_home.html", context)


@staff_member_required
def order_monitor(request, filter_name):
    today = timezone.localdate()
    filters = {
        "pending": Order.objects.filter(status=Order.Status.DRAFT),
        "production": Order.objects.filter(status=Order.Status.IN_PRODUCTION),
        "overdue": Order.objects.filter(
            due_date__lt=today,
            status__in=[Order.Status.DRAFT, Order.Status.IN_PRODUCTION],
        ),
        "completed": Order.objects.filter(status=Order.Status.COMPLETED),
        "delivered": Order.objects.filter(status=Order.Status.DELIVERED),
    }
    queryset = filters.get(filter_name, Order.objects.none()).select_related("customer")
    orders = []

    statuses = dict(Order.Status.choices)

    admin_root = reverse("admin:index")
    for order in queryset:
        overdue = order.due_date < today and order.status in {
            Order.Status.DRAFT,
            Order.Status.IN_PRODUCTION,
        }

        days_until_due = (order.due_date - today).days

        change_url = reverse("admin:shop_order_change", args=[order.pk])

        if overdue:
            due_badge_class = "danger"
        elif days_until_due <= 3:
            due_badge_class = "warning"
        elif order.status in {Order.Status.COMPLETED, Order.Status.DELIVERED, Order.Status.CANCELLED}:
            due_badge_class = "success"
        else:
            due_badge_class = "primary"

        orders.append(
            {
                "model": order,
                "due_badge_days": days_until_due,
                "due_badge_class": due_badge_class,
                "status_label": statuses.get(order.status, order.status),
                "admin_change_url": change_url,
                "overdue": overdue,
            }
        )

    subtitles = {
        "pending": "Orders that still need scheduling or clarification before entering production.",
        "production": "Orders currently underway in tailoring and QC.",
        "overdue": "Orders whose due dates have passed while still pending or in production.",
        "completed": "Orders marked completed internally (typically before final delivery bookkeeping).",
        "delivered": "Orders finalized as delivered.",
    }

    titles = {
        "pending": "Pending orders",
        "production": "Orders in production",
        "overdue": "Overdue orders",
        "completed": "Completed orders",
        "delivered": "Delivered orders",
    }

    keys = {
        "pending": "pending",
        "production": "production",
        "overdue": "overdue",
        "completed": "completed",
        "delivered": "delivered",
    }

    return render(
        request,
        "shop/order_monitor.html",
        {
            "orders": orders,
            "nav_key": keys.get(filter_name, filter_name),
            "filter_name": filter_name,
            "page_title": titles.get(filter_name, filter_name.replace("_", " ").title()),
            "page_subtitle": subtitles.get(filter_name, "Filtered order list."),
            "today": today,
            "admin_root": admin_root,
        },
    )


@staff_member_required
def customer_history(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = customer.orders.prefetch_related("garments__tickets").order_by("-order_date")
    return render(
        request,
        "shop/customer_history.html",
        {
            "customer": customer,
            "orders": orders,
            "nav_key": "customers",
            "page_title": customer.full_name,
            "page_subtitle": "Operational view of every order and related production tickets for this customer.",
            "today": timezone.localdate(),
        },
    )


@staff_member_required
def customer_search(request):
    query = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if query:
        customers = customers.filter(full_name__icontains=query)
    customers = customers.order_by("full_name")[:40]
    return render(
        request,
        "shop/customer_search.html",
        {
            "customers": customers,
            "query": query,
            "nav_key": "customers",
            "page_title": "Customer lookup",
            "page_subtitle": "Search customers and jump into their consolidated order timeline.",
            "today": timezone.localdate(),
        },
    )
