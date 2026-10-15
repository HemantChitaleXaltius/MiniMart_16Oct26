# Code Review Notes

## Production-readiness classification

**Classification:** Prototype

**Evidence:** The Day 1 reliability and injection flaws were fixed, but authentication, route-level authorisation, and secrets management still require work. The project also has no automated tests.

## Backlog for Day 2

1. Replace plaintext passwords and the hardcoded `USERS` dictionary with hashed passwords in SQLite. **Urgency: Critical.**
2. Protect `/admin` and `/admin/add` with an admin-role check, not only a login check. **Urgency: Critical.**
3. Move the hardcoded Flask secret key out of `app.py`. **Urgency: High.**
4. Require login for cart and checkout actions. **Urgency: High.**
