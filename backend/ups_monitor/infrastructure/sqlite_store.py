import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..domain.ports import History
from ..domain.telemetry import Sample, Telemetry


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MICROSECONDS_PER_SECOND = 1_000_000
COLUMNS = """
    timestamp_us, status, input_voltage, output_voltage, output_frequency,
    load_percent, battery_voltage, battery_charge
"""


def _to_us(value: datetime) -> int:
    elapsed = value - EPOCH
    return (elapsed.days * 86400 + elapsed.seconds) * MICROSECONDS_PER_SECOND + elapsed.microseconds


class SQLiteSampleStore:
    def __init__(self, path: Path, ups_name: str) -> None:
        self.path = path
        self.ups_name = ups_name

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS ups_samples (
                    ups_name TEXT NOT NULL,
                    timestamp_us INTEGER NOT NULL,
                    status TEXT,
                    input_voltage REAL,
                    output_voltage REAL,
                    output_frequency REAL,
                    load_percent REAL,
                    battery_voltage REAL,
                    battery_charge REAL,
                    PRIMARY KEY (ups_name, timestamp_us)
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS ups_samples_timestamp_idx
                ON ups_samples (timestamp_us);
            """)

    def save(self, sample: Sample) -> None:
        values = sample.telemetry
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO ups_samples (ups_name, {COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ups_name, timestamp_us) DO NOTHING
                """,
                (
                    self.ups_name, _to_us(sample.timestamp), values.status, values.input_voltage,
                    values.output_voltage, values.output_frequency, values.load_percent,
                    values.battery_voltage, values.battery_charge,
                ),
            )

    def delete_before(self, cutoff: datetime) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM ups_samples WHERE timestamp_us < ?", (_to_us(cutoff),))

    def checkpoint(self) -> None:
        if not self.path.exists():
            return
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def query(self, start: datetime, end: datetime, max_points: int) -> History:
        bounds = (self.ups_name, _to_us(start), _to_us(end))
        bucket_us = None
        with closing(self._connect()) as connection, connection:
            # Keep bounds discovery and selection in the same read snapshot.
            connection.execute("BEGIN")
            count, first, last = connection.execute(
                """
                SELECT COUNT(*), MIN(timestamp_us), MAX(timestamp_us)
                FROM ups_samples WHERE ups_name = ? AND timestamp_us BETWEEN ? AND ?
                """,
                bounds,
            ).fetchone()

            if count <= max_points:
                rows = connection.execute(
                    f"""
                    SELECT {COLUMNS} FROM ups_samples
                    WHERE ups_name = ? AND timestamp_us BETWEEN ? AND ? ORDER BY timestamp_us
                    """,
                    bounds,
                ).fetchall()
            else:
                # The first and last samples remain intact. Interior buckets select real rows.
                interior_slots = max_points - 2
                bucket_us = (last - first + interior_slots - 1) // interior_slots
                rows = connection.execute(
                    f"""
                    WITH selected(timestamp_us) AS (
                        SELECT MIN(timestamp_us)
                        FROM ups_samples
                        WHERE ups_name = ? AND timestamp_us > ? AND timestamp_us < ?
                        GROUP BY (timestamp_us - ?) / ?
                        UNION ALL SELECT ?
                        UNION ALL SELECT ?
                    )
                    SELECT {COLUMNS} FROM ups_samples
                    JOIN selected USING (timestamp_us)
                    WHERE ups_name = ? ORDER BY timestamp_us
                    """,
                    (self.ups_name, first, last, first + 1, bucket_us, first, last, self.ups_name),
                ).fetchall()

        samples = []
        for row in rows:
            values = dict(row)
            timestamp = EPOCH + timedelta(microseconds=values.pop("timestamp_us"))
            samples.append(Sample(timestamp, Telemetry(**values)))
        return History(samples, bucket_us / MICROSECONDS_PER_SECOND if bucket_us else None)
