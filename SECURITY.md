# Security Notes

If a database password, API key, or `SECRET_KEY` was ever pasted into `.env.example`, committed to git, uploaded to coursework portals, or shared in chat/screenshots:

1. Rotate the impacted Supabase database password immediately in the Supabase dashboard.
2. Regenerate `SECRET_KEY` locally (never reuse committed keys).
3. Revoke/leak-scan any forks or zipped submissions that may include secrets.

Operational guidance:

- Commit only `.env.example` with placeholders.
- Keep `.gitignore` ignoring `.venv/`, `.env`, SQLite files, caches, etc.
