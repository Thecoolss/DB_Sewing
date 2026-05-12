from calendar import monthrange
from datetime import date, timedelta
import json
import re
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.db.models import Count, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Customer, CustomerMeasurement, Delivery, Order, WorkTicket
from .workflow import advance_ticket_to_next_stage, order_board_progress_label

_SQL_BLOCKED_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|"
    r"comment|vacuum|analyze|execute|call|copy|merge|refresh|security)\b",
    re.IGNORECASE,
)
_SQL_LIMIT_PATTERN = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)

_ASSISTANT_DECLINE_MESSAGE = "I don't understand the request."

_SQL_ASSISTANT_SCHEMA = """
Use only these tables and columns:
- shop_order(id, reference, customer_id, assigned_employee_id, order_date, due_date, priority, status, completed_at, total_price, deposit_paid, payment_status)
- shop_customer(id, full_name, phone, email, address, notes, preferences, created_at)
- shop_employee(id, full_name, role, active, phone, specialty_stage)
- shop_garment(id, order_id, garment_type_id, primary_material_id, quantity, color, unit_price, design_notes)
- shop_garmenttype(id, name, description, active, base_price)
- shop_material(id, name, description, unit, kind, price_addon, created_at)
- shop_workticket(id, ticket_number, garment_id, assigned_worker_id, current_stage, priority, deadline, started_at, completed_at, notes)
- shop_delivery(id, order_id, method, status, scheduled_date, delivered_date, final_observations)
- shop_statushistory(id, ticket_id, stage, changed_by_id, changed_at, comments)
- shop_workflowevent(id, created_at, actor_id, order_id, ticket_id, delivery_id, summary, archived_order_ref)
- shop_measurement(id, garment_id, name, value, unit, notes)
- shop_customermeasurement(id, customer_id, name, value, unit, notes)
- shop_garmentmaterial(id, garment_id, material_id, quantity, notes)
"""


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
    month_payments_total = (
        orders_m.aggregate(s=Sum("deposit_paid"))["s"]
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
        "month_payments_total": month_payments_total,
        "by_status_chart": by_status_chart,
        "weekly_chart": weekly_rows,
    }
    return render(request, "shop/reports.html", context)


def _compute_daily_metrics(day: date) -> dict:
    day_orders = Order.objects.filter(order_date=day)
    by_status = [
        {"status": row["status"], "count": row["n"]}
        for row in day_orders.values("status").annotate(n=Count("id")).order_by("status")
    ]
    totals = day_orders.aggregate(
        total_value=Sum("total_price"),
        total_deposits=Sum("deposit_paid"),
    )
    return {
        "date": day.isoformat(),
        "orders_count": day_orders.count(),
        "delivered_count": day_orders.filter(status=Order.Status.DELIVERED).count(),
        "in_production_count": day_orders.filter(status=Order.Status.IN_PRODUCTION).count(),
        "total_order_value": float(totals["total_value"] or 0),
        "total_deposits_paid": float(totals["total_deposits"] or 0),
        "status_breakdown": by_status,
    }


@staff_member_required
def trigger_daily_metrics(request):
    today = timezone.localdate()
    metrics = _compute_daily_metrics(today)
    return render(
        request,
        "shop/daily_metrics.html",
        {
            "nav_key": "reports",
            "page_title": "Daily metrics",
            "page_subtitle": f"Metrics for {today}",
            "today": today,
            "metrics": metrics,
        },
    )


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    return cleaned.strip()


