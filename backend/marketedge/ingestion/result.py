"""What an ingest pass actually accomplished.

The dedup trigger means "rows attempted" says nothing about whether anything was
recorded — a healthy steady-state poll and a completely broken one both attempt
the same number of rows. Until the ingest reports rows WRITTEN, no health check
built on top of it can tell those apart, which is how 896 consecutive failures
went unnoticed for a week.

``rows_written`` is measured as a row-count delta inside the ingest's own
transaction. It cannot come from the INSERT's ``rowcount``: the executemany
result exposes no such attribute, and even where a driver reports one it counts
rows sent, not rows the trigger let through.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one ingest pass over one source."""

    source: str
    events_seen: int = 0
    events_skipped: int = 0
    rows_attempted: int = 0
    rows_written: int = 0  # what the dedup trigger actually let through

    @property
    def rows_suppressed(self) -> int:
        """Attempted-but-unchanged rows. Normal and healthy; not an error."""
        return max(0, self.rows_attempted - self.rows_written)

    def __str__(self) -> str:
        return (
            f"{self.source}: {self.events_seen} events "
            f"({self.events_skipped} skipped), {self.rows_written} rows written, "
            f"{self.rows_suppressed} unchanged"
        )
