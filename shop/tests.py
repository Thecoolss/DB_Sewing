from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import (
    Customer,
    Delivery,
    Employee,
    Garment,
    GarmentType,
    Material,
    Measurement,
    Order,
    WorkTicket,
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
        self.assertEqual(self.order.delivery.status, Delivery.Status.READY)

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
