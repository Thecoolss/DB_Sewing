# Workflow Documentation

## Workflow 1: Customer Order Creation

1. Staff creates or updates a customer profile.
2. Staff creates an order linked to the customer and sets due date/status.
3. Staff adds one or more garments to the order.
4. Staff records measurements and materials for each garment.
5. Order enters draft or production state.

## Workflow 2: Ticket Creation and Production Follow-up

1. Staff selects orders or garments in the admin and runs the generate missing work tickets action.
2. Staff assigns ticket priority and a worker/team member.
3. Staff updates ticket stages as work moves through production:
   - order received
   - design confirmed
   - cutting
   - sewing
   - finishing
   - quality check
   - ready for delivery
   - delivered
4. Each stage change is recorded in status history.

## Workflow 3: Order Completion and Delivery

1. Once garment tickets reach terminal stages, staff marks order completed.
2. Staff creates/updates delivery data (method, scheduled date, observations).
3. When delivery status is set to ready, the linked order is marked completed.
4. On customer pickup or shipment completion, staff sets delivery status to delivered.
5. The system stores the delivered date and moves the linked order to delivered.
