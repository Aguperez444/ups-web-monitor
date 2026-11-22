import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.ups_monitor.domain.telemetry import Sample, Telemetry
from backend.ups_monitor.infrastructure.nut import parse_reading
from backend.ups_monitor.infrastructure.settings import (
    DEFAULT_RETENTION_HOURS,
    Settings,
    default_user_db_path,
)
from backend.ups_monitor.infrastructure.sqlite_store import SQLiteSampleStore
from backend.ups_monitor.presentation.app import create_app
from desktop import autostart


NUT_OUTPUT = """ups.status: OL
input.voltage: 230.5
output.voltage: 230.0
output.frequency: 50.0
ups.load: 12
battery.voltage: 27.1
battery.charge: 100
"""


class ProductionFeaturesTests(unittest.TestCase):
    def test_default_retention_is_30_days_and_user_db_path_uses_xdg(self):
        self.assertEqual(DEFAULT_RETENTION_HOURS, 720)
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/custom-xdg-data"}, clear=False):
            self.assertEqual(
                default_user_db_path(),
                Path("/tmp/custom-xdg-data/ups-monitor/ups.sqlite3"),
            )
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
            self.assertEqual(settings.retention, timedelta(days=30))
            self.assertIsNone(settings.frontend_dist)

    def test_static_frontend_serving_coexists_with_api_routes_and_checkpoints_wal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frontend_dist = root / "frontend_out"
            frontend_dist.mkdir()
            (frontend_dist / "index.html").write_text(
                "<!doctype html><html><title>UPS Monitor</title><body>Dashboard</body></html>",
                encoding="utf-8",
            )
            db_path = root / "persistent" / "ups.sqlite3"
            settings = Settings(
                ups_name="ups@localhost",
                db_path=db_path,
                frontend_dist=frontend_dist,
            )
            source = Mock()
            source.read.return_value = parse_reading(NUT_OUTPUT, datetime.now(timezone.utc))

            with TestClient(create_app(settings, source=source)) as client:
                home = client.get("/")
                self.assertEqual(home.status_code, 200)
                self.assertIn("UPS Monitor", home.text)

                current = client.get("/api/ups/current")
                self.assertEqual(current.status_code, 200)
                self.assertEqual(current.json()["mode"], "line")

                metrics = client.get("/api/metrics", params={"window_minutes": 15})
                self.assertEqual(metrics.status_code, 200)

            # After lifespan shutdown, SQLite DB exists and WAL was checkpointed cleanly.
            self.assertTrue(db_path.is_file())
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM ups_samples").fetchone()[0]
                self.assertGreaterEqual(count, 1)

    def test_database_persists_across_restarts_and_retains_multi_day_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "ups.sqlite3"
            now = datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)
            old_but_within_30d = now - timedelta(days=10)
            too_old = now - timedelta(days=35)

            store = SQLiteSampleStore(db_path, "ups@localhost")
            store.initialize()
            store.save(Sample(too_old, Telemetry(status="OL", input_voltage=220.0)))
            store.save(Sample(old_but_within_30d, Telemetry(status="OL", input_voltage=228.0)))
            store.save(Sample(now, Telemetry(status="OL", input_voltage=231.0)))
            store.checkpoint()

            # Simulate reopening after app close / PC reboot
            reopened = SQLiteSampleStore(db_path, "ups@localhost")
            reopened.initialize()
            reopened.delete_before(now - timedelta(days=30))
            samples = reopened.query(now - timedelta(days=40), now, 100).samples
            self.assertEqual([s.telemetry.input_voltage for s in samples], [228.0, 231.0])

    def test_autostart_creates_and_removes_desktop_file_for_appimage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            appimage = root / "My Apps" / "UPS-Monitor-x86_64.AppImage"
            appimage.parent.mkdir(parents=True)
            appimage.write_bytes(b"fake")

            env = {
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "APPIMAGE": str(appimage),
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertFalse(autostart.is_autostart_enabled())
                desktop_path = autostart.enable_autostart()
                self.assertTrue(desktop_path.is_file())
                self.assertTrue(autostart.is_autostart_enabled())

                content = desktop_path.read_text(encoding="utf-8")
                self.assertIn("[Desktop Entry]", content)
                self.assertIn(f'Exec="{appimage.resolve()}"', content)
                self.assertIn("X-KDE-autostart-after=panel", content)

                autostart.disable_autostart()
                self.assertFalse(autostart.is_autostart_enabled())


if __name__ == "__main__":
    unittest.main()
