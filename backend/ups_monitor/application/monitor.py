from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..domain.ports import History, SampleStore, SourceUnavailable, UpsSource
from ..domain.telemetry import Reading


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvalidHistoryRange(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HistoryResult:
    start: datetime
    end: datetime
    sample_interval_seconds: float
    history: History


@dataclass(frozen=True, slots=True)
class Monitor:
    source: UpsSource
    store: SampleStore
    retention: timedelta
    sample_interval_seconds: float
    clock: Callable[[], datetime] = utc_now

    def read(self) -> Reading:
        return self.source.read()

    def current(self) -> Reading:
        reading = self.read()
        if not reading.sample.telemetry.usable:
            raise SourceUnavailable("NUT todavía no devuelve telemetría utilizable del UPS.")
        return reading

    def capture(self) -> None:
        self.store.save(self.current().sample)

    def purge(self) -> None:
        self.store.delete_before(self.clock() - self.retention)

    def history(
        self, start: datetime | None, end: datetime | None, max_points: int,
        *, window_minutes: int | None = None,
    ) -> HistoryResult:
        if max_points < 3:
            raise InvalidHistoryRange("max_points debe ser al menos 3.")
        if start is not None and window_minutes is not None:
            raise InvalidHistoryRange("Usá start o window_minutes para seleccionar el inicio.")
        now = self.clock()
        end = end if end is not None else now
        if end.tzinfo is None or (start is not None and start.tzinfo is None):
            raise InvalidHistoryRange("Indicá la zona horaria de start y end.")
        try:
            end = end.astimezone(timezone.utc)
            start = (
                start.astimezone(timezone.utc)
                if start is not None
                else end - timedelta(minutes=60 if window_minutes is None else window_minutes)
            )
        except OverflowError as error:
            raise InvalidHistoryRange("El rango está fuera de las fechas admitidas.") from error
        if start >= end:
            raise InvalidHistoryRange("start debe ser anterior a end.")

        retained_start = max(start, now - self.retention)
        history = (
            self.store.query(retained_start, end, max_points)
            if retained_start <= end
            else History([])
        )
        return HistoryResult(start, end, self.sample_interval_seconds, history)
