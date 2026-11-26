from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
import uvicorn

from backend.ups_monitor.domain.ports import SourceUnavailable
from backend.ups_monitor.domain.telemetry import Mode
from backend.ups_monitor.infrastructure.settings import (
    DEFAULT_RETENTION_HOURS,
    Settings,
    default_user_db_path,
)
from backend.ups_monitor.presentation.app import create_app
from desktop.autostart import is_autostart_enabled, set_autostart
from desktop.icons import build_tray_icon

logger = logging.getLogger("ups_monitor.desktop")

IPC_SERVER_NAME = "ups-monitor-tray-v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5601

MODE_LABELS: dict[Mode, str] = {
    Mode.LINE: "En línea",
    Mode.BATTERY: "En batería",
    Mode.BYPASS: "Bypass",
    Mode.OFF: "Apagado",
    Mode.UNKNOWN: "Estado desconocido",
}

CONFIG_TEMPLATE = """# Configuración local de UPS Monitor (opcional)
# Descomentá y ajustá los valores que necesites, luego reiniciá la aplicación.

# Identificador del UPS en NUT (por defecto: ups@localhost)
# UPS_NAME=ups@localhost

# Puerto local del dashboard web (por defecto: 5601)
# UPS_PORT=5601

# Ruta de la base de datos SQLite persistente
# UPS_DB_PATH=~/.local/share/ups-monitor/ups.sqlite3

# Intervalo de muestreo en segundos (por defecto: 10)
# UPS_SAMPLE_INTERVAL_SECONDS=10

# Retención de historial en horas (por defecto: 720 = 30 días)
# UPS_RETENTION_HOURS=720

# Reinicio automático de NUT al detectar "Data stale" en upsc (por defecto: true)
# UPS_STALE_RECOVERY_ENABLED=true
# Comando personalizado de recuperación (opcional; por defecto reinicia nut-driver@<ups>.service y nut-server.service)
# UPS_STALE_RECOVERY_COMMAND=sudo -n systemctl restart nut-driver@ups.service nut-server.service
# Tiempo mínimo de espera entre reinicios automáticos en segundos (por defecto: 60)
# UPS_STALE_RECOVERY_COOLDOWN_SECONDS=60
"""


def _xdg_config_dir() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(raw).expanduser() if raw else Path.home() / ".config"
    return base / "ups-monitor"


def _xdg_data_dir() -> Path:
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(raw).expanduser() if raw else Path.home() / ".local" / "share"
    return base / "ups-monitor"


def _config_file_path() -> Path:
    return _xdg_config_dir() / "config.env"


