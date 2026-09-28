"""
The JARVIS core v2: a state-driven cinematic orb.

Layered glass sphere with a swirling energy core, counter-rotating
arc rings, drifting particles, an orbiting satellite ring while
thinking, waveform bars while speaking, and a checkmark flash on
completion. Animation intensity, speed, and extras are driven by the
agent state (set_state), matching the Iron-Man HUD reference.

Bugs fixed vs v1:
- The 30ms animation timer now STOPS when the widget is hidden
  (it used to burn CPU forever in the background).
- The sonar-pulse list is cleared on hide (it could grow unbounded).
- State changes actually change the animation (v1 only changed the
  color; idle spun as fast as executing).
"""

import math
import random
import time

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


class JarvisCore(QWidget):
    def __init__(self):
        super().__init__()

        self.setMinimumSize(220, 220)

        # Emerald default (mockup); color still morphs per state.
        self.color = QColor("#34d399")
        self._target_color = QColor("#34d399")

        self._state = "IDLE"

        # Per-state animation profile.
        self._PROFILE = {
            "IDLE": {
                "breath_speed": 0.9, "ring_speed": 0.35,
                "core_alpha": 150, "glow": 0.55, "particles": 8,
            },
            "LISTENING": {
                "breath_speed": 1.8, "ring_speed": 0.9,
                "core_alpha": 195, "glow": 0.9, "particles": 14,
            },
            "THINKING": {
                "breath_speed": 2.4, "ring_speed": 1.8,
                "core_alpha": 215, "glow": 1.0, "particles": 12,
                "satellite": True,
            },
            "EXECUTING": {
                "breath_speed": 2.1, "ring_speed": 1.5,
                "core_alpha": 205, "glow": 0.95, "particles": 12,
                "satellite": True,
            },
            "WAITING_FOR_CONFIRMATION": {
                "breath_speed": 1.3, "ring_speed": 0.5,
                "core_alpha": 185, "glow": 0.7, "particles": 9,
            },
            "SPEAKING": {
                "breath_speed": 1.7, "ring_speed": 0.7,
                "core_alpha": 200, "glow": 0.95, "particles": 16,
                "waveform": True,
            },
            "DONE": {
                "breath_speed": 1.2, "ring_speed": 0.4,
                "core_alpha": 190, "glow": 0.8, "particles": 10,
                "checkmark": True,
            },
            "SHUTTING_DOWN": {
                "breath_speed": 0.5, "ring_speed": 0.2,
                "core_alpha": 120, "glow": 0.4, "particles": 5,
            },
        }

        # Sonar pulses: spawn times.
        self._pulses = []
        self._last_pulse = 0.0

        # Drifting particles.
        self._particles = []
        self._seed_particles()

        # Done-flash timestamp.
        self._done_at = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(30)

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def set_state_color(self, color_hex: str):
        """Legacy API: color morph target."""
        self._target_color = QColor(color_hex)

    def set_state(self, state: str):
        """Drive the animation profile from the agent state."""
        if state in self._PROFILE:
            self._state = state

            if state == "DONE":
                self._done_at = time.time()

    # --------------------------------------------------
    # LIFECYCLE BUG FIXES
    # --------------------------------------------------

    def hideEvent(self, event):
        # v1 bug: the timer ran at 30ms forever, even hidden.
        self.timer.stop()
        self._pulses.clear()
        super().hideEvent(event)

    def showEvent(self, event):
        self.timer.start(30)
        super().showEvent(event)

    # --------------------------------------------------
    # PARTICLES
    # --------------------------------------------------

    def _seed_particles(self):
        self._particles = []

        for _ in range(18):
            self._particles.append(
                {
                    "angle": random.uniform(0, math.tau),
                    "radius": random.uniform(0.45, 1.25),
                    "speed": random.uniform(0.05, 0.22),
                    "size": random.uniform(1.2, 2.8),
                    "phase": random.uniform(0, math.tau),
                }
            )

    # --------------------------------------------------
    # FRAME
    # --------------------------------------------------

    def animate(self):
        now = time.time()

        # Color easing toward the state color.
        self.color.setRed(
            int(
                self.color.red()
                + (self._target_color.red() - self.color.red()) * 0.08
            )
        )
        self.color.setGreen(
            int(
                self.color.green()
                + (self._target_color.green() - self.color.green()) * 0.08
            )
        )
        self.color.setBlue(
            int(
                self.color.blue()
                + (self._target_color.blue() - self.color.blue()) * 0.08
            )
        )

        profile = self._PROFILE.get(
            self._state,
            self._PROFILE["IDLE"],
        )

        # Sonar pulse cadence scales with state energy.
        pulse_period = max(1.2, 3.2 - profile["ring_speed"])

        if now - self._last_pulse > pulse_period:
            self._last_pulse = now
            self._pulses.append(now)

        # Retire finished pulses.
        self._pulses = [
            pulse for pulse in self._pulses if now - pulse < 2.0
        ]

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center = self.rect().center()
        side = min(self.width(), self.height())

        scale = side / 260.0

        t = time.time()
        profile = self._PROFILE.get(
            self._state,
            self._PROFILE["IDLE"],
        )

        breath_speed = profile["breath_speed"]
        ring_speed = profile["ring_speed"]

        breath = (math.sin(t * breath_speed) + 1) / 2

        core_radius = (44 + breath * 5) * scale
        sphere_radius = 74 * scale
        ring_base = 96 * scale

        # --------------------------------------------------
        # 1. Ambient glow (scales with state energy)
        # --------------------------------------------------
        glow_radius = ring_base * (1.75 + profile["glow"] * 0.35)

        glow = QRadialGradient(center, glow_radius)

        glow_color = QColor(self.color)
        glow_color.setAlpha(
            int((18 + breath * 16) * profile["glow"])
        )

        glow.setColorAt(0.0, glow_color)

        fade = QColor(self.color)
        fade.setAlpha(0)

        glow.setColorAt(1.0, fade)

        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, glow_radius, glow_radius)

        # --------------------------------------------------
        # 2. Two counter-rotating conical arc rings
        # --------------------------------------------------
        rings = [
            (ring_base, ring_speed, 150, 3.0),
            (ring_base * 0.88, -ring_speed * 1.5, 100, 2.2),
        ]

        for radius, speed, alpha, width in rings:
            angle = (t * speed * 57.3) % 360

            gradient = QConicalGradient(center, -angle)

            start = QColor(self.color)
            start.setAlpha(alpha)

            end = QColor(self.color)
            end.setAlpha(0)

            gradient.setColorAt(0.0, start)
            gradient.setColorAt(0.32, end)
            gradient.setColorAt(1.0, end)

            painter.setPen(
                QPen(
                    gradient,
                    width * scale,
                    Qt.SolidLine,
                    Qt.RoundCap,
                )
            )
            painter.setBrush(Qt.NoBrush)

            painter.drawEllipse(center, radius, radius)

        # --------------------------------------------------
        # 3. THINKING/EXECUTING: orbiting satellite ring
        # --------------------------------------------------
        if profile.get("satellite"):
            painter.save()

            painter.translate(center)

            # Tilted elliptical orbit, precessing slowly.
            painter.rotate(18 * math.sin(t * 0.6))

            orbit_rx = sphere_radius * 1.28
            orbit_ry = sphere_radius * 0.42

            orbit_pen = QColor(self.color)
            orbit_pen.setAlpha(120)

            painter.setPen(QPen(orbit_pen, 1.8 * scale))
            painter.setBrush(Qt.NoBrush)

            painter.drawEllipse(QPointF(0, 0), orbit_rx, orbit_ry)

            # Satellite dot riding the orbit.
            sat_angle = t * 2.4

            sat_x = orbit_rx * math.cos(sat_angle)
            sat_y = orbit_ry * math.sin(sat_angle)

            sat_color = QColor(255, 255, 255, 230)

            painter.setPen(Qt.NoPen)
            painter.setBrush(sat_color)

            painter.drawEllipse(
                QPointF(sat_x, sat_y),
                3.4 * scale,
                3.4 * scale,
            )

            painter.restore()

        # --------------------------------------------------
        # 4. SPEAKING: waveform bars flanking the sphere
        # --------------------------------------------------
        if profile.get("waveform"):
            bar_count = 4

            for side_sign in (-1, 1):
                base_x = center.x() + side_sign * (
                    sphere_radius + 16 * scale
                )

                for index in range(bar_count):
                    offset = index * 9 * scale

                    wave = (
                        math.sin(
                            t * 9 + index * 1.4 + side_sign
                        )
                        + 1
                    ) / 2

                    bar_height = (8 + wave * 26) * scale

                    bar_color = QColor(self.color)
                    bar_color.setAlpha(90 + int(wave * 130))

                    painter.setPen(Qt.NoPen)
                    painter.setBrush(bar_color)

                    bar_x = base_x + side_sign * offset

                    painter.drawRoundedRect(
                        QRectF(
                            bar_x - 1.8 * scale,
                            center.y() - bar_height / 2,
                            3.6 * scale,
                            bar_height,
                        ),
                        2,
                        2,
                    )

        # --------------------------------------------------
        # 5. Drifting particles
        # --------------------------------------------------
        painter.setPen(Qt.NoPen)

        target_particles = profile["particles"]

        for index, particle in enumerate(self._particles):
            if index >= target_particles:
                break

            particle["angle"] += (
                particle["speed"] * 0.016 * (1 + ring_speed)
            )

            radius = (
                particle["radius"]
                + 0.05 * math.sin(t + particle["phase"])
            )

            x = center.x() + radius * (
                sphere_radius * 1.35
            ) * math.cos(particle["angle"])

            y = center.y() + radius * (
                sphere_radius * 1.35
            ) * math.sin(particle["angle"]) * 0.96

            alpha = 40 + int(
                70 * (math.sin(t * 2 + particle["phase"]) + 1) / 2
            )

            dot = QColor(self.color)
            dot.setAlpha(alpha)

            painter.setBrush(dot)

            painter.drawEllipse(
                QPointF(x, y),
                particle["size"] * scale,
                particle["size"] * scale,
            )

        # --------------------------------------------------
        # 6. Glass sphere: body, inner swirl, rim light
        # --------------------------------------------------
        body = QRadialGradient(
            center.x() - core_radius * 0.3,
            center.y() - core_radius * 0.4,
            sphere_radius * 1.35,
        )

        body_edge = QColor(self.color)
        body_edge.setAlpha(profile["core_alpha"])

        body.setColorAt(0.0, QColor(255, 255, 255, 60))
        body.setColorAt(0.55, QColor(10, 30, 26, 150))
        body.setColorAt(1.0, body_edge)

        painter.setBrush(body)
        painter.setPen(Qt.NoPen)

        painter.drawEllipse(center, sphere_radius, sphere_radius)

        # Inner swirl: two spiral arcs clipped to the sphere.
        painter.save()

        swirl_path = QPainterPath()
        swirl_path.addEllipse(
            center,
            sphere_radius * 0.94,
            sphere_radius * 0.94,
        )

        painter.setClipPath(swirl_path)

        painter.translate(center)

        for index, (swirl_speed, swirl_alpha) in enumerate(
            ((0.8, 170), (-0.55, 120))
        ):
            swirl_angle = t * swirl_speed * 57.3

            painter.save()

            painter.rotate(swirl_angle + index * 120)

            swirl_color = QColor(self.color)
            swirl_color.setAlpha(swirl_alpha)

            painter.setPen(
                QPen(
                    swirl_color,
                    5.5 * scale,
                    Qt.SolidLine,
                    Qt.RoundCap,
                )
            )
            painter.setBrush(Qt.NoBrush)

            # Open arc: most of a circle; the gap gives swirl motion.
            arc_rect = QRectF(
                -sphere_radius * 0.55,
                -sphere_radius * 0.55,
                sphere_radius * 1.1,
                sphere_radius * 1.1,
            )

            painter.drawArc(arc_rect, 0, 280 * 16)

            # Arc tip dot: the comet head of the swirl.
            tip_x = sphere_radius * 0.55
            tip_y = 0.0

            tip = QColor(self.color)
            tip.setAlpha(min(255, swirl_alpha + 60))

            painter.setPen(Qt.NoPen)
            painter.setBrush(tip)

            painter.drawEllipse(
                QPointF(tip_x, tip_y),
                4.2 * scale,
                4.2 * scale,
            )

            painter.restore()

        painter.restore()

        # Rim light: bright arc top-left, glass feel.
        rim_rect = QRectF(
            center.x() - sphere_radius,
            center.y() - sphere_radius,
            sphere_radius * 2,
            sphere_radius * 2,
        )

        rim = QColor(255, 255, 255, 170)

        painter.setPen(
            QPen(rim, 2.4 * scale, Qt.SolidLine, Qt.RoundCap)
        )
        painter.setBrush(Qt.NoBrush)

        painter.drawArc(rim_rect, 100 * 16, 80 * 16)

        # Bottom rim reflection, fainter.
        rim_low = QColor(255, 255, 255, 60)

        painter.setPen(QPen(rim_low, 2.0 * scale))

        painter.drawArc(rim_rect, 280 * 16, 50 * 16)

        # --------------------------------------------------
        # 7. DONE: checkmark flash
        # --------------------------------------------------
        if profile.get("checkmark"):
            elapsed = time.time() - self._done_at

            if elapsed < 1.6:
                fade_alpha = int(
                    255 * max(0.0, 1.0 - elapsed / 1.6)
                )

                check = QColor(255, 255, 255, fade_alpha)

                painter.setPen(
                    QPen(
                        check,
                        6 * scale,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.RoundJoin,
                    )
                )
                painter.setBrush(Qt.NoBrush)

                check_size = sphere_radius * 0.42

                painter.drawPolyline(
                    [
                        QPointF(
                            center.x() - check_size * 0.7,
                            center.y(),
                        ),
                        QPointF(
                            center.x() - check_size * 0.1,
                            center.y() + check_size * 0.55,
                        ),
                        QPointF(
                            center.x() + check_size * 0.75,
                            center.y() - check_size * 0.55,
                        ),
                    ]
                )

        # --------------------------------------------------
        # 8. Outer structure ring
        # --------------------------------------------------
        static_ring = QColor(self.color)
        static_ring.setAlpha(40)

        painter.setPen(QPen(static_ring, 1.2 * scale))
        painter.setBrush(Qt.NoBrush)

        painter.drawEllipse(
            center,
            ring_base * 1.18,
            ring_base * 1.18,
        )

        painter.end()
