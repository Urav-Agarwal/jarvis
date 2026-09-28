"""
Frameless title bar for the JARVIS window, mockup-exact:

orb brand + "JARVIS / DESKTOP AGENT" wordmark on the left, the
time-aware greeting centered, and a clock card plus notification,
minimize, maximize and close controls on the right. Handles window
dragging and double-click maximize.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_STYLE = """
QWidget#titleBar {
    background-color: rgba(8, 13, 24, 150);
    border-bottom: 1px solid #101c30;
}

QLabel#brand {
    color: #dbeafe;
    font-size: 19px;
    font-weight: 600;
    letter-spacing: 9px;
}

QLabel#brandSub {
    color: #3f5673;
    font-size: 8px;
    letter-spacing: 4px;
    padding-top: 3px;
}

QLabel#greeting {
    color: #d7e6fb;
    font-size: 15px;
    font-weight: 600;
}

QLabel#tagline {
    color: #54688a;
    font-size: 10px;
    font-style: italic;
    padding-top: 2px;
}

QWidget#clockCard {
    background-color: rgba(12, 20, 34, 235);
    border: 1px solid #16263c;
    border-radius: 12px;
}

QLabel#clockTime {
    color: #eaf2ff;
    font-size: 19px;
    font-weight: 700;
}

QLabel#clockDate {
    color: #54688a;
    font-size: 9px;
}

QPushButton#winButton {
    color: #6b80a0;
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 5px 11px;
}

QPushButton#winButton:hover {
    color: #e6eefb;
    background-color: #142131;
    border-radius: 8px;
}

QPushButton#closeButton {
    color: #6b80a0;
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 5px 11px;
}

QPushButton#closeButton:hover {
    color: #fecaca;
    background-color: #7f1d1d;
    border-radius: 8px;
}
"""


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)

        self.window_ref = window

        self.setObjectName("titleBar")
        self.setStyleSheet(_STYLE)
        self.setFixedHeight(74)

        self._drag_position = None
        self._maximized = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 10, 8)
        layout.setSpacing(10)

        # ------------------------------------------------
        # BRAND: glowing orb + JARVIS wordmark
        # ------------------------------------------------
        self.dot = QLabel()
        self.dot.setFixedSize(38, 38)
        self.dot.setAlignment(Qt.AlignCenter)
        self.dot.setStyleSheet(
            "border-radius: 19px;"
            "background-color: qradialgradient(cx:0.5 cy:0.42, radius:0.55, "
            "stop:0 #e0f7ff, stop:0.35 #38bdf8, stop:0.75 #1d4ed8, stop:1 #0b1f3d);"
            "border: 2px solid #2563eb;"
        )

        brand_column = QVBoxLayout()
        brand_column.setSpacing(0)

        brand = QLabel("J A R V I S")
        brand.setObjectName("brand")

        subtitle = QLabel("DESKTOP AGENT")
        subtitle.setObjectName("brandSub")

        brand_column.addWidget(brand)
        brand_column.addWidget(subtitle)

        layout.addWidget(self.dot)
        layout.addSpacing(6)
        layout.addLayout(brand_column)

        layout.addStretch(1)

        # ------------------------------------------------
        # CENTER: time-aware greeting + tagline
        # ------------------------------------------------
        center_column = QVBoxLayout()
        center_column.setSpacing(0)

        greeting_row = QHBoxLayout()
        greeting_row.setAlignment(Qt.AlignCenter)
        greeting_row.setSpacing(8)

        moon = QLabel("🌙")
        moon.setStyleSheet("font-size: 14px; background: transparent;")

        self.greeting = QLabel("")
        self.greeting.setObjectName("greeting")

        greeting_row.addWidget(moon)
        greeting_row.addWidget(self.greeting)

        self.tagline = QLabel("")
        self.tagline.setObjectName("tagline")
        self.tagline.setAlignment(Qt.AlignCenter)

        center_column.addLayout(greeting_row)
        center_column.addWidget(self.tagline)

        layout.addLayout(center_column)

        layout.addStretch(1)

        # ------------------------------------------------
        # CLOCK CARD
        # ------------------------------------------------
        clock_card = QWidget()
        clock_card.setObjectName("clockCard")

        clock_layout = QVBoxLayout(clock_card)
        clock_layout.setContentsMargins(16, 6, 16, 6)
        clock_layout.setSpacing(0)

        self.clock = QLabel()
        self.clock.setObjectName("clockTime")
        self.clock.setAlignment(Qt.AlignCenter)

        self.date_label = QLabel()
        self.date_label.setObjectName("clockDate")
        self.date_label.setAlignment(Qt.AlignCenter)

        clock_layout.addWidget(self.clock)
        clock_layout.addWidget(self.date_label)

        self._update_clock()

        clock_timer = QTimer(self)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start(10_000)

        layout.addWidget(clock_card)
        layout.addSpacing(6)

        # ------------------------------------------------
        # NOTIFICATION + WINDOW CONTROLS
        # ------------------------------------------------
        bell = QPushButton("🔔")
        bell.setObjectName("winButton")
        bell.setCursor(Qt.PointingHandCursor)
        bell.setToolTip("Notifications")
        bell.clicked.connect(self._notify)

        minimize = QPushButton("─")
        minimize.setObjectName("winButton")
        minimize.setCursor(Qt.PointingHandCursor)
        minimize.clicked.connect(self.window_ref.showMinimized)

        self.maximize = QPushButton("☐")
        self.maximize.setObjectName("winButton")
        self.maximize.setCursor(Qt.PointingHandCursor)
        self.maximize.clicked.connect(self._toggle_maximize)

        close = QPushButton("✕")
        close.setObjectName("closeButton")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.window_ref.close)

        layout.addWidget(bell)
        layout.addWidget(minimize)
        layout.addWidget(self.maximize)
        layout.addWidget(close)

    def _update_clock(self):
        now = datetime.now()

        self.clock.setText(now.strftime("%H:%M"))
        self.date_label.setText(now.strftime("%a, %d %b %Y"))

    def _notify(self):
        self.window_ref.tray.showMessage(
            "All systems nominal",
            "No new notifications, sir.",
            self.window_ref.tray.Information,
            2500,
        )

    def _toggle_maximize(self):
        if self.window_ref.isMaximized():
            self.window_ref.showNormal()
        else:
            self.window_ref.showMaximized()

    def set_greeting(self, text: str, tagline: str = ""):
        self.greeting.setText(text)
        self.tagline.setText(tagline)

    # --------------------------------------------------
    # STATUS (state ring on the brand orb; full mode is
    # shown in the CURRENT MODE card of the rail)
    # --------------------------------------------------

    def set_status(self, text: str, color: str):
        self.dot.setStyleSheet(
            "border-radius: 19px;"
            "background-color: qradialgradient(cx:0.5 cy:0.42, radius:0.55, "
            "stop:0 #e0f7ff, stop:0.35 #38bdf8, stop:0.75 #1d4ed8, stop:1 #0b1f3d);"
            f"border: 2px solid {color};"
        )

    # --------------------------------------------------
    # DRAGGING + DOUBLE-CLICK MAXIMIZE
    # --------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_position = (
                event.globalPosition().toPoint()
                - self.window_ref.frameGeometry().topLeft()
            )

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_position is not None
            and event.buttons() & Qt.LeftButton
        ):
            self.window_ref.move(
                event.globalPosition().toPoint()
                - self._drag_position
            )

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_position = None

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._toggle_maximize()

        super().mouseDoubleClickEvent(event)
