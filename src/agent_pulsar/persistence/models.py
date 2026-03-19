"""SQLAlchemy ORM models for task persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TaskRequestRecord(Base):
    """Persisted high-level user request."""

    __tablename__ = "task_requests"

    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[str] = mapped_column(String(255))
    intent: Mapped[str] = mapped_column(String(255))
    raw_message: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AtomicTaskRecord(Base):
    """Persisted decomposed sub-task."""

    __tablename__ = "atomic_tasks"

    task_id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("task_requests.request_id"), index=True
    )
    type: Mapped[str] = mapped_column(String(255), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    execution_tier: Mapped[str] = mapped_column(String(10))
    model_assignment: Mapped[str] = mapped_column(String(100))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
