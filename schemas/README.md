# `schemas/` — shared Pydantic models (API)

Cross-cutting request/response models used outside a single router file.

| File | Purpose |
|------|---------|
| `jobs.py` | Job create/response models |
| `users.py` | User request/response models |
| `auth.py` | Auth/login/signup/reset models |
| `jira.py` | Normalized JIRA ticket + extracted hints |
| `jira_rca.py` | JIRA RCA run request/response, log signals, explanation payload |
| `jira_investigations.py` | Investigation record models |

Imported by **`api/routes/`**, **`api/services/`**, and **`services/jobs_service.py`**.
