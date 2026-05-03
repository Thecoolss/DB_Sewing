# Requirements Description

## Main Features

- Customer registration and profile management.
- Order management with due dates, statuses, and notes.
- Multi-item garment support per order.
- Work ticket generation and tracking by production stage.
- Admin workflow actions that generate missing tickets from selected orders or garments.
- Worker assignment and ticket prioritization.
- Delivery status and date tracking, including automatic linked order status updates.
- Monitoring views for pending, production, overdue, and completed work.

## Business Rules

1. Every order belongs to exactly one customer.
2. An order can contain one or more garments.
3. A garment can generate one or more work tickets.
4. Every ticket must have a current production stage.
5. Completed or delivered orders cannot keep tickets in active production stages.
6. Delivered deliveries require a delivery date.
7. Due dates are mandatory and used to detect overdue work.

## Modules

- Customer module
- Order module
- Garment details module
- Work ticket module
- Production status history module
- Delivery module
- Monitoring/report module

## Workflows Supported

- Customer Order Creation
- Ticket Creation and Production Follow-up
- Order Completion and Delivery
