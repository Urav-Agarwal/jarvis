"""
Right-hand system rail, mockup-exact: SYSTEM STATUS (four ring
gauges + running badge), CURRENT MODE (status pill + waveform),
QUICK ACTIONS (3x2 icon-tile grid), and RECENT ACTIVITY (icon
rows with relative timestamps). Pure psutil polling — no LLM.
"""

import time

import psutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.components.hud_widgets import Waveform


_STYLE = """
QWidget#railCard {
    background-color: rgba(12, 19, 34, 225);
    border: 1px solid #15243c;
    border-radius: 16px;
}

QLabel#railHeading {
    color: #7d94b4;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
}

QLabel#runningBadge {
    color: #4ade80;
    font-size: 11px;
    font-weight: 600;
}

QLabel#metricName {
    color: #8fa8c4;
    font-size: 11px;
}

QLabel#modeChip {
    color: #c4b5fd;
    background-color: rgba(76, 29, 149, 120);
    border: 1px solid #7c3aed;
    border-radius: 12px;
    padding: 4px 14px;
    font-size: 12px;
    font-weight: 600;
}

QWidget#actionTile {
    background-color: rgba(16, 26, 44, 235);
    border: 1px solid #1a2c48;
    border-radius: 14px;
}

QWidget#actionTile:hover {
    border: 1px solid #2c5fc4;
    background-color: rgba(23, 37, 63, 240);
}

QLabel#tileIcon {
    color: #7dd3fc;
    font-size: 17px;
    background: transparent;
}

QLabel#tileLabel {
    color: #c9d8ee;
    font-size: 11px;
    background: transparent;
}

QLabel#activityRow {
    color: #c9d8ee;
    font-size: 12px;
    background: transparent;
}

QLabel#activityTime {
    color: #54688a;
    font-size: 10px;
    background: transparent;
}

QLabel#statusBody {
    color: #647d99;
    font-size: 11px;
}
"""


class _Card(QWidget):
    def __init__(self):
        super().__init__()

        self.setObjectName("railCard")


