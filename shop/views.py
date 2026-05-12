from calendar import monthrange
from datetime import date, timedelta
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Customer, CustomerMeasurement, Delivery, Order, WorkTicket
from .workflow import advance_ticket_to_next_stage, order_board_progress_label


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
    delivered_qs = Order.objects.filter(status=Order.Status.DELIVERED)

    ticket_summary = (
        WorkTicket.objects.values("current_stage")
        .annotate(total=Count("id"))
        .order_by("current_stage")
    )
    stages = dict(WorkTicket.Stage.choices)
    ticket_summary_rows = [
        {
            "code": row["current_stage"],
            "label": stages.get(row["current_stage"], row["current_stage"]),
            "total": row["total"],
        }
        for row in ticket_summary
    ]

    context = {
        "nav_key": "dashboard",
        "page_title": "Operations dashboard",
        "page_subtitle": "Large text, simple layout. Use the menu for orders and reports.",
        "today": today,
        "pending_count": pending_qs.count(),
        "in_production_count": in_production_qs.count(),
        "overdue_count": overdue_qs.count(),
        "completed_count": completed_qs.count(),
        "delivered_count": delivered_qs.count(),
        "ticket_summary": ticket_summary_rows,
    }
    return render(request, "shop/dashboard_home.html", context)


@staff_member_required
def order_board(request, tab):
    """Widget board: active | closed | cancelled."""
    today = timezone.localdate()
    qs = Order.objects.select_related("customer", "delivery").prefetch_related(
        "garments__tickets"
    )
    if tab == "active":
        qs = qs.exclude(
            status__in=[Order.Status.DELIVERED, Order.Status.CANCELLED]
        )
    elif tab == "closed":
        qs = qs.filter(status=Order.Status.DELIVERED)
    elif tab == "cancelled":
        qs = qs.filter(status=Order.Status.CANCELLED)
    else:
        qs = qs.none()

    cards = []
    prio_rank = {"high": 0, "medium": 1, "low": 2}
    for order in qs:
        try:
            deliv = order.delivery
            dlabel = deliv.get_status_display()
        except Delivery.DoesNotExist:
            dlabel = "—"
        cards.append(
            {
                "order": order,
                "progress": order_board_progress_label(order),
                "delivery_label": dlabel,
                "edit_url": reverse("admin:shop_order_change", args=[order.pk]),
                "overdue": order.due_date < today
                and order.status
                in (Order.Status.DRAFT, Order.Status.IN_PRODUCTION),
            }
        )
    if tab == "active":
        cards.sort(key=lambda c: (prio_rank.get(c["order"].priority, 1), c["order"].due_date))

    titles = {
        "active": "Active orders",
        "closed": "Closed (delivered)",
        "cancelled": "Cancelled",
    }
    return render(
        request,
        "shop/order_board.html",
        {
            "nav_key": "orders_board",
            "board_tab": tab,
            "cards": cards,
            "page_title": titles.get(tab, "Orders"),
            "page_subtitle": "Tap Open to edit in the admin. Priority: high first.",
            "today": today,
        },
    )


@staff_member_required
def order_detail_shop(request, pk):
    """Simple order detail with next-stage buttons (staff-facing)."""
    order = get_object_or_404(
        Order.objects.select_related("customer", "delivery").prefetch_related(
            "garments__tickets__assigned_worker",
            "garments__garment_type",
        ),
        pk=pk,
    )
    tickets = (
        WorkTicket.objects.filter(garment__order=order)
        .select_related("garment__garment_type", "assigned_worker")
        .order_by("deadline", "ticket_number")
    )
    return render(
        request,
        "shop/order_detail.html",
        {
            "order": order,
            "tickets": tickets,
            "nav_key": "orders_board",
            "page_title": order.reference,
            "page_subtitle": order.customer.full_name,
            "today": timezone.localdate(),
            "edit_url": reverse("admin:shop_order_change", args=[order.pk]),
        },
    )


@staff_member_required
@require_POST
def ticket_next_stage(request, pk):
    ticket = get_object_or_404(WorkTicket, pk=pk)
    ok, msg = advance_ticket_to_next_stage(ticket)
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    order = ticket.garment.order
    return HttpResponseRedirect(
        request.POST.get("next")
        or reverse("shop:order_detail", kwargs={"pk": order.pk})
    )


def _week_ranges_in_month(ref: date) -> list[tuple[date, date]]:
    """Split a calendar month into consecutive ranges of up to 7 days (for weekly bars)."""
    y, m = ref.year, ref.month
    last = monthrange(y, m)[1]
    month_start = date(y, m, 1)
    month_end = date(y, m, last)
    out = []
    cur = month_start
    while cur <= month_end:
        week_end = min(cur + timedelta(days=6), month_end)
        out.append((cur, week_end))
        cur = week_end + timedelta(days=1)
    return out


@staff_member_required
def reports_dashboard(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    orders_m = Order.objects.filter(order_date__gte=month_start)
    delivered_revenue = (
        Order.objects.filter(
            status=Order.Status.DELIVERED,
            order_date__gte=month_start,
        ).aggregate(s=Sum("deposit_paid"))["s"]
        or 0
    )
    labels = dict(Order.Status.choices)
    by_status_chart = [
        {"label": labels.get(row["status"], row["status"]), "n": row["n"]}
        for row in Order.objects.values("status").annotate(n=Count("id")).order_by("status")
    ]

    weekly_rows = []
    for start_d, end_d in _week_ranges_in_month(today):
        label = f"{start_d.day}–{end_d.day} {start_d.strftime('%b')}"
        w_orders = Order.objects.filter(order_date__range=(start_d, end_d))
        n_orders = w_orders.count()
        week_payments = w_orders.aggregate(s=Sum("deposit_paid"))["s"] or 0
        weekly_rows.append(
            {
                "label": label,
                "orders": n_orders,
                "week_payments": float(week_payments),
            }
        )

    context = {
        "nav_key": "reports",
        "page_title": "Reports",
        "page_subtitle": f"This month (from {month_start})",
        "today": today,
        "order_count_month": orders_m.count(),
        "delivered_revenue": delivered_revenue,
        "by_status_chart": by_status_chart,
        "weekly_chart": weekly_rows,
    }
    return render(request, "shop/reports.html", context)


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
        elif order.status in {
            Order.Status.COMPLETED,
            Order.Status.DELIVERED,
            Order.Status.CANCELLED,
        }:
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
        "pending": "Draft orders.",
        "production": "In production.",
        "overdue": "Past due while still active.",
        "completed": "Completed (pre-delivery).",
        "delivered": "Delivered.",
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
            "page_subtitle": subtitles.get(filter_name, ""),
            "today": today,
        },
    )


@staff_member_required
def customer_profile_measurements_api(request, customer_id):
    """JSON list of saved profile measurements for order admin (prefill garment inlines)."""
    get_object_or_404(Customer, pk=customer_id)
    rows = [
        {"name": m.name, "value": str(m.value), "unit": m.unit or "cm"}
        for m in CustomerMeasurement.objects.filter(customer_id=customer_id).order_by("name")
    ]
    return JsonResponse({"measurements": rows})


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
            "page_subtitle": "Order history",
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
            "page_title": "Customers",
            "page_subtitle": "Search by name",
            "today": timezone.localdate(),
        },
    )
