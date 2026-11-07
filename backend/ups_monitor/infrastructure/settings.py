import math
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "ups.sqlite3"
DEFAULT_RETENTION_HOURS = 24 * 30  # 30 days


def default_user_db_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "ups-monitor" / "ups.sqlite3"


def _positive_env(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} debe ser un número finito mayor que cero.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    ups_name: str = "ups@localhost"
    db_path: Path = DEFAULT_DB_PATH
    upsc_timeout_seconds: float = 3
    sample_interval_seconds: float = 10
    retention: timedelta = timedelta(hours=DEFAULT_RETENTION_HOURS)
    cleanup_interval_seconds: float = 60
    frontend_dist: Path | None = None

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
        )
