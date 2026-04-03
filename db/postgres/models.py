"""SQLAlchemy ORM models for PostgreSQL — maps to tables defined in schema.sql (no DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for ORM mapping only (no Base.metadata.create_all)."""

    pass


class User(Base):
    """Application user row (``users`` table)."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    email_verification_token_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_verification_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    password_reset_token_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    password_reset_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.current_timestamp(),
        nullable=False,
    )
