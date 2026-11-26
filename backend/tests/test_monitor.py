import asyncio
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.ups_monitor.application.monitor import InvalidHistoryRange, Monitor
from backend.ups_monitor.application.sampler import sample_periodically
from backend.ups_monitor.domain.ports import SourceUnavailable
from backend.ups_monitor.domain.telemetry import ChargerState, Mode, Sample, Telemetry
from backend.ups_monitor.infrastructure.nut import (
    NutSource,
    StaleDataRecovery,
    default_stale_recovery_commands,
    parse_reading,
)
from backend.ups_monitor.infrastructure.settings import Settings
from backend.ups_monitor.infrastructure.sqlite_store import SQLiteSampleStore
from backend.ups_monitor.presentation.app import create_app


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
NUT_OUTPUT = """ups.status: OL TRIM
input.voltage: 231.4
output.voltage: 230.0
output.frequency: 50.1
ups.load: 0
battery.voltage: 26.9
battery.charge: 90
device.model: Model: Test
battery.charger.status: floating
"""


class NutTests(unittest.TestCase):
    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_reads_upsc_with_a_timeout_and_parses_only_stdout(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["upsc"], 0, stdout=NUT_OUTPUT, stderr="SSL: initialization warning"
        )
        reading = NutSource("rack@nut", timeout=2).read()

        run.assert_called_once_with(
            ["upsc", "rack@nut"], check=True, capture_output=True, text=True,
            errors="replace", timeout=2,
        )
        self.assertEqual(
            reading.sample.telemetry,
            Telemetry("OL TRIM", 231.4, 230.0, 50.1, 0, 26.9, 90),
        )
        self.assertEqual(reading.sample.timestamp.utcoffset(), timedelta(0))
        self.assertEqual(reading.model, "Model: Test")
        self.assertEqual(reading.charger, ChargerState.FLOATING)
        self.assertNotIn("SSL", reading.raw)

    def test_missing_and_invalid_values_do_not_become_measurements(self):
        reading = parse_reading(
            "input.voltage: NaN\noutput.voltage: inf\nups.load: -1\n"
            "battery.charge: 101\nbattery.voltage: unknown\n",
            NOW,
        )
        self.assertEqual(reading.sample.telemetry, Telemetry())
        self.assertFalse(reading.sample.telemetry.usable)
        self.assertEqual(reading.raw["input.voltage"], "NaN")
        self.assertEqual(parse_reading("ups.load: 135", NOW).sample.telemetry.load_percent, 135)
        with self.assertRaises(SourceUnavailable):
            parse_reading("no structured data", NOW)

    def test_status_uses_documented_tokens_and_preserves_unknown_flags(self):
        for flags, expected in {
            "OL CHRG": Mode.LINE,
            "OB LB": Mode.BATTERY,
            "OL BYPASS": Mode.BYPASS,
            "OL OFF": Mode.OFF,
            "OL OB": Mode.UNKNOWN,
            "WAIT OL": Mode.UNKNOWN,
            "BOOST": Mode.UNKNOWN,
            None: Mode.UNKNOWN,
        }.items():
            with self.subTest(flags=flags):
                self.assertEqual(Telemetry(status=flags).mode, expected)
        self.assertFalse(Telemetry(status="WAIT", input_voltage=230).usable)
        self.assertEqual(parse_reading("ups.status: OL CHRG", NOW).charger, ChargerState.CHARGING)
        self.assertIsNone(parse_reading("ups.status: OL", NOW).charger)

    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_translates_driver_errors_timeouts_and_missing_executable(self, run):
        for error, detail in (
            (subprocess.CalledProcessError(1, "upsc", stderr="Error: Driver not connected"), "Driver"),
            (subprocess.TimeoutExpired("upsc", 1), "tiempo de espera"),
            (FileNotFoundError(2, "No such file"), "No se pudo ejecutar"),
        ):
            with self.subTest(error=error):
                run.side_effect = error
                with self.assertRaisesRegex(SourceUnavailable, detail):
                    NutSource("ups@localhost", 1).read()

    def test_default_stale_recovery_commands_match_local_targets_only(self):
        self.assertEqual(
            default_stale_recovery_commands("ups@localhost", is_root=False),
            (
                ("sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"),
                ("systemctl", "--no-ask-password", "restart", "nut-driver@ups.service", "nut-server.service"),
            ),
        )
        self.assertEqual(
            default_stale_recovery_commands("myups@127.0.0.1:3493", is_root=True),
            (("systemctl", "--no-ask-password", "restart", "nut-driver@myups.service", "nut-server.service"),),
        )
        self.assertEqual(
            default_stale_recovery_commands("ups@[::1]:3493", is_root=False)[0],
            ("sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"),
        )
        self.assertEqual(default_stale_recovery_commands("rack@192.168.1.10", is_root=False), ())

    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_restarts_nut_and_retries_reading_on_data_stale(self, run):
        slept: list[float] = []
        now = [100.0]
        recovery = StaleDataRecovery(
            default_stale_recovery_commands("ups@localhost", is_root=False),
            cooldown_seconds=60.0,
            timeout_seconds=15.0,
            retry_delay_seconds=1.5,
            monotonic=lambda: now[0],
            sleep=slept.append,
        )
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc", "ups@localhost"], stderr="Error: Data stale\n"),
            subprocess.CompletedProcess(["sudo"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["upsc", "ups@localhost"], 0, stdout=NUT_OUTPUT, stderr=""),
        ]

        reading = NutSource("ups@localhost", 3, stale_recovery=recovery).read()

        self.assertEqual(reading.sample.telemetry.input_voltage, 231.4)
        self.assertEqual(slept, [1.5])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"],
        )

    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_stale_recovery_respects_cooldown_and_ignores_non_stale_errors(self, run):
        now = [100.0]
        recovery = StaleDataRecovery(
            (("sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"),),
            cooldown_seconds=60.0,
            retry_delay_seconds=0.0,
            monotonic=lambda: now[0],
            sleep=lambda _: None,
        )
        source = NutSource("ups@localhost", 3, stale_recovery=recovery)

        # Non-stale error must not trigger recovery.
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Driver not connected"),
        ]
        with self.assertRaisesRegex(SourceUnavailable, "Driver not connected"):
            source.read()
        self.assertEqual(run.call_count, 1)

        # First stale error triggers restart; retry still fails -> raises without looping.
        run.reset_mock()
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Data stale"),
            subprocess.CompletedProcess(["sudo"], 0, stdout="", stderr=""),
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Data stale"),
        ]
        with self.assertRaisesRegex(SourceUnavailable, "Data stale"):
            source.read()
        self.assertEqual(run.call_count, 3)

        # Within cooldown (30s later) -> no restart attempt.
        now[0] = 130.0
        run.reset_mock()
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Data stale"),
        ]
        with self.assertRaisesRegex(SourceUnavailable, "Data stale"):
            source.read()
        self.assertEqual(run.call_count, 1)

        # After cooldown (61s after previous attempt) -> restarts again and recovers.
        now[0] = 161.0
        run.reset_mock()
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Data stale"),
            subprocess.CompletedProcess(["sudo"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["upsc"], 0, stdout=NUT_OUTPUT, stderr=""),
        ]
        reading = source.read()
        self.assertEqual(reading.sample.telemetry.status, "OL TRIM")
        self.assertEqual(run.call_count, 3)

    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_stale_recovery_falls_back_to_systemctl_when_sudo_needs_password(self, run):
        recovery = StaleDataRecovery(
            default_stale_recovery_commands("ups@localhost", is_root=False),
            retry_delay_seconds=0.0,
            sleep=lambda _: None,
        )
        run.side_effect = [
            subprocess.CalledProcessError(1, ["upsc"], stderr="Error: Data stale"),
            subprocess.CalledProcessError(1, ["sudo"], stderr="sudo: a password is required"),
            subprocess.CompletedProcess(["systemctl"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["upsc"], 0, stdout=NUT_OUTPUT, stderr=""),
        ]

        reading = NutSource("ups@localhost", 3, stale_recovery=recovery).read()

        self.assertEqual(reading.sample.telemetry.output_voltage, 230.0)
        self.assertEqual(
            run.call_args_list[2].args[0],
            ["systemctl", "--no-ask-password", "restart", "nut-driver@ups.service", "nut-server.service"],
        )

    @patch("backend.ups_monitor.infrastructure.nut.subprocess.run")
    def test_stale_recovery_skips_concurrent_duplicate_restarts(self, run):
        started = threading.Event()
        release = threading.Event()

        def slow_restart(*_args, **_kwargs):
            started.set()
            release.wait(timeout=2)
            return subprocess.CompletedProcess(["sudo"], 0, stdout="", stderr="")

        run.side_effect = slow_restart
        recovery = StaleDataRecovery(
            (("sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"),),
            retry_delay_seconds=0.0,
            sleep=lambda _: None,
        )

        results: list[bool] = []
        worker = threading.Thread(target=lambda: results.append(recovery.recover("Error: Data stale")))
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(recovery.recover("Error: Data stale"))
        release.set()
        worker.join(timeout=2)

        self.assertEqual(results, [True])
        self.assertEqual(run.call_count, 1)

    def test_settings_and_create_app_wire_stale_recovery(self):
        env = {
            "UPS_NAME": "ups@localhost",
            "UPS_STALE_RECOVERY_ENABLED": "true",
            "UPS_STALE_RECOVERY_COMMAND": "sudo -n systemctl restart nut-driver@ups.service nut-server.service",
            "UPS_STALE_RECOVERY_COOLDOWN_SECONDS": "45",
            "UPS_STALE_RECOVERY_TIMEOUT_SECONDS": "12",
            "UPS_STALE_RECOVERY_RETRY_DELAY_SECONDS": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings.from_env()
        self.assertTrue(settings.stale_recovery_enabled)
        self.assertEqual(
            settings.stale_recovery_command,
            ("sudo", "-n", "systemctl", "restart", "nut-driver@ups.service", "nut-server.service"),
        )
        self.assertEqual(settings.stale_recovery_cooldown_seconds, 45.0)
        self.assertEqual(settings.stale_recovery_timeout_seconds, 12.0)
        self.assertEqual(settings.stale_recovery_retry_delay_seconds, 2.0)

        with tempfile.TemporaryDirectory() as directory:
            app_enabled = create_app(Settings(ups_name="ups@localhost", db_path=Path(directory) / "a.db"))
            self.assertIsNotNone(app_enabled.state.monitor.source.stale_recovery)

            app_disabled = create_app(
                Settings(
                    ups_name="ups@localhost",
                    db_path=Path(directory) / "b.db",
                    stale_recovery_enabled=False,
                )
            )
            self.assertIsNone(app_disabled.state.monitor.source.stale_recovery)

            app_remote = create_app(Settings(ups_name="rack@192.168.1.20", db_path=Path(directory) / "c.db"))
            self.assertIsNone(app_remote.state.monitor.source.stale_recovery)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "nested" / "telemetry.sqlite3"
        self.store = SQLiteSampleStore(self.path, "rack@nut")
        self.store.initialize()
        self.source = Mock()
        self.monitor = Monitor(self.source, self.store, timedelta(hours=10), 10, lambda: NOW)

    def save(self, when, voltage=230):
        self.store.save(Sample(when, Telemetry(status="OL", input_voltage=voltage)))

    def test_persists_across_initialization_and_preserves_nulls_and_duplicates(self):
        self.source.read.return_value = parse_reading("ups.status: OL\nups.load: 0", NOW)
        self.monitor.capture()
        self.save(NOW, 250)
        reopened = SQLiteSampleStore(self.path, "rack@nut")
        reopened.initialize()
        sample, = reopened.query(NOW, NOW, 10).samples
        self.assertEqual(sample, Sample(NOW, Telemetry(status="OL", load_percent=0)))

    def test_range_includes_both_boundaries_and_ignores_other_devices(self):
        other = SQLiteSampleStore(self.path, "other@nut")
        other.save(Sample(NOW, Telemetry(status="OB")))
        for offset in (20, -10, 0, 10, 30):
            self.save(NOW + timedelta(seconds=offset), offset + 230)
        start = NOW
        end = NOW + timedelta(seconds=20)
        samples = self.monitor.history(start, end, 10).history.samples
        self.assertEqual([s.telemetry.input_voltage for s in samples], [230, 240, 250])

    def test_downsampling_is_bounded_and_preserves_real_samples_and_endpoints(self):
        for offset in range(40):
            self.save(NOW - timedelta(seconds=offset), 230 + offset)
        history = self.monitor.history(NOW - timedelta(minutes=1), NOW, 7).history
        self.assertEqual(len(history.samples), 7)
        self.assertGreater(history.bucket_seconds, 0)
        self.assertEqual(history.samples[0].telemetry.input_voltage, 269)
        self.assertEqual(history.samples[-1].telemetry.input_voltage, 230)
        for sample in history.samples:
            self.assertEqual(sample.telemetry.input_voltage, 230 + (NOW - sample.timestamp).seconds)
        self.assertEqual(history.samples, sorted(history.samples, key=lambda sample: sample.timestamp))

    def test_retention_hides_and_then_deletes_old_rows_even_without_new_samples(self):
        cutoff = NOW - timedelta(hours=10)
        self.save(cutoff - timedelta(microseconds=1))
        self.save(cutoff)
        self.save(NOW)

        result = self.monitor.history(NOW - timedelta(hours=11), NOW, 10)
        self.assertEqual([s.timestamp for s in result.history.samples], [cutoff, NOW])
        self.monitor.purge()
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ups_samples").fetchone()[0], 2)

    def test_current_rejects_unusable_data_before_saving(self):
        for response in ("battery.voltage: bogus", "ups.status: WAIT\ninput.voltage: 230"):
            self.source.read.return_value = parse_reading(response, NOW)
            with self.assertRaises(SourceUnavailable):
                self.monitor.capture()
        self.assertEqual(self.store.query(NOW, NOW, 10).samples, [])

    def test_history_defaults_and_validation(self):
        self.assertEqual(self.monitor.history(None, None, 10).start, NOW - timedelta(hours=1))
        self.assertEqual(
            self.monitor.history(None, None, 10, window_minutes=15).start,
            NOW - timedelta(minutes=15),
        )
        for start, end in ((NOW, NOW), (NOW.replace(tzinfo=None), NOW)):
            with self.assertRaises(InvalidHistoryRange):
                self.monitor.history(start, end, 10)


class SamplerTests(unittest.IsolatedAsyncioTestCase):
    async def test_continues_after_nut_and_storage_errors_and_stops_cleanly(self):
        source = Mock()
        source.read.side_effect = [SourceUnavailable("offline"), parse_reading(NUT_OUTPUT, NOW),
                                   parse_reading(NUT_OUTPUT, NOW)]
        store = Mock()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def save(_sample):
            if store.save.call_count == 1:
                raise sqlite3.OperationalError("busy")
            loop.call_soon_threadsafe(stop.set)

        store.save.side_effect = save
        monitor = Monitor(source, store, timedelta(hours=10), 0.01, lambda: NOW)

        with self.assertLogs("backend.ups_monitor.application.sampler", "WARNING") as logs:
            await asyncio.wait_for(sample_periodically(monitor, stop, 60), timeout=2)
        self.assertEqual(source.read.call_count, 3)
        self.assertEqual(store.save.call_count, 2)
        store.delete_before.assert_called_once_with(NOW - timedelta(hours=10))
        self.assertIn("offline", logs.output[0])
        self.assertIn("OperationalError", logs.output[1])


class ApiTests(unittest.TestCase):
    def test_contracts_lifespan_and_history_independent_of_nut(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(ups_name="test@nut", db_path=Path(directory) / "history.db")
            reading = parse_reading(NUT_OUTPUT, datetime.now(timezone.utc))
            source = Mock()
            source.read.return_value = reading
            with TestClient(create_app(settings, source=source)) as client:
                self.assertTrue(settings.db_path.exists())
                self.assertEqual(client.get("/saludo").json(), {"chao": "mundo"})
                self.assertEqual(client.get("/ups/raw").json(), reading.raw)
                legacy = client.get("/ups/summary").json()
                self.assertEqual(set(legacy), {
                    "status", "input_voltage", "output_voltage", "output_frequency",
                    "load_percent", "battery_voltage", "battery_charge", "raw",
                })
                current = client.get("/api/ups/current")
                self.assertEqual(current.headers["Cache-Control"], "no-store")
                self.assertEqual(current.json()["ups_name"], settings.ups_name)
                self.assertEqual(current.json()["mode"], "line")
                self.assertNotIn("raw", current.json())

                deadline = time.monotonic() + 2
                while not client.get("/api/metrics").json()["samples"]:
                    self.assertLess(time.monotonic(), deadline, "The lifespan sampler did not persist its first sample")
                    time.sleep(0.01)

                source.read.side_effect = SourceUnavailable("Error ejecutando upsc: offline")
                self.assertEqual(client.get("/ups/summary").status_code, 500)
                self.assertEqual(client.get("/ups/raw").status_code, 500)
                self.assertEqual(client.get("/api/ups/current").status_code, 503)
                history = client.get("/api/metrics", params={"window_minutes": 15})
                self.assertEqual(history.status_code, 200)
                sample, = history.json()["samples"]
                self.assertEqual(sample["load_percent"], 0)
                self.assertEqual(sample["output_frequency"], 50.1)

                for params in (
                    {"start": "2026-01-01T08:00:00"},
                    {"start": "2026-01-01T12:00:00Z", "end": "2026-01-01T12:00:00Z"},
                    {"window_minutes": 30, "start": "2026-01-01T08:00:00Z"},
                    {"max_points": 2},
                ):
                    with self.subTest(params=params):
                        self.assertEqual(client.get("/api/metrics", params=params).status_code, 422)


if __name__ == "__main__":
    unittest.main()
