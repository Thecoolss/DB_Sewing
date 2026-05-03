from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Customer, Delivery, Garment, Order, WorkTicket


class WorkflowAutomationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(full_name="Test Customer")
        self.order = Order.objects.create(
            customer=self.customer,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        self.garment = Garment.objects.create(
            order=self.order,
            garment_type="Dress",
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

# Create your tests here.
