# Sewing Shop Management System

This project implements a complete sewing shop management system with Django, Django ORM, and a relational database (Supabase PostgreSQL supported via `DATABASE_URL`).

## Tech Stack

- Django backend
- Django Unfold admin interface
- PostgreSQL via Supabase (or SQLite fallback for local testing)
- Django ORM models and migrations

## Features

- Customer management with order history
- Order and garment management
- Ticket/work order management with priorities and stages
- Admin actions to generate missing work tickets from orders or garments
- Production stage tracking with status history
- Delivery completion tracking with linked order status updates
- Monitoring dashboard pages:
  - pending orders
  - orders in production
  - overdue orders
  - completed orders
  - ticket status summary
  - customer order history

## Setup

1. Create and activate a virtual environment:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Copy environment template:
   - `cp .env.example .env`
4. Configure secrets and database:
   - Set `SECRET_KEY` to a long random string
   - Set `DATABASE_URL` to your Supabase PostgreSQL URI in `.env` (see notes below)

If you accidentally paste real credentials inside `.env.example` or commit them to git, rotate the impacted Supabase credentials immediately—`.env.example` must stay sanitized for GitHub-ready repos.
5. Apply migrations:
   - `python manage.py migrate`
6. Create admin user:
   - `python manage.py createsuperuser`
7. (Optional) Load demo data:
   - `python manage.py seed_demo_data`
8. Run server:
   - `python manage.py runserver`

## Tests (optional)

If your `.env` points at Supabase/Postgres but you want quick local tests without outbound DB connectivity:

```bash
USE_SQLITE=1 python manage.py test shop
```

## Supabase Notes

Grab the Postgres connection URI from Supabase (`Project Settings -> Database -> Connection string`).

Prefer the **pooler/IPv4-friendly** URI if connecting from WSL/Windows setups where resolving the direct `db.<project>.supabase.co` hostname yields IPv6 and your network cannot route it.

Typical URIs:

- Pooler URI (recommended for many laptops/WSL setups):
  `postgresql://postgres.<PROJECT_REF>:<PASSWORD>@aws-0-<REGION>.pooler.supabase.com:5432/postgres?sslmode=require`
- Direct URI:
  `postgresql://postgres:<PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres?sslmode=require`

## GitHub-ready repo hygiene

- Don't commit `.env` (tracked in `.gitignore`)
- Commit `.env.example` with placeholders only
- Prefer CI for basic validation (see `.github/workflows/ci.yml`)

## Main Routes

- `/admin/` - Django Unfold admin
- `/` - dashboard
- `/orders/pending/`
- `/orders/production/`
- `/orders/overdue/`
- `/orders/completed/`
- `/customers/`
