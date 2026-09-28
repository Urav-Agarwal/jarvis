"""
Futuristic HUD widgets: audio-style waveform visualizer and circular
ring gauges for the system telemetry. Pure Qt painting, no deps.
"""

import math
import random
import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


class Waveform(QWidget):
    """
    Living waveform ribbon: symmetric vertical bars driven by layered
    sine motion + gentle randomness. Amplitude follows the given
    activity level (0..1) — calm when idle, lively when thinking.
    """

    def __init__(self, bars: int = 28):
        super().__init__()

        self.setFixedHeight(56)
        self.bars = bars

        self.level = 0.25
        self._target_level = 0.25

        self._offsets = [
            random.uniform(0, math.tau)
            for _ in range(bars)
        ]

        self._speeds = [
            random.uniform(1.6, 3.2)
            for _ in range(bars)
        ]

        self._color = QColor("#22d3ee")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    def set_color(self, color_hex: str):
        self._color = QColor(color_hex)

    def set_level(self, level: float):
        self._target_level = max(0.08, min(1.0, level))

    def _tick(self):
        self.level += (self._target_level - self.level) * 0.15
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        mid = height / 2

        gap = 3
        bar_width = (width - gap * (self.bars - 1)) / self.bars

        t = time.time()

        for index in range(self.bars):
            # Layered sine motion with per-bar personality.
            wave = (
                math.sin(t * self._speeds[index] + self._offsets[index]) * 0.45
                + math.sin(t * 0.8 + index * 0.55) * 0.35
                + math.sin(t * 5.1 + index * 1.7) * 0.2
            )

            envelope = 0.35 + 0.65 * math.sin(
                math.pi * (index + 0.5) / self.bars
            )

            amplitude = max(
                2.0,
                abs(wave) * self.level * envelope * (height / 2 - 3),
            )

            x = index * (bar_width + gap)

            color = QColor(self._color)
            color.setAlpha(120 + int(110 * (amplitude / (height / 2))))

            painter.setPen(Qt.NoPen)
            painter.setBrush(color)

            painter.drawRoundedRect(
                x,
                mid - amplitude,
                bar_width,
                amplitude * 2,
                bar_width / 2,
                bar_width / 2,
            )

        painter.end()


class RingGauge(QWidget):
    """
    Circular progress ring with a centered value label. Clean,
    futuristic, state-colored.
    """

    def __init__(self, label: str):
        super().__init__()

        self.label = label
        self.percent = 0
        self._display = 0.0

        self._color = QColor("#22d3ee")

        self.setMinimumSize(74, 74)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(40)

    def set_color(self, color_hex: str):
        self._color = QColor(color_hex)

    def set_value(self, percent: int, text: str = ""):
        self.percent = max(0, min(100, int(percent)))
        self._text = text or f"{self.percent}%"

    def _tick(self):
        self._display += (self.percent - self._display) * 0.12
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        side = min(self.width(), self.height())

        center = QPointF(self.width() / 2, self.height() / 2)
        radius = side / 2 - 6

        # Background track.
        track = QColor("#16273a")

        painter.setPen(QPen(track, 5, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)

        painter.drawEllipse(center, radius, radius)

        # Value arc (sweep from top, clockwise).
        span = int(-360 * self._display / 100 * 16)

        painter.setPen(
            QPen(self._color, 5, Qt.SolidLine, Qt.RoundCap)
        )

        from PySide6.QtCore import QRectF

        painter.drawArc(
            QRectF(
                center.x() - radius,
                center.y() - radius,
                radius * 2,
                radius * 2,
            ),
            90 * 16,
            span,
        )

        # Value text.
        painter.setPen(QColor("#e6eefb"))
        font = painter.font()
        font.setPointSizeF(9.5)
        font.setBold(True)
        painter.setFont(font)

        painter.drawText(
            QRectF(
                center.x() - radius,
                center.y() - 14,
                radius * 2,
                18,
            ),
            Qt.AlignCenter,
            self._text,
        )

        # Label text.
        painter.setPen(QColor("#5b7290"))
        small = painter.font()
        small.setPointSizeF(6.5)
        small.setBold(False)
        painter.setFont(small)

        painter.drawText(
            QRectF(
                center.x() - radius,
                center.y() + 2,
                radius * 2,
                14,
            ),
            Qt.AlignCenter,
            self.label,
        )

        painter.end()
