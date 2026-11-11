from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from ..application.monitor import HistoryResult
from ..domain.telemetry import ChargerState, Mode, Sample


class ErrorResponse(BaseModel):
    detail: str


class TelemetryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str | None
    input_voltage: float | None
    output_voltage: float | None
    output_frequency: float | None
    load_percent: float | None
    battery_voltage: float | None
    battery_charge: float | None


class SummaryResponse(TelemetryResponse):
    raw: dict[str, str]


SampleResponseType = TypeVar("SampleResponseType", bound="SampleResponse")


class SampleResponse(TelemetryResponse):
    timestamp: datetime
    mode: Mode

    @classmethod
    def from_sample(cls: type[SampleResponseType], sample: Sample, **extra: object) -> SampleResponseType:
        values = TelemetryResponse.model_validate(sample.telemetry).model_dump()
        return cls(
            **values,
            timestamp=sample.timestamp,
            mode=sample.telemetry.mode,
            **extra,
        )


class CurrentResponse(SampleResponse):
    ups_name: str
    manufacturer: str | None
    model: str | None
    charger: ChargerState | None


class MetricsResponse(BaseModel):
    start: datetime
    end: datetime
    sample_interval_seconds: float
    bucket_seconds: float | None
    samples: list[SampleResponse]

    @classmethod
    def from_result(cls, result: HistoryResult) -> "MetricsResponse":
        return cls(
            start=result.start,
            end=result.end,
            sample_interval_seconds=result.sample_interval_seconds,
            bucket_seconds=result.history.bucket_seconds,
            samples=[SampleResponse.from_sample(sample) for sample in result.history.samples],
        )
