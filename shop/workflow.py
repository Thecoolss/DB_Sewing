"""Production workflow helpers: stage sequence, next-step advancement, employee assignment."""

from __future__ import annotations

from django.db import transaction

from .models import Delivery, Employee, Order, WorkTicket


# Canonical job titles per ticket stage. Use these to keep employee roles
# logical and consistent (e.g. someone whose specialty is "sewing" is a "Stitcher").
STAGE_TO_ROLE = {
    WorkTicket.Stage.ORDER_RECEIVED: "Order intake",
    WorkTicket.Stage.DESIGN_CONFIRMED: "Designer",
    WorkTicket.Stage.CUTTING: "Cutter",
    WorkTicket.Stage.SEWING: "Stitcher",
    WorkTicket.Stage.FINISHING: "Finisher",
    WorkTicket.Stage.QUALITY_CHECK: "Quality inspector",
    WorkTicket.Stage.READY_FOR_DELIVERY: "Dispatch / fitting",
    WorkTicket.Stage.DELIVERED: "Delivery / pickup",
}


def role_for_stage(stage: str) -> str:
    """Return the canonical job title for a stage code, or empty string if unknown."""
    return STAGE_TO_ROLE.get(stage, "")


def order_board_progress_label(order: Order) -> str:
    """Short label for cards: earliest active stage across tickets for an order."""
    tickets = WorkTicket.objects.filter(garment__order=order)
    if not tickets.exists():
        return "No tickets"
    stages = list(tickets.values_list("current_stage", flat=True))
    if all(s == WorkTicket.Stage.DELIVERED for s in stages):
        return "All delivered"
    order_seq = [c for c, _ in WorkTicket.Stage.choices]
    terminal = {
        WorkTicket.Stage.READY_FOR_DELIVERY,
        WorkTicket.Stage.DELIVERED,
    }
    active = [s for s in stages if s not in terminal]
    if not active:
        return "Ready / finishing"
    idxs = [order_seq.index(s) for s in active if s in order_seq]
    if not idxs:
        return "—"
    i = min(idxs)
    return dict(WorkTicket.Stage.choices).get(order_seq[i], order_seq[i])

# Linear ticket workflow
STAGE_SEQUENCE = [
    WorkTicket.Stage.ORDER_RECEIVED,
    WorkTicket.Stage.DESIGN_CONFIRMED,
    WorkTicket.Stage.CUTTING,
    WorkTicket.Stage.SEWING,
    WorkTicket.Stage.FINISHING,
    WorkTicket.Stage.QUALITY_CHECK,
    WorkTicket.Stage.READY_FOR_DELIVERY,
    WorkTicket.Stage.DELIVERED,
]


def next_stage_value(current: str) -> str | None:
    try:
        i = STAGE_SEQUENCE.index(current)
    except ValueError:
        return None
    if i >= len(STAGE_SEQUENCE) - 1:
        return None
    return STAGE_SEQUENCE[i + 1]


def pick_employee_for_stage(stage: str) -> Employee | None:
    """
    Pick an active employee for this stage:
    1) specialty_stage matches the ticket stage code exactly
    2) otherwise any active employee with no specialty (generalist)
    3) otherwise any active employee
    """
    active = Employee.objects.filter(active=True)
    emp = active.filter(specialty_stage=stage).order_by("full_name").first()
    if emp:
        return emp
    emp = active.filter(specialty_stage="").order_by("full_name").first()
    if emp:
        return emp
    return active.order_by("full_name").first()


def order_priority_to_ticket_priority(order: Order) -> str:
    mapping = {
        Order.Priority.LOW: WorkTicket.Priority.LOW,
        Order.Priority.MEDIUM: WorkTicket.Priority.NORMAL,
        Order.Priority.HIGH: WorkTicket.Priority.HIGH,
    }
    return mapping.get(order.priority, WorkTicket.Priority.NORMAL)


@transaction.atomic
def advance_ticket_to_next_stage(ticket: WorkTicket) -> tuple[bool, str]:
    """
    Move ticket one step forward; assign worker for the NEW stage.
    Returns (success, message).
    """
    if ticket.garment.order.status == Order.Status.CANCELLED:
        return False, "Cannot advance ticket because the order is cancelled."
    nxt = next_stage_value(ticket.current_stage)
    if nxt is None:
        return False, "Already at the final stage."
    ticket.current_stage = nxt
    w = pick_employee_for_stage(nxt)
    ticket.assigned_worker = w
    ticket.save()
    who = w.full_name if w else "no-one (add an employee for this stage)"
    return True, f"Advanced to {ticket.get_current_stage_display()}. Assigned: {who}."
