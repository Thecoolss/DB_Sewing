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
        ticket = self.garment.create_default_ticket()

        self.assertEqual(ticket.garment, self.garment)
        self.assertEqual(ticket.deadline, self.order.due_date)
        self.assertEqual(ticket.current_stage, WorkTicket.Stage.ORDER_RECEIVED)
        self.assertEqual(self.garment.tickets.count(), 1)

    def test_delivery_marks_order_delivered(self):
        delivery = Delivery.objects.create(
            order=self.order,
            status=Delivery.Status.DELIVERED,
        )

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

    def test_delivery_blocked_when_tickets_in_active_production(self):
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.SEWING
        ticket.save()

        delivery = Delivery(
            order=self.order,
            status=Delivery.Status.READY,
        )

        with self.assertRaises(ValidationError):
            delivery.full_clean()

    def test_delivery_to_delivered_requires_all_tickets_delivered(self):
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.READY_FOR_DELIVERY
        ticket.save()

        delivery = Delivery(
            order=self.order,
            status=Delivery.Status.DELIVERED,
            delivered_date=timezone.localdate(),
        )

        with self.assertRaises(ValidationError):
            delivery.full_clean()

    def test_delivered_order_cannot_regress(self):
        ticket = self.garment.create_default_ticket()
        ticket.current_stage = WorkTicket.Stage.DELIVERED
        ticket.save()

        Delivery.objects.create(
            order=self.order,
            status=Delivery.Status.DELIVERED,
        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

        self.order.status = Order.Status.IN_PRODUCTION
        with self.assertRaises(ValidationError):
            self.order.full_clean()
