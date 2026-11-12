import asyncio
import sqlite3
import subprocess
import tempfile
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
from backend.ups_monitor.infrastructure.nut import NutSource, parse_reading
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
