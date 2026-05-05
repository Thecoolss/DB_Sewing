# Normalized Database Design

## Entities and Attributes

### Customer
- `id` (PK)
- `full_name`
- `phone`
- `email`
- `address`
- `notes`
- `preferences`

### Order
- `id` (PK)
- `reference` (unique)
- `customer_id` (FK -> Customer)
- `assigned_employee_id` (FK -> Employee, nullable)
- `order_date`
- `due_date`
- `status`
- `completed_at`
- `notes`

### GarmentType
- `id` (PK)
- `name` (unique)
- `description`
- `active`

### Garment
- `id` (PK)
- `order_id` (FK -> Order)
- `garment_type_id` (FK -> GarmentType)
- `primary_material_id` (FK -> Material, nullable)
- `quantity`
- `color`
- `design_notes`

### Measurement
- `id` (PK)
- `garment_id` (FK -> Garment)
- `name`
- `value`
- `unit`
- `notes`
- unique (`garment_id`, `name`)

### Material
- `id` (PK)
- `name` (unique)
- `description`
- `unit`

### GarmentMaterial
- `id` (PK)
- `garment_id` (FK -> Garment)
- `material_id` (FK -> Material)
- `quantity`
- `notes`
- unique (`garment_id`, `material_id`)

### Employee
- `id` (PK)
- `full_name`
- `role`
- `active`
- `phone`

### WorkTicket
- `id` (PK)
- `ticket_number` (unique)
- `garment_id` (FK -> Garment)
- `assigned_worker_id` (FK -> Employee, nullable)
- `current_stage`
- `priority`
- `deadline`
- `started_at`
- `completed_at`
- `notes`

### StatusHistory
- `id` (PK)
- `ticket_id` (FK -> WorkTicket)
- `stage`
- `changed_by_id` (FK -> User, nullable)
- `changed_at`
- `comments`

### Delivery
- `id` (PK)
- `order_id` (FK -> Order, one-to-one)
- `method`
- `status`
- `scheduled_date`
- `delivered_date`
- `final_observations`

## Normalization Decisions

- The design follows 3NF for operational data.
- Repeated garment type values are separated into `GarmentType`.
- Repeated material information is separated into `Material`.
- The many-to-many between garments and materials is resolved through `GarmentMaterial`.
- `Garment.primary_material` stores the main material selected during order intake, while `GarmentMaterial` remains the detailed material usage table.
- Repeated measurement pairs are normalized into `Measurement` records.
- Ticket progress is historized in `StatusHistory` instead of storing duplicate stage columns.

## Relationship Summary

- Customer 1..N Order
- Employee 1..N Order (optional assignment)
- Order 1..N Garment
- GarmentType 1..N Garment
- Garment 1..N WorkTicket
- WorkTicket 1..N StatusHistory
- Employee 1..N WorkTicket (optional assignment)
- Order 1..1 Delivery
- Garment N..M Material (via GarmentMaterial)
- Garment 1..N Measurement
