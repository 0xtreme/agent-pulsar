"""Enumerations used across Agent Pulsar."""

from enum import Enum


class TaskStatus(str, Enum):
    """Lifecycle state of a task."""

    PENDING = "PENDING"          # Created, not yet dispatched
    CLAIMED = "CLAIMED"          # Picked up by supervisor, being decomposed
    IN_PROGRESS = "IN_PROGRESS"  # Dispatched to a worker, executing
    COMPLETED = "COMPLETED"      # Successfully finished
    FAILED = "FAILED"            # Exhausted retries or permanent failure
    DLQ = "DLQ"                  # Moved to dead-letter queue


class Priority(str, Enum):
    """Task priority level."""

    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionTier(str, Enum):
    """Execution isolation level for a task."""

    HOT = "hot"    # In-process async, ~100ms startup, process-level isolation
    WARM = "warm"  # Subprocess or pre-warmed container, ~1-2s startup
    COLD = "cold"  # Fresh Docker container, ~5-10s startup (Phase 2)


class ComplexityTier(str, Enum):
    """Task complexity classification — drives model selection."""

    SIMPLE = "simple"      # Haiku-class: email send, calendar check, lookups
    MODERATE = "moderate"  # Sonnet-class: research, drafting, document processing
    COMPLEX = "complex"    # Opus-class: payroll, financial ops, code generation
