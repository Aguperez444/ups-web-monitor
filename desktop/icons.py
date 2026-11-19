from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

STATE_COLORS: dict[str, tuple[str, str]] = {
    # (accent_color, fill_color)
    "line": ("#47e5b5", "#1c5746"),
    "battery": ("#f59e0b", "#66400a"),
    "bypass": ("#eeb071", "#5c4124"),
    "off": ("#f87171", "#5c2323"),
    "error": ("#f87171", "#5c2323"),
    "unknown": ("#94a3b8", "#334155"),
    "starting": ("#94a3b8", "#334155"),
}


def _render_pixmap(size: int, state: str, charge: float | None) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    accent_hex, fill_hex = STATE_COLORS.get(state, STATE_COLORS["unknown"])
    accent = QColor(accent_hex)
    fill = QColor(fill_hex)
    body_bg = QColor("#0e1623")
    body_bg.setAlpha(235)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    s = float(size)
    stroke = max(1.6, s * 0.075)

    # Draw a crisp vertical battery with plug-like top cap & lightning bolt.
    cap_w = s * 0.30
    cap_h = s * 0.10
    cap_x = (s - cap_w) / 2.0
    cap_y = s * 0.06

    body_w = s * 0.62
    body_h = s * 0.74
    body_x = (s - body_w) / 2.0
    body_y = cap_y + cap_h + s * 0.015
    radius = s * 0.11

    # Cap
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(accent)
    painter.drawRoundedRect(QRectF(cap_x, cap_y, cap_w, cap_h + s * 0.02), s * 0.035, s * 0.035)

    # Battery body background
    body_rect = QRectF(body_x, body_y, body_w, body_h)
    painter.setBrush(body_bg)
    painter.setPen(QPen(accent, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawRoundedRect(body_rect, radius, radius)

    # Optional battery charge level fill inside the body
    inner_margin = stroke * 1.15
    inner_w = body_w - inner_margin * 2
    inner_h = body_h - inner_margin * 2
    if inner_w > 2 and inner_h > 2:
        ratio = 1.0 if charge is None else max(0.08, min(1.0, charge / 100.0))
        if state in ("error", "off", "unknown", "starting") and charge is None:
            ratio = 0.0
        if ratio > 0:
            fill_h = inner_h * ratio
            fill_rect = QRectF(
                body_x + inner_margin,
                body_y + inner_margin + (inner_h - fill_h),
                inner_w,
                fill_h,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(fill_rect, s * 0.05, s * 0.05)

    # Centered lightning bolt (symbolizing power / UPS)
    bolt = QPainterPath()
    cx = s * 0.50
    top_y = body_y + body_h * 0.14
    bot_y = body_y + body_h * 0.86
    mid_y = body_y + body_h * 0.50
    bolt_w = body_w * 0.28

    bolt.moveTo(QPointF(cx + bolt_w * 0.25, top_y))
    bolt.lineTo(QPointF(cx - bolt_w * 0.95, mid_y + body_h * 0.03))
    bolt.lineTo(QPointF(cx - bolt_w * 0.05, mid_y + body_h * 0.03))
    bolt.lineTo(QPointF(cx - bolt_w * 0.30, bot_y))
    bolt.lineTo(QPointF(cx + bolt_w * 0.95, mid_y - body_h * 0.04))
    bolt.lineTo(QPointF(cx + bolt_w * 0.05, mid_y - body_h * 0.04))
    bolt.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(accent)
    painter.drawPath(bolt)

    painter.end()
    return pixmap


def build_tray_icon(state: str = "starting", charge: float | None = None) -> QIcon:
    """Create a sharp multi-resolution tray icon for the given UPS state."""
    icon = QIcon()
    for size in (22, 32, 48, 64):
        icon.addPixmap(_render_pixmap(size, state, charge))
    return icon
