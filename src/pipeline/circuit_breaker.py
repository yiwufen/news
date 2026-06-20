"""Circuit breaker for entity enhancement dependencies.

Prevents cascading dirty-data production when an enhancement API (entity
description / alias / embedding generation) fails repeatedly — e.g. when an
offline LLM quota is exhausted. Without this, enhancement failures are silently
swallowed and the entity resolver keeps creating "half-baked" entities
(canonical name only, no aliases/description), which downstream documents fail
to match — the documented root cause of the 2026-05 duplicate-entity outbreak.

The breaker is purely in-memory: state resets when the pipeline process
restarts. That is sufficient to stop a cascading outage; sustained recovery is
signalled by restarting the ingestion loop after the API is healthy again.
"""

from __future__ import annotations


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker has tripped.

    The pipeline run that observes this should stop processing further
    documents in the current run rather than continue producing entities that
    cannot be enhanced.
    """


class CircuitBreaker:
    """Consecutive-failure circuit breaker.

    Tracks how many entity-enhancement calls have failed in a row. Once the
    count reaches ``failure_threshold`` the breaker trips and ``check`` raises
    :class:`CircuitOpenError`. A single success resets the counter, so
    transient blips do not trip the breaker while a genuine outage does.
    """

    def __init__(self, failure_threshold: int = 5) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._failure_threshold = failure_threshold
        self._consecutive_failures = 0
        self._tripped = False

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    def record_failure(self, reason: str = "") -> None:
        """Record one enhancement failure; trip when the threshold is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and not self._tripped:
            self._tripped = True

    def record_success(self) -> None:
        """Record one enhancement success; reset the failure counter."""
        self._consecutive_failures = 0
        self._tripped = False

    def check(self) -> None:
        """Raise :class:`CircuitOpenError` if the breaker has tripped."""
        if self._tripped:
            raise CircuitOpenError(
                f"Circuit breaker tripped: {self._consecutive_failures} consecutive "
                f"entity-enhancement failures (threshold={self._failure_threshold}). "
                "Aborting to prevent cascading dirty data — check enhancement API "
                "(LLM quota / embedding service) and restart after recovery."
            )
