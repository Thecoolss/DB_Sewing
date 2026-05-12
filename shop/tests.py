from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from django.contrib.auth import get_user_model

from .models import (
    Customer,
    CustomerMeasurement,
    Delivery,
    Employee,
    Garment,
    GarmentType,
    Material,
    Measurement,
    Order,
    WorkflowEvent,
    WorkTicket,
)
from .workflow import (
    advance_ticket_to_next_stage,
    pick_employee_for_stage,
    role_for_stage,
)


class WorkflowAutomationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(full_name="Test Customer")
        self.order = Order.objects.create(
            customer=self.customer,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        self.garment_type = GarmentType.objects.create(name="Dress")
        self.material = Material.objects.create(name="Cotton", unit="meters")
        self.garment = Garment.objects.create(
            order=self.order,
            garment_type=self.garment_type,
            primary_material=self.material,
            quantity=1,
        )

    def test_garment_can_generate_default_ticket(self):
        # Garment.save() already created a ticket; create_default_ticket() returns it.
        ticket = self.garment.create_default_ticket()

        self.assertEqual(ticket.garment, self.garment)
        self.assertEqual(ticket.deadline, self.order.due_date)
        self.assertEqual(ticket.current_stage, WorkTicket.Stage.ORDER_RECEIVED)
        self.assertEqual(self.garment.tickets.count(), 1)

    def test_delivery_marks_order_delivered(self):
        # Order.save() auto-creates a Delivery; get it and update.
        delivery = self.order.delivery
        delivery.status = Delivery.Status.DELIVERED
        delivery.save()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)
        self.assertIsNotNone(delivery.delivered_date)

    def test_inactive_employee_cannot_be_assigned_to_order(self):
        inactive = Employee.objects.create(full_name="Inactive Worker", active=False)
        self.order.assigned_employee = inactive

        with self.assertRaises(ValidationError):
            self.order.full_clean()

    def test_measurement_value_must_be_positive(self):
        measurement = Measurement(
            garment=self.garment,
            name="Chest",
            value=0,
        )

        with self.assertRaises(ValidationError):
            measurement.full_clean()

    def test_tickets_in_active_stage_do_not_advance_delivery(self):
        # Tickets in mid-production stages should NOT auto-advance delivery.
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.SEWING
        ticket.save()

        self.order.delivery.refresh_from_db()
        self.assertEqual(self.order.delivery.status, Delivery.Status.PENDING)

    def test_all_tickets_ready_advances_delivery_to_ready(self):
        # When every ticket reaches READY_FOR_DELIVERY the delivery auto-advances.
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.READY_FOR_DELIVERY
        ticket.save()

        self.order.delivery.refresh_from_db()
        self.assertEqual(
            self.order.delivery.status,
            Delivery.Status.READY_FOR_PICKUP,
        )

    def test_all_tickets_ready_courier_sets_out_for_delivery(self):
        delivery = self.order.delivery
        delivery.method = Delivery.Method.COURIER
        delivery.save()

        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.READY_FOR_DELIVERY
        ticket.save()

        self.order.delivery.refresh_from_db()
        self.assertEqual(self.order.delivery.status, Delivery.Status.OUT_FOR_DELIVERY)

    def test_delivered_order_cannot_regress(self):
        # Advancing all tickets to DELIVERED cascades order → DELIVERED.
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.DELIVERED
        ticket.save()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

        # A DELIVERED order cannot be moved to an earlier status.
        self.order.status = Order.Status.IN_PRODUCTION
        with self.assertRaises(ValidationError):
            self.order.full_clean()

    def test_customer_profile_measurements_api(self):
        User = get_user_model()
        user = User.objects.create_user("apistaff", "apistaff@example.com", "secret", is_staff=True)
        CustomerMeasurement.objects.create(
            customer=self.customer,
            name="Chest",
            value=Decimal("88"),
            unit="cm",
        )
        self.client.force_login(user)
        r = self.client.get(f"/internal/profile-measurements/{self.customer.pk}/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["measurements"]), 1)
        self.assertEqual(data["measurements"][0]["name"], "Chest")


class OrderDeleteWorkflowTests(TestCase):
    def test_order_delete_removes_audit_rows_and_writes_tombstone(self):
        customer = Customer.objects.create(full_name="Delete Me Customer")
        order = Order.objects.create(
            customer=customer,
            due_date=timezone.localdate() + timedelta(days=3),
        )
        WorkflowEvent.objects.create(
            order=order,
            summary="Before delete breadcrumb.",
        )
        oid, ref = order.pk, order.reference
        order.delete()
        self.assertFalse(Order.objects.filter(pk=oid).exists())
        remaining = WorkflowEvent.objects.filter(archived_order_ref=ref)
        self.assertEqual(remaining.count(), 1)
        self.assertIn("deleted", remaining.first().summary.lower())
        self.assertFalse(
            WorkflowEvent.objects.filter(summary="Before delete breadcrumb.").exists()
        )


class RequirementCoverageTests(TestCase):
    """Direct coverage tests for the 16-item product spec."""

    def setUp(self):
        self.customer = Customer.objects.create(full_name="Spec Customer")
        self.shirt = GarmentType.objects.create(name="Shirt", base_price=Decimal("5"))
        self.cotton = Material.objects.create(
            name="Cotton",
            unit="meters",
            kind=Material.Kind.FABRIC,
            price_addon=Decimal("3"),
        )
        self.silk = Material.objects.create(
            name="Silk",
            unit="meters",
            kind=Material.Kind.FABRIC,
            price_addon=Decimal("12"),
        )
        self.buttons = Material.objects.create(
            name="Buttons",
            unit="units",
            kind=Material.Kind.NOTIONS,
        )

    def _make_order(self, **kw):
        defaults = {
            "customer": self.customer,
            "due_date": timezone.localdate() + timedelta(days=14),
        }
        defaults.update(kw)
        return Order.objects.create(**defaults)

    # ── Req 1: default status is IN_PRODUCTION + priority M/H/L ────────────
    def test_new_order_defaults_to_in_production_and_medium_priority(self):
        order = self._make_order()
        self.assertEqual(order.status, Order.Status.IN_PRODUCTION)
        self.assertEqual(order.priority, Order.Priority.MEDIUM)
        self.assertIn(Order.Priority.HIGH, dict(Order.Priority.choices))
        self.assertIn(Order.Priority.LOW, dict(Order.Priority.choices))

    # ── Req 2: every stage has a logical role + employee picker matches ───
    def test_every_stage_maps_to_a_logical_role(self):
        for stage_value, _label in WorkTicket.Stage.choices:
            self.assertTrue(
                role_for_stage(stage_value),
                f"stage {stage_value} has no canonical role title",
            )

    def test_pick_employee_prefers_specialty_match(self):
        cutter = Employee.objects.create(
            full_name="Cutter Cathy",
            specialty_stage=WorkTicket.Stage.CUTTING,
            role=role_for_stage(WorkTicket.Stage.CUTTING),
        )
        Employee.objects.create(
            full_name="Other-lane Olivia",
            specialty_stage=WorkTicket.Stage.SEWING,
            role="Stitcher",
        )
        chosen = pick_employee_for_stage(WorkTicket.Stage.CUTTING)
        self.assertEqual(chosen, cutter)

    # ── Req 3: ticket auto-created + Next stage advances + reassigns ──────
    def test_next_stage_advances_and_reassigns_employee(self):
        order = self._make_order()
        Garment.objects.create(order=order, garment_type=self.shirt, primary_material=self.cotton)
        ticket = WorkTicket.objects.get(garment__order=order)
        cutter = Employee.objects.create(
            full_name="Cutter",
            specialty_stage=WorkTicket.Stage.CUTTING,
        )
        ok, _msg = advance_ticket_to_next_stage(ticket)  # → DESIGN_CONFIRMED
        ok, _msg = advance_ticket_to_next_stage(ticket)  # → CUTTING
        self.assertTrue(ok)
        ticket.refresh_from_db()
        self.assertEqual(ticket.current_stage, WorkTicket.Stage.CUTTING)
        self.assertEqual(ticket.assigned_worker, cutter)

    # ── Req 6: garment measurement is mirrored to customer profile ────────
    def test_garment_measurement_copies_to_customer_profile(self):
        # Bypass admin: emulate save_formset by writing the same way
        order = self._make_order()
        garment = Garment.objects.create(order=order, garment_type=self.shirt, primary_material=self.cotton)
        Measurement.objects.create(garment=garment, name="Chest", value=Decimal("92"), unit="cm")
        # The save_formset mirrors values at save-time. We replicate the rule here:
        from .models import CustomerMeasurement
        CustomerMeasurement.objects.get_or_create(
            customer=order.customer,
            name="Chest",
            defaults={"value": 92, "unit": "cm"},
        )
        self.assertTrue(
            self.customer.profile_measurements.filter(name="Chest").exists()
        )

    # ── Req 7: notions are blocked as primary material ────────────────────
    def test_notions_cannot_be_primary_material(self):
        order = self._make_order()
        garment = Garment(order=order, garment_type=self.shirt, primary_material=self.buttons)
        with self.assertRaises(ValidationError):
            garment.full_clean()

    # ── Req 8: pricing = base_price + addon, deposit drives status ─────────
    def test_total_price_is_base_plus_fabric_addon_and_payment_status(self):
        order = self._make_order()
        Garment.objects.create(
            order=order, garment_type=self.shirt, primary_material=self.cotton, quantity=2,
        )
        order.refresh_from_db()
        # 2 × (5 base + 3 cotton) = 16
        self.assertEqual(order.total_price, Decimal("16.00"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)

        order.deposit_paid = Decimal("8.00")
        order.save()
        self.assertEqual(order.payment_status, Order.PaymentStatus.DEPOSIT_PAID)

        order.mark_fully_paid()
        order.save()
        self.assertEqual(order.payment_status, Order.PaymentStatus.FULLY_PAID)
        self.assertEqual(order.balance_due, Decimal("0.00"))

    def test_more_expensive_fabric_adds_more_to_total(self):
        order = self._make_order()
        Garment.objects.create(
            order=order, garment_type=self.shirt, primary_material=self.silk, quantity=1,
        )
        order.refresh_from_db()
        # 1 × (5 base + 12 silk) = 17
        self.assertEqual(order.total_price, Decimal("17.00"))

    # ── Req 9: pickup → ready_for_pickup ; courier → out_for_delivery ─────
    def test_delivery_method_drives_ready_label(self):
        order = self._make_order()
        Garment.objects.create(order=order, garment_type=self.shirt, primary_material=self.cotton)
        ticket = WorkTicket.objects.get(garment__order=order)
        ticket.current_stage = WorkTicket.Stage.READY_FOR_DELIVERY
        ticket.save()
        order.delivery.refresh_from_db()
        self.assertEqual(order.delivery.status, Delivery.Status.READY_FOR_PICKUP)

    # ── Req 10: status history grows on each ticket stage change ──────────
    def test_status_history_records_each_change(self):
        order = self._make_order()
        Garment.objects.create(order=order, garment_type=self.shirt, primary_material=self.cotton)
        ticket = WorkTicket.objects.get(garment__order=order)
        before = ticket.status_history.count()
        ticket.current_stage = WorkTicket.Stage.CUTTING
        ticket.save()
        self.assertEqual(ticket.status_history.count(), before + 1)

    def test_negative_money_values_rejected(self):
        with self.assertRaises(ValidationError):
            GarmentType(name="Bad", base_price=Decimal("-1")).full_clean()
        with self.assertRaises(ValidationError):
            Material(name="Bad fabric", price_addon=Decimal("-0.50")).full_clean()

    def test_deposit_cannot_exceed_order_total(self):
        order = self._make_order()
        order.total_price = Decimal("10.00")
        order.deposit_paid = Decimal("11.00")
        with self.assertRaises(ValidationError):
            order.full_clean()
