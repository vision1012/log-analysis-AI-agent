#!/usr/bin/env python3
"""
Seed sample users into PostgreSQL (Supabase-compatible).

Requires ``POSTGRES_URL`` (same as the app). Logical labels ``user_001`` / ``user_002``
map to stable UUID strings in the ``users.user_id`` (TEXT) column.

Usage (from repo root)::

    export POSTGRES_URL=postgresql://user:pass@localhost:5432/dbname
    python scripts/seed_users.py
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any

# Allow ``import db.*`` when run as a script
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from db.postgres.connection import get_db_session
from db.postgres.repository import create_user, get_user_by_email, get_user_by_id
from security.passwords import hash_password

# Dev-only password for seeded accounts (change in production).
_SEED_PASSWORD = "seeddev123"

# Stable UUIDs for dev seeds (logical ids user_001 / user_002)
_NS = uuid.NAMESPACE_URL
USER_001_ID = uuid.uuid5(_NS, "log-analysis-ai-agent:seed:user_001")
USER_002_ID = uuid.uuid5(_NS, "log-analysis-ai-agent:seed:user_002")

SAMPLE_USERS: list[dict[str, Any]] = [
    {
        "label": "user_001",
        "user_id": USER_001_ID,
        "first_name": "Neel",
        "last_name": "Bhesaniya",
        "email": "neel@example.com",
        "role": "admin",
        "team": "platform",
    },
    {
        "label": "user_002",
        "user_id": USER_002_ID,
        "first_name": "Demo",
        "last_name": "User",
        "email": "demo@example.com",
        "role": "engineer",
        "team": "debugging",
    },
]


def main() -> int:
    if not os.environ.get("POSTGRES_URL", "").strip():
        print("Error: POSTGRES_URL is not set or empty.", file=sys.stderr)
        print("  Example: export POSTGRES_URL=postgresql://user:pass@localhost:5432/mydb", file=sys.stderr)
        return 1

    print("Seeding users (PostgreSQL).")
    print("  Note: user_id is TEXT; seeds use stable UUID strings below.\n")

    with get_db_session() as session:
        for row in SAMPLE_USERS:
            label = row["label"]
            uid = row["user_id"]
            email = row["email"]

            existing = get_user_by_id(session, uid) or get_user_by_email(session, email)
            if existing is not None:
                print(
                    f"  [SKIP] {label}  email={email!r}  user_id={uid}  "
                    f"(already present as user_id={existing.user_id})"
                )
                continue

            create_user(
                session,
                {
                    "user_id": uid,
                    "first_name": row["first_name"],
                    "last_name": row["last_name"],
                    "email": email,
                    "password_hash": hash_password(_SEED_PASSWORD),
                    "is_email_verified": True,
                    "role": row["role"],
                    "team": row["team"],
                },
            )
            print(
                f"  [OK]   {label}  name={row['first_name']!r} {row['last_name']!r}  email={email!r}  "
                f"user_id={uid}  role={row['role']!r}  team={row['team']!r}"
            )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
