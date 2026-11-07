import math
import subprocess
from datetime import datetime, timezone

from ..domain.ports import SourceUnavailable
from ..domain.telemetry import ChargerState, Reading, Sample, Telemetry


def _number(raw: dict[str, str], key: str, *, maximum: float = math.inf) -> float | None:
    try:
        value = float(raw[key])
    except (KeyError, ValueError):
        return None
    return value if math.isfinite(value) and 0 <= value <= maximum else None


def _charger_state(raw: dict[str, str], telemetry: Telemetry) -> ChargerState | None:
    reported = raw.get("battery.charger.status")
    if reported:
        try:
            return ChargerState(reported.casefold())
        except ValueError:
            return None

    flags = telemetry.flags
    if "CHRG" in flags and "DISCHRG" not in flags:
        return ChargerState.CHARGING
    if "DISCHRG" in flags and "CHRG" not in flags:
        return ChargerState.DISCHARGING
    return None


def parse_reading(output: str, timestamp: datetime) -> Reading:
    raw = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip():
            raw[key.strip()] = value.strip()
    if not raw:
        raise SourceUnavailable("NUT no devolvió variables del UPS.")

    telemetry = Telemetry(
        status=raw.get("ups.status") or None,
        input_voltage=_number(raw, "input.voltage"),
        output_voltage=_number(raw, "output.voltage"),
        output_frequency=_number(raw, "output.frequency"),
        load_percent=_number(raw, "ups.load"),
        battery_voltage=_number(raw, "battery.voltage"),
        battery_charge=_number(raw, "battery.charge", maximum=100),
    )
    return Reading(
        sample=Sample(timestamp, telemetry),
        raw=raw,
        manufacturer=raw.get("ups.mfr") or raw.get("device.mfr") or None,
        model=raw.get("ups.model") or raw.get("device.model") or None,
        charger=_charger_state(raw, telemetry),
    )


class NutSource:
    def __init__(self, target: str, timeout: float) -> None:
        self.target = target
        self.timeout = timeout

    def read(self) -> Reading:
        try:
            result = subprocess.run(
                ["upsc", self.target],
                check=True,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout,
            )
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip() or error.stdout.strip() or str(error.returncode)
            raise SourceUnavailable(f"Error ejecutando upsc: {detail}") from error
        except subprocess.TimeoutExpired as error:
            raise SourceUnavailable("upsc agotó el tiempo de espera.") from error
        except OSError as error:
            raise SourceUnavailable(f"No se pudo ejecutar upsc: {error.strerror}.") from error

        return parse_reading(result.stdout, datetime.now(timezone.utc))
