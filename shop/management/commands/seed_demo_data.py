from datetime import timedelta
from random import choice, randint

from django.core.management.base import BaseCommand
from django.utils import timezone

from shop.models import (
    Customer,
    Delivery,
    Employee,
    Garment,
    GarmentType,
    GarmentMaterial,
    Material,
    Measurement,
    Order,
    WorkTicket,
)


class Command(BaseCommand):
    help = "Create demo sewing shop data for testing workflows."

    def handle(self, *args, **options):
        today = timezone.localdate()

        workers = []
        for name in ["Amira Nassar", "Lina Haddad", "Omar Khoury"]:
            worker, _ = Employee.objects.get_or_create(full_name=name, defaults={"role": "Tailor"})
            workers.append(worker)

        materials = []
        for material_name in ["Cotton Fabric", "Linen Fabric", "Polyester Thread", "Buttons"]:
            material, _ = Material.objects.get_or_create(name=material_name, defaults={"unit": "units"})
            materials.append(material)

        garment_types = []
        for type_name in ["Dress", "Shirt", "Skirt", "Blazer"]:
            garment_type, _ = GarmentType.objects.get_or_create(name=type_name)
            garment_types.append(garment_type)

        # Pick ticket stages and delivery status that don't violate model rules.
        in_production_stages = [
            WorkTicket.Stage.DESIGN_CONFIRMED,
            WorkTicket.Stage.CUTTING,
            WorkTicket.Stage.SEWING,
            WorkTicket.Stage.FINISHING,
            WorkTicket.Stage.QUALITY_CHECK,
        ]
        order_status_cycle = [
            Order.Status.DRAFT,
            Order.Status.IN_PRODUCTION,
            Order.Status.COMPLETED,
            Order.Status.DELIVERED,
            Order.Status.IN_PRODUCTION,
        ]

        for idx in range(1, 6):
            customer, _ = Customer.objects.get_or_create(
                full_name=f"Customer {idx}",
                defaults={
                    "phone": f"+100000000{idx}",
                    "email": f"customer{idx}@example.com",
                    "preferences": "Prefers fitting appointment before final delivery.",
                },
            )

            order_status = order_status_cycle[(idx - 1) % len(order_status_cycle)]
            order, _ = Order.objects.get_or_create(
                customer=customer,
                due_date=today + timedelta(days=7 + idx),
                defaults={
                    "assigned_employee": choice(workers),
                    "status": order_status,
                    "notes": "Auto-generated demo order.",
                },
            )

            if order_status == Order.Status.DRAFT:
                ticket_stage = WorkTicket.Stage.ORDER_RECEIVED
            elif order_status == Order.Status.IN_PRODUCTION:
                ticket_stage = choice(in_production_stages)
            elif order_status == Order.Status.COMPLETED:
                ticket_stage = WorkTicket.Stage.READY_FOR_DELIVERY
            elif order_status == Order.Status.DELIVERED:
                ticket_stage = WorkTicket.Stage.DELIVERED
            else:
                ticket_stage = WorkTicket.Stage.ORDER_RECEIVED

            for garment_idx in range(1, 3):
                garment, _ = Garment.objects.get_or_create(
                    order=order,
                    garment_type=choice(garment_types),
                    defaults={
                        "primary_material": choice(materials),
                        "quantity": randint(1, 2),
                        "color": choice(["Blue", "Black", "Green"]),
                        "design_notes": "Slim fit with simple lining.",
                    },
                )

                Measurement.objects.get_or_create(
                    garment=garment,
                    name="Chest",
                    defaults={"value": 90 + garment_idx, "unit": "cm"},
                )
                Measurement.objects.get_or_create(
                    garment=garment,
                    name="Length",
                    defaults={"value": 110 + garment_idx, "unit": "cm"},
                )

                GarmentMaterial.objects.get_or_create(
                    garment=garment,
                    material=choice(materials),
                    defaults={"quantity": 2.5},
                )

                WorkTicket.objects.get_or_create(
                    garment=garment,
                    deadline=order.due_date,
                    defaults={
                        "assigned_worker": choice(workers),
                        "priority": choice(list(WorkTicket.Priority.values)),
                        "current_stage": ticket_stage,
                        "notes": "Auto-generated ticket.",
                    },
                )

            if order_status == Order.Status.COMPLETED:
                delivery_status = Delivery.Status.READY
                delivered_date = None
            elif order_status == Order.Status.DELIVERED:
                delivery_status = Delivery.Status.DELIVERED
                delivered_date = today
            else:
                delivery_status = Delivery.Status.PENDING
                delivered_date = None

            Delivery.objects.get_or_create(
                order=order,
                defaults={
                    "method": Delivery.Method.PICKUP,
                    "status": delivery_status,
                    "scheduled_date": order.due_date,
                    "delivered_date": delivered_date,
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
