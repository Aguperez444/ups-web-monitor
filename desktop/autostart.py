from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_ID = "ups-monitor"


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".config"


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "share"


def autostart_desktop_path() -> Path:
    return _xdg_config_home() / "autostart" / f"{APP_ID}.desktop"


def user_icon_path() -> Path:
    return _xdg_data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def _quote_desktop_arg(arg: str) -> str:
    # FreeDesktop Desktop Entry Spec Exec quoting
    if not arg or any(ch in arg for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        escaped = (
            arg.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
        return f'"{escaped}"'
    return arg


def resolve_autostart_exec() -> str:
    override = os.environ.get("UPS_AUTOSTART_EXEC", "").strip()
    if override:
        return override

    appimage = os.environ.get("APPIMAGE", "").strip()
    if appimage:
        return _quote_desktop_arg(str(Path(appimage).resolve()))

    # Fallback when running directly from a source checkout
    repo_root = Path(__file__).resolve().parents[1]
    return " ".join(
        [
            _quote_desktop_arg(sys.executable),
            "-m",
            "desktop.tray_app",
        ]
    ) + f" # cwd={repo_root}"


def _install_user_icon() -> str:
    asset_svg = Path(__file__).resolve().parent / "assets" / "ups-monitor.svg"
    if not asset_svg.is_file():
        return "battery"
    dest = user_icon_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset_svg, dest)
        return str(dest)
    except OSError:
        return "battery"


def is_autostart_enabled() -> bool:
    return autostart_desktop_path().is_file()


def enable_autostart() -> Path:
    path = autostart_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    icon_value = _install_user_icon()

    appimage = os.environ.get("APPIMAGE", "").strip()
    exec_line = resolve_autostart_exec().split(" # cwd=", 1)[0]
    path_line = ""
    if not appimage:
        repo_root = Path(__file__).resolve().parents[1]
        path_line = f"Path={repo_root}\n"

    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=UPS Monitor\n"
        "Comment=Monitor local de UPS (NUT) con historial persistente\n"
        f"Exec={exec_line}\n"
        f"{path_line}"
        f"Icon={icon_value}\n"
        "Terminal=false\n"
        "Categories=System;Monitor;\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def disable_autostart() -> None:
    path = autostart_desktop_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def set_autostart(enabled: bool) -> bool:
    if enabled:
        enable_autostart()
        return True
    disable_autostart()
    return False