def _call_gemini_json(system_prompt: str, user_prompt: str, temperature: float = 0.0) -> dict:
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    model = settings.GEMINI_MODEL.strip() or "gemini-1.5-flash"
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    req_body = json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {"text": f"System instructions:\n{system_prompt}\n\nUser request:\n{user_prompt}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    req = urlrequest.Request(
        url=url,
        data=req_body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(req, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini request failed ({exc.code}): {details[:300]}") from exc
    except urlerror.URLError as exc:
        raise ValueError(f"Gemini network error: {exc.reason}") from exc

    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    content = "".join(str(part.get("text", "")) for part in parts)
    content = _strip_code_fences(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("AI response was not valid JSON.") from exc


def _validate_select_sql(candidate_sql: str) -> str:
    sql = candidate_sql.strip()
    if not sql:
        raise ValueError("The AI did not return a SQL query.")
    if ";" in sql:
        raise ValueError("Only a single SELECT query is allowed (no semicolons).")
    if _SQL_BLOCKED_PATTERN.search(sql):
        raise ValueError("Only read-only SELECT/WITH queries are allowed.")
    if not re.match(r"^\s*(select|with)\b", sql, flags=re.IGNORECASE):
        raise ValueError("Query must start with SELECT or WITH.")
    if not _SQL_LIMIT_PATTERN.search(sql):
        sql = f"{sql.rstrip()} LIMIT 100"
    return sql


def _execute_select_query(sql: str) -> tuple[list[str], list[dict]]:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        cols = [col[0] for col in cursor.description or []]
        rows = cursor.fetchall()
    normalized_rows = [dict(zip(cols, row)) for row in rows]
    return cols, normalized_rows


def _assistant_classify_data_question(user_prompt: str) -> bool:
    """
    Return True only if the user is asking for shop data answerable via SELECT
    on the operational schema. Everything else is treated as off-topic.
    """
    response = _call_gemini_json(
        system_prompt=(
            "You gatekeep a sewing shop database assistant. The database contains "
            "operational data only: orders, customers, garments, work tickets, deliveries, "
            "employees, materials, measurements, garment materials, status history, and "
            "workflow events (see schema hint below).\n\n"
            "Reply with JSON only, one key:\n"
            '- {"data_question": true} — the user wants factual answers from this database '
            "(counts, sums, averages, lists, filters, who/when/what status, dates, names, "
            "money fields like deposit_paid or total_price).\n"
            '- {"data_question": false} — general chat, jokes, unrelated topics, coding help, '
            "homework, medical/legal advice, web search, or anything not grounded in this schema.\n\n"
            "When in doubt, use false."
            f"\n\nSchema hint:\n{_SQL_ASSISTANT_SCHEMA}"
        ),
        user_prompt=f"User message:\n{user_prompt}",
        temperature=0.0,
    )
    return bool(response.get("data_question"))


def _sql_from_natural_language(user_prompt: str) -> str:
    response = _call_gemini_json(
        system_prompt=(
            "You convert natural language into safe PostgreSQL SELECT queries. "
            "Return JSON: {\"sql\": \"...\"}. "
            "Rules: SELECT/WITH only, no semicolons, no writes, no DDL, "
            "prefer explicit columns, include useful aliases."
        ),
        user_prompt=(
            f"Database schema:\n{_SQL_ASSISTANT_SCHEMA}\n\n"
            f"Question: {user_prompt}\n"
            "Return JSON with key `sql` only."
        ),
        temperature=0.0,
    )
    sql = str(response.get("sql", ""))
    return _validate_select_sql(sql)


def _narrate_sql_result(user_prompt: str, sql: str, rows: list[dict]) -> str:
    safe_rows = rows[:20]
    response = _call_gemini_json(
        system_prompt=(
            "You are an operations analyst. Explain SQL results in plain language "
            "for shop staff. Keep it short and concrete. "
            "Return JSON: {\"answer\": \"...\"}."
        ),
        user_prompt=(
            f"Question: {user_prompt}\nSQL: {sql}\n"
            f"Rows (sample): {json.dumps(safe_rows, default=str)}\n"
            f"Returned row count: {len(rows)}"
        ),
        temperature=0.2,
    )
    return str(response.get("answer", "")).strip() or "No explanation generated."


@staff_member_required
def sql_assistant(request):
    context = {
        "nav_key": "sql_assistant",
        "page_title": "Assistant",
        "page_subtitle": "Ask in plain English; runs read-only queries only.",
        "today": timezone.localdate(),
    }
    if request.method == "POST":
        prompt = request.POST.get("prompt", "").strip()
        context["prompt"] = prompt
        if not prompt:
            messages.error(request, "Type a question first.")
            return render(request, "shop/sql_assistant.html", context)
        try:
            if not _assistant_classify_data_question(prompt):
                context["assistant_answer"] = _ASSISTANT_DECLINE_MESSAGE
            else:
                sql = _sql_from_natural_language(prompt)
                columns, rows = _execute_select_query(sql)
                answer = _narrate_sql_result(prompt, sql, rows)
                context.update(
                    {
                        "generated_sql": sql,
                        "result_columns": columns,
                        "result_rows": rows[:30],
                        "result_row_count": len(rows),
                        "assistant_answer": answer,
                    }
                )
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Query failed: {exc}")
    return render(request, "shop/sql_assistant.html", context)


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
