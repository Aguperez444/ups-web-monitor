import math
import os
import shlex
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ups.sqlite3"
DEFAULT_RETENTION_HOURS = 24 * 30  # 30 days
DEFAULT_STALE_RECOVERY_COOLDOWN_SECONDS = 60.0
DEFAULT_STALE_RECOVERY_TIMEOUT_SECONDS = 15.0
DEFAULT_STALE_RECOVERY_RETRY_DELAY_SECONDS = 1.5


def default_user_db_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "ups-monitor" / "ups.sqlite3"


def _positive_env(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} debe ser un número finito mayor que cero.")
    return value


def _non_negative_env(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} debe ser un número finito mayor o igual que cero.")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} debe ser true o false.")


def _command_env(name: str) -> tuple[str, ...] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        parts = tuple(shlex.split(raw))
    except ValueError as error:
        raise ValueError(f"{name} tiene una sintaxis de comando inválida: {error}") from error
    if not parts:
        return None
    return parts


@dataclass(frozen=True, slots=True)
class Settings:
    ups_name: str = "ups@localhost"
    db_path: Path = DEFAULT_DB_PATH
    upsc_timeout_seconds: float = 3
    sample_interval_seconds: float = 10
    retention: timedelta = timedelta(hours=DEFAULT_RETENTION_HOURS)
    cleanup_interval_seconds: float = 60
    frontend_dist: Path | None = None
    stale_recovery_enabled: bool = True
    stale_recovery_command: tuple[str, ...] | None = None
    stale_recovery_cooldown_seconds: float = DEFAULT_STALE_RECOVERY_COOLDOWN_SECONDS
    stale_recovery_timeout_seconds: float = DEFAULT_STALE_RECOVERY_TIMEOUT_SECONDS
    stale_recovery_retry_delay_seconds: float = DEFAULT_STALE_RECOVERY_RETRY_DELAY_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        ups_name = os.environ.get("UPS_NAME", "ups@localhost").strip()
        if not ups_name or ups_name.startswith("-"):
            raise ValueError("UPS_NAME debe identificar un UPS para upsc, por ejemplo ups@localhost.")
        retention = timedelta(hours=_positive_env("UPS_RETENTION_HOURS", DEFAULT_RETENTION_HOURS))
        if retention <= timedelta(0):
            raise ValueError("UPS_RETENTION_HOURS es demasiado pequeño.")
        frontend_dist_raw = os.environ.get("UPS_FRONTEND_DIST", "").strip()
        frontend_dist = Path(frontend_dist_raw).expanduser() if frontend_dist_raw else None
        return cls(
            ups_name=ups_name,
            db_path=Path(os.environ.get("UPS_DB_PATH", str(DEFAULT_DB_PATH))).expanduser(),
            upsc_timeout_seconds=_positive_env("UPS_UPSC_TIMEOUT_SECONDS", 3),
            sample_interval_seconds=_positive_env("UPS_SAMPLE_INTERVAL_SECONDS", 10),
            retention=retention,
            cleanup_interval_seconds=_positive_env("UPS_CLEANUP_INTERVAL_SECONDS", 60),
            frontend_dist=frontend_dist,
            stale_recovery_enabled=_bool_env("UPS_STALE_RECOVERY_ENABLED", True),
            stale_recovery_command=_command_env("UPS_STALE_RECOVERY_COMMAND"),
            stale_recovery_cooldown_seconds=_non_negative_env(
                "UPS_STALE_RECOVERY_COOLDOWN_SECONDS",
                DEFAULT_STALE_RECOVERY_COOLDOWN_SECONDS,
            ),
            stale_recovery_timeout_seconds=_positive_env(
                "UPS_STALE_RECOVERY_TIMEOUT_SECONDS",
                DEFAULT_STALE_RECOVERY_TIMEOUT_SECONDS,
            ),
            stale_recovery_retry_delay_seconds=_non_negative_env(
                "UPS_STALE_RECOVERY_RETRY_DELAY_SECONDS",
                DEFAULT_STALE_RECOVERY_RETRY_DELAY_SECONDS,
            ),
        )
