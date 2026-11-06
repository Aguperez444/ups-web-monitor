from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    LINE = "line"
    BATTERY = "battery"
    BYPASS = "bypass"
    OFF = "off"
    UNKNOWN = "unknown"


class ChargerState(str, Enum):
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FLOATING = "floating"
    RESTING = "resting"


@dataclass(frozen=True, slots=True)
class Telemetry:
    status: str | None = None
    input_voltage: float | None = None
    output_voltage: float | None = None
    output_frequency: float | None = None
    load_percent: float | None = None
    battery_voltage: float | None = None
    battery_charge: float | None = None

    @property
    def flags(self) -> frozenset[str]:
        return frozenset((self.status or "").upper().split())

    @property
    def mode(self) -> Mode:
        flags = self.flags
        if "WAIT" in flags:
            return Mode.UNKNOWN
        if "OFF" in flags:
            return Mode.OFF
        if "OB" in flags:
            if flags.intersection({"OL", "BYPASS"}):
                return Mode.UNKNOWN
            return Mode.BATTERY
        if "BYPASS" in flags:
            return Mode.BYPASS
        return Mode.LINE if "OL" in flags else Mode.UNKNOWN

    @property
    def usable(self) -> bool:
        return "WAIT" not in self.flags and any(
            getattr(self, field.name) is not None for field in fields(self)
        )


@dataclass(frozen=True, slots=True)
class Sample:
    timestamp: datetime
    telemetry: Telemetry


@dataclass(frozen=True, slots=True)
class Reading:
    sample: Sample
    raw: dict[str, str]
    manufacturer: str | None = None
    model: str | None = None
    charger: ChargerState | None = None