def _configure_logging(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "ups-monitor.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if sys.stderr and sys.stderr.isatty():
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    return log_path


def _clean_host_env() -> dict[str, str]:
    """Restore original host environment so xdg-open/browser doesn't inherit AppImage libs."""
    env = dict(os.environ)
    mappings = {
        "UPS_ORIG_LD_LIBRARY_PATH": "LD_LIBRARY_PATH",
        "UPS_ORIG_QT_PLUGIN_PATH": "QT_PLUGIN_PATH",
        "UPS_ORIG_QT_QPA_PLATFORM_PLUGIN_PATH": "QT_QPA_PLATFORM_PLUGIN_PATH",
        "UPS_ORIG_PYTHONHOME": "PYTHONHOME",
        "UPS_ORIG_PYTHONPATH": "PYTHONPATH",
    }
    for orig_key, target_key in mappings.items():
        if orig_key in env:
            value = env.pop(orig_key)
            if value:
                env[target_key] = value
            else:
                env.pop(target_key, None)
        elif os.environ.get("APPIMAGE") or os.environ.get("UPS_RUNNING_IN_APPIMAGE"):
            env.pop(target_key, None)
    return env


def open_external_target(target: str) -> None:
    """Open a URL or local path using the desktop's default handler."""
    env = _clean_host_env()
    try:
        subprocess.Popen(
            ["xdg-open", target],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    except OSError:
        logger.warning("xdg-open no disponible; usando webbrowser para %s", target)
    webbrowser.open(target)


def _resolve_frontend_dist() -> Path | None:
    env_dist = os.environ.get("UPS_FRONTEND_DIST", "").strip()
    if env_dist:
        candidate = Path(env_dist).expanduser()
        if (candidate / "index.html").is_file():
            return candidate
    repo_candidate = Path(__file__).resolve().parents[1] / "frontend" / "out"
    if (repo_candidate / "index.html").is_file():
        return repo_candidate
    return None


def _build_settings() -> tuple[Settings, str, int]:
    config_file = _config_file_path()
    if config_file.is_file():
        load_dotenv(config_file, override=False)

    # Default to persistent XDG user data dir unless explicitly overridden.
    os.environ.setdefault("UPS_DB_PATH", str(default_user_db_path()))
    os.environ.setdefault("UPS_RETENTION_HOURS", str(DEFAULT_RETENTION_HOURS))

    frontend_dist = _resolve_frontend_dist()
    if frontend_dist is not None:
        os.environ.setdefault("UPS_FRONTEND_DIST", str(frontend_dist))

    settings = Settings.from_env()
    host = os.environ.get("UPS_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = int(os.environ.get("UPS_PORT", str(DEFAULT_PORT)))
    return settings, host, port


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    check_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with socket.create_connection((check_host, port), timeout=timeout):
            return True
    except OSError:
        return False


class EmbeddedServer:
    """Runs FastAPI/Uvicorn in a dedicated background thread with clean shutdown."""

    def __init__(self, app: Any, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
        )
        self._server = uvicorn.Server(self._config)
        # Qt owns POSIX signal handling in the main thread.
        self._server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self._thread = threading.Thread(target=self._run, name="ups-monitor-server", daemon=True)
        self.error: BaseException | None = None

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # pragma: no cover - defensive runtime guard
            self.error = exc
            logger.exception("El servidor embebido se detuvo por un error.")

    def start(self, wait_timeout: float = 5.0) -> bool:
        self._thread.start()
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            if self._server.started:
                return True
            if self.error is not None or not self._thread.is_alive():
                return False
            time.sleep(0.05)
        return _is_port_open(self.host, self.port)

    def stop(self, timeout: float = 5.0) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)


class StatusPoller(QObject):
    """Fetches current UPS reading off the UI thread to keep tray responsive."""

    updated = pyqtSignal(dict)

    def __init__(self, monitor: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._busy = False

    def poll_async(self) -> None:
        if self._busy:
            return
        self._busy = True
        thread = threading.Thread(target=self._worker, name="ups-tray-status", daemon=True)
        thread.start()

    def _worker(self) -> None:
        payload: dict[str, Any]
        try:
            reading = self._monitor.current()
            telemetry = reading.sample.telemetry
            payload = {
                "ok": True,
                "mode": telemetry.mode,
                "status": telemetry.status,
                "charge": telemetry.battery_charge,
                "load": telemetry.load_percent,
                "input_voltage": telemetry.input_voltage,
                "output_voltage": telemetry.output_voltage,
            }
        except SourceUnavailable as error:
            payload = {"ok": False, "error": str(error)}
        except Exception as error:
            payload = {"ok": False, "error": f"Error leyendo UPS: {error}"}
        finally:
            self._busy = False
        self.updated.emit(payload)


def _notify_running_instance(message: bytes = b"OPEN") -> bool:
    socket_client = QLocalSocket()
    socket_client.connectToServer(IPC_SERVER_NAME)
    if not socket_client.waitForConnected(400):
        return False
    socket_client.write(message)
    socket_client.flush()
    socket_client.waitForBytesWritten(400)
    socket_client.disconnectFromServer()
    return True


def _format_status_lines(payload: dict[str, Any]) -> tuple[str, str, str, str, float | None]:
    if not payload.get("ok"):
        error = str(payload.get("error") or "Sin conexión con NUT")
        short_error = error if len(error) <= 58 else error[:55] + "…"
        return (
            "error",
            "UPS Monitor — Sin lectura de NUT",
            "Estado: Sin conexión con NUT",
            short_error,
            None,
        )

    mode: Mode = payload["mode"]
    charge: float | None = payload.get("charge")
    load: float | None = payload.get("load")
    vin: float | None = payload.get("input_voltage")
    vout: float | None = payload.get("output_voltage")

    mode_text = MODE_LABELS.get(mode, "Desconocido")
    parts = [mode_text]
    if charge is not None:
        parts.append(f"Batería {charge:.0f}%")
    if load is not None:
        parts.append(f"Carga {load:.0f}%")

    headline = " · ".join(parts)
    tooltip = f"UPS Monitor — {headline}\nClick para abrir el panel web"

    volt_parts: list[str] = []
    if vin is not None:
        volt_parts.append(f"Entrada {vin:.0f} V")
    if vout is not None:
        volt_parts.append(f"Salida {vout:.0f} V")
    detail = " · ".join(volt_parts) if volt_parts else "Lectura activa"

    return mode.value, tooltip, f"Estado: {headline}", detail, charge


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UPS Monitor (servidor local + ícono en bandeja)")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Abrir el panel web en el navegador inmediatamente al iniciar.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Iniciar el servidor embebido, verificar respuestas locales y salir (sin bandeja).",
    )
    return parser.parse_args(argv)


def _run_smoke_test(settings: Settings, host: str, port: int) -> int:
    import urllib.request

    app = create_app(settings)
    server = EmbeddedServer(app, host, port)
    if not server.start(wait_timeout=8.0):
        print("ERROR: No se pudo iniciar el servidor embebido.", file=sys.stderr)
        return 1
    try:
        base_url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
        with urllib.request.urlopen(f"{base_url}/api/metrics?window_minutes=15", timeout=5) as resp:
            assert resp.status == 200, f"Unexpected /api/metrics status: {resp.status}"
        if settings.frontend_dist and (settings.frontend_dist / "index.html").is_file():
            with urllib.request.urlopen(f"{base_url}/", timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                assert resp.status == 200, f"Unexpected / status: {resp.status}"
                assert "UPS Monitor" in body, "Dashboard HTML missing expected title"
        assert settings.db_path.is_file(), f"SQLite DB was not created at {settings.db_path}"
        print(f"SMOKE_TEST_OK url={base_url} db={settings.db_path}")
        return 0
    finally:
        server.stop()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    settings, host, port = _build_settings()
    data_dir = settings.db_path.parent
    _configure_logging(data_dir)

    if args.smoke_test:
        return _run_smoke_test(settings, host, port)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("UPS Monitor")
    qt_app.setApplicationDisplayName("UPS Monitor")
    qt_app.setDesktopFileName("ups-monitor")
    qt_app.setQuitOnLastWindowClosed(False)

    # Single-instance check: if already running, tell it to open the dashboard and exit.
    if _notify_running_instance(b"OPEN"):
        logger.info("Ya existe una instancia activa de UPS Monitor; abriendo panel web.")
        return 0

    browser_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    dashboard_url = f"http://{browser_host}:{port}"

    logger.info(
        "Iniciando UPS Monitor en %s (UPS=%s, DB=%s, retención=%sh, frontend=%s)",
        dashboard_url,
        settings.ups_name,
        settings.db_path,
        int(settings.retention.total_seconds() // 3600),
        settings.frontend_dist or "solo-API",
    )

    fastapi_app = create_app(settings)
    server = EmbeddedServer(fastapi_app, host, port)
    started = server.start(wait_timeout=8.0)
    if not started:
        logger.error("No se pudo iniciar el servidor local en %s:%s", host, port)

    # Set up local IPC server so subsequent launches open the browser cleanly.
    QLocalServer.removeServer(IPC_SERVER_NAME)
    ipc_server = QLocalServer()
    ipc_server.listen(IPC_SERVER_NAME)

    def handle_ipc_connection() -> None:
        while ipc_server.hasPendingConnections():
            conn = ipc_server.nextPendingConnection()
            if conn is None:
                continue
            conn.waitForReadyRead(300)
            command = bytes(conn.readAll()).decode("utf-8", errors="ignore").strip()
            conn.disconnectFromServer()
            conn.deleteLater()
            if command in ("", "OPEN"):
                open_external_target(dashboard_url)

    ipc_server.newConnection.connect(handle_ipc_connection)

    tray = QSystemTrayIcon(build_tray_icon("starting"), qt_app)
    tray.setToolTip("UPS Monitor — Iniciando…\nClick para abrir el panel web")

    menu = QMenu()

    open_action = QAction("Abrir panel UPS en el navegador", menu)
    bold_font = open_action.font()
    bold_font.setBold(True)
    open_action.setFont(bold_font)
    open_action.triggered.connect(lambda: open_external_target(dashboard_url))
    menu.addAction(open_action)

    menu.addSeparator()

    status_action = QAction("Estado: Consultando UPS…", menu)
    status_action.setEnabled(False)
    menu.addAction(status_action)

    detail_action = QAction(f"URL: {dashboard_url}", menu)
    detail_action.setEnabled(False)
    menu.addAction(detail_action)

    menu.addSeparator()

    autostart_action = QAction("Iniciar con el sistema", menu)
    autostart_action.setCheckable(True)
    autostart_action.setChecked(is_autostart_enabled())

    def toggle_autostart(checked: bool) -> None:
        try:
            set_autostart(checked)
            logger.info("Inicio automático %s", "activado" if checked else "desactivado")
        except OSError:
            logger.exception("No se pudo actualizar el inicio automático.")
            autostart_action.setChecked(is_autostart_enabled())

    autostart_action.toggled.connect(toggle_autostart)
    menu.addAction(autostart_action)

    open_data_action = QAction("Abrir carpeta de datos (BDD y logs)", menu)
    open_data_action.triggered.connect(lambda: open_external_target(str(data_dir)))
    menu.addAction(open_data_action)

    def open_config_file() -> None:
        cfg = _config_file_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        if not cfg.exists():
            cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        open_external_target(str(cfg))

    open_config_action = QAction("Editar configuración (config.env)", menu)
    open_config_action.triggered.connect(open_config_file)
    menu.addAction(open_config_action)

    menu.addSeparator()

    quit_action = QAction("Salir", menu)
    quit_action.triggered.connect(qt_app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            open_external_target(dashboard_url)

    tray.activated.connect(on_tray_activated)
    tray.show()

    if not started:
        tray.setIcon(build_tray_icon("error"))
        tray.setToolTip(f"UPS Monitor — Error iniciando en puerto {port}")
        tray.showMessage(
            "UPS Monitor",
            f"No se pudo abrir el puerto {port}. Revisá el log en {data_dir / 'ups-monitor.log'}.",
            QSystemTrayIcon.MessageIcon.Warning,
            6000,
        )

    last_mode: dict[str, Mode | None] = {"value": None}

    def on_status_updated(payload: dict[str, Any]) -> None:
        state_key, tooltip, status_line, detail_line, charge = _format_status_lines(payload)
        tray.setIcon(build_tray_icon(state_key, charge))
        tray.setToolTip(tooltip)
        status_action.setText(status_line)
        detail_action.setText(detail_line)

        if payload.get("ok"):
            current_mode: Mode = payload["mode"]
            previous_mode = last_mode["value"]
            if previous_mode is not None and current_mode != previous_mode:
                if current_mode == Mode.BATTERY:
                    charge_msg = f" (batería al {charge:.0f}%)" if charge is not None else ""
                    tray.showMessage(
                        "UPS en batería",
                        f"Se detectó corte de energía eléctrica{charge_msg}.",
                        QSystemTrayIcon.MessageIcon.Warning,
                        8000,
                    )
                elif previous_mode == Mode.BATTERY and current_mode == Mode.LINE:
                    tray.showMessage(
                        "Energía restablecida",
                        "El UPS volvió a alimentación de red eléctrica.",
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )
            last_mode["value"] = current_mode

    poller = StatusPoller(fastapi_app.state.monitor, qt_app)
    poller.updated.connect(on_status_updated)

    poll_timer = QTimer(qt_app)
    poll_timer.setInterval(5000)
    poll_timer.timeout.connect(poller.poll_async)
    poll_timer.start()
    QTimer.singleShot(300, poller.poll_async)

    if args.open and started:
        QTimer.singleShot(250, lambda: open_external_target(dashboard_url))

    # Allow SIGINT/SIGTERM (e.g. logout/reboot/Ctrl+C) to trigger clean Qt & SQLite shutdown.
    def _request_quit(*_args: Any) -> None:
        qt_app.quit()

    signal.signal(signal.SIGINT, _request_quit)
    signal.signal(signal.SIGTERM, _request_quit)
    signal_pump = QTimer(qt_app)
    signal_pump.setInterval(250)
    signal_pump.timeout.connect(lambda: None)
    signal_pump.start()

    def _cleanup() -> None:
        logger.info("Deteniendo UPS Monitor y consolidando SQLite…")
        poll_timer.stop()
        signal_pump.stop()
        tray.hide()
        ipc_server.close()
        QLocalServer.removeServer(IPC_SERVER_NAME)
        server.stop(timeout=5.0)
        logger.info("UPS Monitor detenido correctamente.")

    qt_app.aboutToQuit.connect(_cleanup)
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
