import logging
import math
import os
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from ..domain.ports import SourceUnavailable
from ..domain.telemetry import ChargerState, Reading, Sample, Telemetry

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})
_SYSTEMD_INSTANCE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SUDO_AUTH_MARKERS = (
    "sudo:",
    "password is required",
    "terminal is required",
    "not in the sudoers",
    "no tty present",
    "askpass",
)


def is_data_stale_error(detail: str) -> bool:
    normalized = detail.casefold()
    return "data stale" in normalized or "data-stale" in normalized


def _parse_nut_target(target: str) -> tuple[str, str]:
    ups_id, sep, host_part = target.partition("@")
    ups_id = ups_id.strip()
    if not sep:
        return ups_id, ""
    host_part = host_part.strip()
    if host_part.startswith("["):
        host, _, _ = host_part[1:].partition("]")
    elif host_part.count(":") == 1:
        host, _, _ = host_part.partition(":")
    else:
        host = host_part
    return ups_id, host.casefold()


def default_stale_recovery_commands(
    target: str, *, is_root: bool | None = None
) -> tuple[tuple[str, ...], ...]:
    ups_id, host = _parse_nut_target(target)
    if host not in _LOCAL_HOSTS or not _SYSTEMD_INSTANCE_RE.fullmatch(ups_id):
        return ()
    units = (f"nut-driver@{ups_id}.service", "nut-server.service")
    running_as_root = (getattr(os, "geteuid", lambda: -1)() == 0) if is_root is None else is_root
    if running_as_root:
        return (("systemctl", "--no-ask-password", "restart", *units),)
    return (
        ("sudo", "-n", "systemctl", "restart", *units),
        ("systemctl", "--no-ask-password", "restart", *units),
    )


def _is_sudo_auth_failure(command: tuple[str, ...], detail: str) -> bool:
    if not command or os.path.basename(command[0]) != "sudo":
        return False
    normalized = detail.casefold()
    return any(marker in normalized for marker in _SUDO_AUTH_MARKERS)


class StaleDataRecovery:
    def __init__(
        self,
        commands: tuple[tuple[str, ...], ...],
        *,
        cooldown_seconds: float = 60.0,
        timeout_seconds: float = 15.0,
        retry_delay_seconds: float = 1.5,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.commands = tuple(tuple(command) for command in commands if command)
        self.cooldown_seconds = cooldown_seconds
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_attempt_at: float | None = None

    def recover(self, detail: str) -> bool:
        if not self.commands:
            return False
        if not self._lock.acquire(blocking=False):
            logger.info("Reinicio de NUT ya en curso tras Data stale; omitiendo intento duplicado.")
            return False
        try:
            now = self._monotonic()
            if self._last_attempt_at is not None:
                elapsed = now - self._last_attempt_at
                if elapsed < self.cooldown_seconds:
                    logger.debug(
                        "Data stale detectado (%s), recuperación en espera (%.1fs restantes).",
                        detail,
                        self.cooldown_seconds - elapsed,
                    )
                    return False
            self._last_attempt_at = now
            recovered = self._run_commands(detail)
            self._last_attempt_at = self._monotonic()
            if recovered and self.retry_delay_seconds > 0:
                self._sleep(self.retry_delay_seconds)
            return recovered
        finally:
            self._lock.release()

    def _run_commands(self, detail: str) -> bool:
        for index, command in enumerate(self.commands):
            formatted = shlex.join(command)
            has_fallback = index + 1 < len(self.commands)
            logger.warning("Data stale detectado en upsc (%s). Ejecutando: %s", detail, formatted)
            try:
                subprocess.run(
                    list(command),
                    check=True,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=self.timeout_seconds,
                )
            except subprocess.CalledProcessError as error:
                last_error = (error.stderr or "").strip() or (error.stdout or "").strip() or str(error.returncode)
                if has_fallback and _is_sudo_auth_failure(command, last_error):
                    logger.info(
                        "No se pudo ejecutar '%s' sin contraseña (%s); probando alternativa.",
                        formatted,
                        last_error,
                    )
                    continue
                if _is_sudo_auth_failure(command, last_error) or "authentication required" in last_error.casefold():
                    logger.warning(
                        "No se pudo reiniciar NUT automáticamente tras Data stale (%s): %s. "
                        "Configurá NOPASSWD en sudoers o una regla de polkit para reiniciar los servicios de NUT.",
                        formatted,
                        last_error,
                    )
                else:
                    logger.warning("Falló el reinicio automático de NUT (%s): %s", formatted, last_error)
                return False
            except subprocess.TimeoutExpired:
                logger.warning(
                    "El reinicio automático de NUT (%s) agotó el tiempo de espera (%.1fs).",
                    formatted,
                    self.timeout_seconds,
                )
                return False
            except OSError as error:
                last_error = error.strerror or str(error)
                if has_fallback:
                    logger.info(
                        "No se pudo invocar '%s' (%s); probando alternativa.",
                        formatted,
                        last_error,
                    )
                    continue
                logger.warning("No se pudo ejecutar '%s': %s", formatted, last_error)
                return False
            else:
                logger.info("Servicios NUT reiniciados correctamente (%s).", formatted)
                return True

        return False


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
    def __init__(
        self,
        target: str,
        timeout: float,
        *,
        stale_recovery: StaleDataRecovery | None = None,
    ) -> None:
        self.target = target
        self.timeout = timeout
        self.stale_recovery = stale_recovery

    def _run_upsc(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["upsc", self.target],
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=self.timeout,
        )

    def _read_once(self) -> Reading:
        try:
            result = self._run_upsc()
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip() or (error.stdout or "").strip() or str(error.returncode)
            raise SourceUnavailable(f"Error ejecutando upsc: {detail}") from error
        except subprocess.TimeoutExpired as error:
            raise SourceUnavailable("upsc agotó el tiempo de espera.") from error
        except OSError as error:
            raise SourceUnavailable(f"No se pudo ejecutar upsc: {error.strerror}.") from error

        return parse_reading(result.stdout, datetime.now(timezone.utc))

    def read(self) -> Reading:
        try:
            result = self._run_upsc()
        except subprocess.CalledProcessError as error:
            stderr = (error.stderr or "").strip()
            stdout = (error.stdout or "").strip()
            detail = stderr or stdout or str(error.returncode)
            if self.stale_recovery is not None and is_data_stale_error(f"{stderr}\n{stdout}"):
                if self.stale_recovery.recover(detail):
                    return self._read_once()
            raise SourceUnavailable(f"Error ejecutando upsc: {detail}") from error
        except subprocess.TimeoutExpired as error:
            raise SourceUnavailable("upsc agotó el tiempo de espera.") from error
        except OSError as error:
            raise SourceUnavailable(f"No se pudo ejecutar upsc: {error.strerror}.") from error

        return parse_reading(result.stdout, datetime.now(timezone.utc))
