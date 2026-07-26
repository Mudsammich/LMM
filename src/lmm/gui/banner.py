"""The vaporwave title banner: a painted sunset grid with a glowing 'LMM'
wordmark, sitting above the tabs. Pure QPainter - no image assets needed."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme

HEIGHT = 132


class VaporwaveBanner(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        self._paint_sky(painter, rect)
        horizon_y = rect.height() * 0.62
        self._paint_sun(painter, rect, horizon_y)
        self._paint_grid(painter, rect, horizon_y)
        self._paint_horizon_line(painter, rect, horizon_y)
        self._paint_wordmark(painter, rect)

        painter.end()

    def _paint_sky(self, painter: QPainter, rect: QRectF) -> None:
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0.0, QColor("#1b0f3d"))
        gradient.setColorAt(0.45, QColor("#5a2578"))
        gradient.setColorAt(0.75, QColor("#c9457f"))
        gradient.setColorAt(1.0, QColor(theme.SUNSET_ORANGE))
        painter.fillRect(rect, gradient)

    def _paint_sun(self, painter: QPainter, rect: QRectF, horizon_y: float) -> None:
        radius = rect.height() * 0.34
        center = QPointF(rect.width() * 0.82, horizon_y - radius * 0.15)

        sun_gradient = QLinearGradient(0, center.y() - radius, 0, center.y() + radius)
        sun_gradient.setColorAt(0.0, QColor(theme.SUNSET_GOLD))
        sun_gradient.setColorAt(1.0, QColor(theme.NEON_PINK))

        painter.save()
        clip_path = QPainterPath()
        clip_path.addEllipse(center, radius, radius)
        painter.setClipPath(clip_path)
        painter.fillRect(rect, sun_gradient)

        # Retro "sliced" sun bands.
        band_color = self._paint_sky_color_at(horizon_y, rect.height())
        num_bands = 5
        band_height = radius * 0.14
        for i in range(num_bands):
            y = center.y() - i * (band_height * 1.7)
            painter.fillRect(QRectF(center.x() - radius, y, radius * 2, band_height), band_color)
        painter.restore()

    def _paint_sky_color_at(self, y: float, total_height: float) -> QColor:
        t = max(0.0, min(1.0, y / total_height))
        stops = [
            (0.0, QColor("#1b0f3d")),
            (0.45, QColor("#5a2578")),
            (0.75, QColor("#c9457f")),
            (1.0, QColor(theme.SUNSET_ORANGE)),
        ]
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                return QColor(
                    int(c0.red() + (c1.red() - c0.red()) * f),
                    int(c0.green() + (c1.green() - c0.green()) * f),
                    int(c0.blue() + (c1.blue() - c0.blue()) * f),
                )
        return stops[-1][1]

    def _paint_horizon_line(self, painter: QPainter, rect: QRectF, horizon_y: float) -> None:
        pen = QPen(QColor(theme.NEON_CYAN))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, horizon_y), QPointF(rect.width(), horizon_y))

    def _paint_grid(self, painter: QPainter, rect: QRectF, horizon_y: float) -> None:
        vanishing_point = QPointF(rect.width() / 2, horizon_y)
        floor_top = horizon_y
        floor_bottom = rect.height()

        pen = QPen(QColor(theme.NEON_PINK))
        pen.setWidth(1)
        painter.setPen(pen)

        # Radiating lines from the vanishing point down to the bottom edge.
        num_lines = 14
        spread = rect.width() * 1.4
        for i in range(num_lines + 1):
            x = -spread / 2 + spread * (i / num_lines) + vanishing_point.x()
            painter.drawLine(vanishing_point, QPointF(x, floor_bottom))

        # Horizontal lines, spaced closer together near the horizon.
        pen.setColor(QColor(theme.NEON_CYAN_DIM))
        painter.setPen(pen)
        num_rows = 6
        for row in range(1, num_rows + 1):
            frac = (row / num_rows) ** 1.8
            y = floor_top + frac * (floor_bottom - floor_top)
            painter.drawLine(QPointF(0, y), QPointF(rect.width(), y))

    def _paint_wordmark(self, painter: QPainter, rect: QRectF) -> None:
        title_font = QFont(theme.FONT_FAMILY.split(",")[0].strip('"'))
        title_font.setPointSize(34)
        title_font.setBold(True)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 6)

        path = QPainterPath()
        path.addText(0, 0, title_font, "LMM")
        bounds = path.boundingRect()
        x = 28 - bounds.left()
        y = rect.height() / 2 - bounds.center().y() - 4
        path.translate(x, y)

        # Neon glow: several soft, wide, low-alpha strokes stacked under a
        # crisp core stroke+fill.
        for width, alpha in ((14, 25), (9, 45), (5, 80)):
            glow_pen = QPen(QColor(theme.NEON_PINK))
            glow_pen.setWidth(width)
            glow_pen.setJoinStyle(Qt.RoundJoin)
            glow_color = QColor(theme.NEON_PINK)
            glow_color.setAlpha(alpha)
            glow_pen.setColor(glow_color)
            painter.setPen(glow_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        core_pen = QPen(QColor(theme.NEON_CYAN))
        core_pen.setWidth(2)
        painter.setPen(core_pen)
        painter.setBrush(QColor(theme.TEXT_MAIN))
        painter.drawPath(path)

        subtitle_font = QFont(theme.MONO_FONT_FAMILY.split(",")[0].strip('"'))
        subtitle_font.setPointSize(11)
        subtitle_font.setBold(True)
        subtitle_font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        painter.setFont(subtitle_font)
        painter.setPen(QColor(theme.TEXT_MAIN))
        painter.drawText(
            QRectF(x + bounds.left(), y + bounds.bottom() + 8, rect.width(), 24),
            Qt.AlignLeft | Qt.AlignTop,
            "L I N U X   M O D   M A N A G E R",
        )
