# Contributing

This repository is coursework-oriented but kept GitHub-friendly via a small CI workflow.

## Quick local checks

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py check
python manage.py migrate --noinput
USE_SQLITE=1 python manage.py test shop
```

Notes:

- If you omit `DATABASE_URL`, Django falls back to `db.sqlite3` for local experimentation.
- For Supabase Postgres, paste your Postgres URI into `.env` under `DATABASE_URL`.
- If your `.env` points at Postgres but you want fast offline tests, run with `USE_SQLITE=1`.

## Secrets

Never commit `.env`. Keep `.env.example` placeholder-only.