class _ActionTile(QWidget):
    """Mockup quick-action tile: emoji icon over a small label."""

    def __init__(self, icon, label, on_click):
        super().__init__()

        self.setObjectName("actionTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(76, 62)

        self._on_click = on_click

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 8)
        layout.setSpacing(6)

        icon_label = QLabel(icon)
        icon_label.setObjectName("tileIcon")
        icon_label.setAlignment(Qt.AlignCenter)

        text_label = QLabel(label)
        text_label.setObjectName("tileLabel")
        text_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon_label)
        layout.addWidget(text_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._on_click:
            self._on_click()

        super().mousePressEvent(event)


class SystemRail(QWidget):
    """
    Mockup rail: SYSTEM STATUS / CURRENT MODE / QUICK ACTIONS /
    RECENT ACTIVITY cards in a single column.
    """

    def __init__(self, on_chip=None):
        super().__init__()

        self.on_chip = on_chip

        self._activity_items = []
        self._activity_rows = []
        self._mode_chip_text = "Voice Listening"

        self.setFixedWidth(280)
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ------------------------------------------------
        # SYSTEM STATUS card: heading + Running + 4 gauges
        # ------------------------------------------------
        system_card = _Card()

        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(16, 14, 16, 14)
        system_layout.setSpacing(12)

        heading_row = QHBoxLayout()

        heading = QLabel("SYSTEM STATUS")
        heading.setObjectName("railHeading")

        self.running_dot = QLabel("● Running")
        self.running_dot.setObjectName("runningBadge")

        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(self.running_dot)

        system_layout.addLayout(heading_row)

        # Circular gauges row (4: CPU / RAM / Storage / Battery).
        from ui.components.hud_widgets import RingGauge

        gauges = QHBoxLayout()
        gauges.setSpacing(4)

        self.cpu = RingGauge("CPU")
        self.ram = RingGauge("RAM")
        self.disk = RingGauge("Storage")
        self.battery = RingGauge("Battery")

        for gauge in (self.cpu, self.ram, self.disk, self.battery):
            gauges.addWidget(gauge, 1)

        system_layout.addLayout(gauges)

        layout.addWidget(system_card)

        # ------------------------------------------------
        # CURRENT MODE card: pill + waveform
        # ------------------------------------------------
        mode_card = _Card()

        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(16, 14, 16, 14)
        mode_layout.setSpacing(10)

        mode_heading_row = QHBoxLayout()

        mode_heading = QLabel("CURRENT MODE")
        mode_heading.setObjectName("railHeading")

        self.mode_chip = QLabel("🔊  Voice Listening")
        self.mode_chip.setObjectName("modeChip")

        mode_heading_row.addWidget(mode_heading)
        mode_heading_row.addStretch(1)
        mode_heading_row.addWidget(self.mode_chip)

        # Living waveform: amplitude follows agent activity.
        self.waveform = Waveform(bars=32)
        self.waveform.setFixedHeight(64)

        mode_layout.addLayout(mode_heading_row)
        mode_layout.addWidget(self.waveform)

        layout.addWidget(mode_card)

        # ------------------------------------------------
        # QUICK ACTIONS card: 3x2 icon tiles
        # ------------------------------------------------
        actions_card = _Card()

        actions_layout = QVBoxLayout(actions_card)
        actions_layout.setContentsMargins(16, 14, 16, 14)
        actions_layout.setSpacing(8)

        actions_heading_row = QHBoxLayout()

        actions_heading = QLabel("QUICK ACTIONS")
        actions_heading.setObjectName("railHeading")

        actions_heading_row.addWidget(actions_heading)

        actions_layout.addLayout(actions_heading_row)

        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)

        # Label -> the exact spoken command JARVIS understands.
        quick_actions = [
            ("📸", "Screenshot", "take a screenshot"),
            ("➕", "New Tab", "open a new tab"),
            ("🔒", "Lock PC", "lock my laptop"),
            ("🔊", "Volume", "open volume control"),
            ("☀️", "Brightness", "open brightness settings"),
            ("📝", "Take Note", "take a note"),
        ]

        for index, (icon, label, command) in enumerate(quick_actions):
            tile = _ActionTile(
                icon,
                label,
                on_click=(
                    (lambda c=command: on_chip(c)) if on_chip else None
                ),
            )

            actions_grid.addWidget(
                tile,
                index // 3,
                index % 3,
            )

        actions_layout.addLayout(actions_grid)

        layout.addWidget(actions_card)

        # ------------------------------------------------
        # RECENT ACTIVITY card: heading + "View all"
        # ------------------------------------------------
        activity_card = _Card()
        activity_card.setMinimumHeight(200)

        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(16, 14, 16, 14)
        activity_layout.setSpacing(8)

        activity_heading_row = QHBoxLayout()

        activity_heading = QLabel("RECENT ACTIVITY")
        activity_heading.setObjectName("railHeading")

        view_all = QLabel("View all")
        view_all.setStyleSheet(
            "color: #38bdf8; font-size: 11px; background: transparent;"
        )

        activity_heading_row.addWidget(activity_heading)
        activity_heading_row.addStretch(1)
        activity_heading_row.addWidget(view_all)

        activity_layout.addLayout(activity_heading_row)

        self.activity_layout = QVBoxLayout()
        self.activity_layout.setSpacing(8)

        self._activity_placeholder = QLabel("Nothing yet — talk to me.")
        self._activity_placeholder.setObjectName("statusBody")
        self._activity_placeholder.setWordWrap(True)

        self.activity_layout.addWidget(self._activity_placeholder)

        activity_layout.addLayout(self.activity_layout)
        activity_layout.addStretch(1)

        layout.addWidget(activity_card, 1)

        # ------------------------------------------------
        # Telemetry polling
        # ------------------------------------------------
        self._update_telemetry()

        from PySide6.QtCore import QTimer

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_telemetry)
        self._timer.start(2500)

    # --------------------------------------------------
    # MODE PILL (mockup: "Voice Listening", purple)
    # --------------------------------------------------

    _MODES = {
        "IDLE": ("🔊  Voice Listening", True),
        "LISTENING": ("🎙️  Listening", False),
        "THINKING": ("🧠  Thinking", False),
        "EXECUTING": ("⚙️  Executing", False),
        "WAITING_FOR_CONFIRMATION": ("👤  Awaiting You", False),
        "SHUTTING_DOWN": ("💤  Sleeping", False),
    }

    def set_mode(self, state: str):
        text, _dim = self._MODES.get(
            state,
            (f"⚙️  {state.title()}", False),
        )

        self._mode_chip_text = text

        self.mode_chip.setText(text)

    # --------------------------------------------------
    # AGENT STATUS LINE (kept for state sweep compatibility)
    # --------------------------------------------------

    def set_agent_status(self, title: str, body: str):
        # The mockup shows the mode as the pill (set_mode) — no
        # separate agent card. Kept as a no-op-compatible hook.
        pass

    # --------------------------------------------------
    # RECENT ACTIVITY FEED (icon rows + relative times)
    # --------------------------------------------------

    _ACTIVITY_ICONS = [
        ("chrome", "🌐"),
        ("vs code", "🧩"),
        ("vscode", "🧩"),
        ("code", "🧩"),
        ("search", "🔍"),
        ("youtube", "▶️"),
        ("download", "📁"),
        ("file", "📁"),
        ("folder", "📁"),
        ("remind", "⏰"),
        ("note", "📝"),
        ("volume", "🔊"),
        ("brightness", "☀️"),
        ("whatsapp", "💬"),
        ("instagram", "📷"),
        ("spotify", "🎧"),
        ("lock", "🔒"),
        ("screenshot", "📸"),
    ]

    def _icon_for(self, text: str) -> str:
        lowered = text.lower()

        for needle, icon in self._ACTIVITY_ICONS:
            if needle in lowered:
                return icon

        return "🔹"

    def add_activity(self, text: str):
        """Prepend a compact activity row (max 4 visible)."""

        from datetime import datetime

        # The placeholder QLabel can be C++-deleted once removed by
        # deleteLater; guard so a late call can never raise.
        if self._activity_placeholder is not None:
            try:
                self._activity_placeholder.hide()

            except RuntimeError:
                pass

            self._activity_placeholder = None

        from PySide6.QtWidgets import QHBoxLayout

        icon = self._icon_for(text)

        row_label = QLabel(f"{icon}  {text}")
        row_label.setObjectName("activityRow")

        time_label = QLabel(
            datetime.now().strftime("%H:%M")
        )
        time_label.setObjectName("activityTime")

        line = QHBoxLayout()
        line.setSpacing(8)
        line.addWidget(row_label, 1)
        line.addWidget(time_label)

        self.activity_layout.insertLayout(0, line)
        self._activity_rows.append(line)

        # Keep at most 4 rows (rows are nested layouts).
        while len(self._activity_rows) > 4:
            old = self._activity_rows.pop(0)

            while old.count():
                child = old.takeAt(0)

                child_widget = child.widget()

                if child_widget is not None:
                    child_widget.deleteLater()

    def note_command(self):
        """One more command counted this session (reserved)."""

        pass

    # --------------------------------------------------
    # TELEMETRY
    # --------------------------------------------------

    def _update_telemetry(self):
        try:
            self.cpu.set_value(int(psutil.cpu_percent(interval=None)))

            ram = psutil.virtual_memory()

            self.ram.set_value(int(ram.percent))

            try:
                battery = psutil.sensors_battery()

                if battery is not None:
                    percent = int(battery.percent)

                    if battery.power_plugged:
                        self.battery.set_value(
                            percent,
                            f"⚡ {percent}%",
                        )

                    else:
                        self.battery.set_value(percent)

                else:
                    self.battery.set_value(0, "n/a")

            except Exception:
                self.battery.set_value(0, "n/a")

            # Disk usage (root partition).
            disk = psutil.disk_usage("C:\\")

            self.disk.set_value(int(disk.percent))

        except Exception:
            pass

    # --------------------------------------------------
    # STATE VISUALS (waveform color/energy)
    # --------------------------------------------------

    def set_state_visuals(self, color_hex: str, activity: float):
        self.waveform.set_color(color_hex)
        self.waveform.set_level(activity)
