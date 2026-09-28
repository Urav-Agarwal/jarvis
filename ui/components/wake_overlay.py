"""
Siri-like circular wake animation overlay for JARVIS.

A frameless, always-on-top overlay window positioned bottom-center of
the screen. When JARVIS is awake, a layered glowing orb with orbiting
arcs animates; color reflects the agent state (listening green,
thinking amber, executing pink, confirmation orange, error red).
"""

from math import sin, cos, pi

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QBrush,
    QRadialGradient,
    QPainterPath,
)
from PySide6.QtWidgets import QWidget, QApplication


class WakeOverlay(QWidget):
    """Bottom-center circular assistant animation."""

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool,
        )

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Compact size: visible but never intrusive.
        screen = QApplication.primaryScreen().availableGeometry()

        self._diameter = min(150, screen.height() // 6)

        self.setFixedSize(self._diameter, self._diameter)

        # Bottom-center of the screen with a small margin.
        margin = 24

        self.move(
            (screen.width() - self._diameter) // 2,
            screen.height() - self._diameter - margin,
        )

        self.phase = 0.0
        self.visible_phase = 0.0

        self.base_color = QColor("#4ade80")
        self.current_color = QColor("#4ade80")

        self._active = False
        self._target_opacity = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

    # ==================================================
    # PUBLIC API
    # ==================================================

    def wake(self, color: str = "#4ade80"):
        """Show the orb with the given state color."""

        self.base_color = QColor(color)
        self.current_color = QColor(color)
        self._active = True
        self._target_opacity = 1.0
        self.show()

    def sleep(self):
        """Fade out and hide the orb."""

        self._active = False
        self._target_opacity = 0.0

    # ==================================================
    # ANIMATION
    # ==================================================

    def _tick(self):
        self.phase = (self.phase + 0.06) % (2 * pi)

        # Smooth opacity transitions toward the target.
        self.visible_phase += (
            self._target_opacity - self.visible_phase
        ) * 0.12

        if self.visible_phase < 0.02 and not self._active:
            if self.isVisible():
                self.hide()

            return

        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        if self.visible_phase <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setOpacity(self.visible_phase)

        size = min(self.width(), self.height())
        center = QPoint(self.width() // 2, self.height() // 2)
        cx, cy = center.x(), center.y()

        color = self.current_color

        breathe = (sin(self.phase * 1.7) + 1) / 2

        # ------------------------------------------------
        # Layer 1: soft radial glow
        # ------------------------------------------------
        glow_radius = size * (0.34 + 0.03 * breathe)

        gradient = QRadialGradient(cx, cy, glow_radius)

        glow_color = QColor(color)
        glow_color.setAlpha(70 + int(40 * breathe))

        gradient.setColorAt(0.0, glow_color)
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))

        painter.drawEllipse(
            QPoint(cx, cy),
            int(glow_radius),
            int(glow_radius),
        )

        # ------------------------------------------------
        # Layer 2: core orb with brighter center
        # ------------------------------------------------
        core_radius = size * (0.16 + 0.015 * breathe)

        core_gradient = QRadialGradient(cx, cy, core_radius)

        inner = QColor("white")
        inner.setAlpha(220)

        core_gradient.setColorAt(0.0, inner)
        core_gradient.setColorAt(0.55, color)
        core_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))

        painter.setBrush(QBrush(core_gradient))

        painter.drawEllipse(
            QPoint(cx, cy),
            int(core_radius),
            int(core_radius),
        )

        # ------------------------------------------------
        # Layer 3: orbiting arcs (Siri-like motion)
        # ------------------------------------------------
        for index in range(3):
            orbit_radius = size * (0.22 + 0.06 * index)

            pen_width = 4 - index

            arc_color = QColor(color)
            arc_color.setAlpha(160 - 40 * index)

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(arc_color, pen_width))

            start = (
                self.phase * (60 + 40 * index)
                + index * 2.1
            )

            span = 70 + 25 * sin(self.phase * (1.3 + 0.4 * index))

            from PySide6.QtCore import QRect

            rect = QRect(
                int(cx - orbit_radius),
                int(cy - orbit_radius),
                int(orbit_radius * 2),
                int(orbit_radius * 2),
            )

            painter.drawArc(rect, int(start * 16), int(span * 16))

        # ------------------------------------------------
        # Layer 4: faint outer shimmer ring
        # ------------------------------------------------
        shimmer = size * (0.42 + 0.015 * breathe)

        ring_color = QColor(color)
        ring_color.setAlpha(50)

        painter.setPen(QPen(ring_color, 2))
        painter.setBrush(Qt.NoBrush)

        painter.drawEllipse(
            QPoint(cx, cy),
            int(shimmer),
            int(shimmer),
        )


def get_overlay():
    """Return the shared overlay instance (creates on first call)."""

    global _overlay

    try:
        return _overlay
    except NameError:
        _overlay = WakeOverlay()
        return _overlay
