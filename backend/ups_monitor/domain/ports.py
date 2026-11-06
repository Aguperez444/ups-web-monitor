from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .telemetry import Reading, Sample


class SourceUnavailable(Exception):
    """The telemetry source did not return a readable snapshot."""


class UpsSource(Protocol):
    def read(self) -> Reading: ...


@dataclass(frozen=True, slots=True)
class History:
    samples: list[Sample]
    bucket_seconds: float | None = None


class SampleStore(Protocol):
    def save(self, sample: Sample) -> None: ...
    def delete_before(self, cutoff: datetime) -> None: ...
    def query(self, start: datetime, end: datetime, max_points: int) -> History: ...
