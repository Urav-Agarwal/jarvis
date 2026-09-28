"""
Left navigation sidebar, mockup-exact: Chat / Apps / Files / Web
Search / Automation / Reminders / System Control / Notes / Settings
with icon glyphs, one selected item with a glowing gradient pill,
and the Urav / JARVIS v1.0 user card at the bottom. Selecting a
section fires its ready-made command through the chip callback.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_STYLE = """
QWidget#sidebar {
    background-color: rgba(9, 14, 26, 225);
    border: 1px solid #12203a;
    border-radius: 16px;
}

QPushButton#navButton {
    color: #7d94b4;
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 11px 14px;
    font-size: 13px;
    text-align: left;
}

QPushButton#navButton:hover {
    color: #dbeafe;
    background-color: #0e1c33;
}

QPushButton#navButton:checked {
    color: #eaf2ff;
    background-color: qlineargradient(x1:0 y1:0, x2:1 y2:0,
        stop:0 rgba(37, 99, 235, 110), stop:1 rgba(56, 189, 248, 45));
    border: 1px solid #2c5fc4;
}

QWidget#userCard {
    background-color: rgba(13, 21, 36, 235);
    border: 1px solid #1a2c48;
    border-radius: 14px;
}

QLabel#userName {
    color: #eaf2ff;
    font-size: 13px;
    font-weight: 600;
}

QLabel#userSub {
    color: #54688a;
    font-size: 10px;
}
"""

SECTIONS = [
    ("Chat", "💬", None),
    ("Apps", "🚀", "open whatsapp"),
    ("Files", "📁", "find my physics notes"),
    ("Web Search", "🔍", "search the web for today's tech news"),
    ("Automation", "⚡", "whenever I say study setup, open Chrome and set volume to 30"),
    ("Reminders", "🗓️", "what are my reminders"),
    ("System Control", "🖥️", "how is my laptop doing"),
    ("Notes", "📝", "take a note"),
    ("Settings", "⚙️", "what can you do"),
]


class Sidebar(QWidget):
    def __init__(self, on_command=None):
        super().__init__()

        self.on_command = on_command

        self.setObjectName("sidebar")
        self.setStyleSheet(_STYLE)
        self.setFixedWidth(186)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(4)

        self._buttons = {}

        for name, icon, command in SECTIONS:
            button = QPushButton(f"{icon}   {name}")
            button.setObjectName("navButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setChecked(name == "Chat")

            button.clicked.connect(
                lambda checked, n=name, c=command: self._select(n, c)
            )

            layout.addWidget(button)

            self._buttons[name] = button

        layout.addStretch(1)

        # ------------------------------------------------
        # User card (bottom)
        # ------------------------------------------------
        card = QWidget()
        card.setObjectName("userCard")

        from PySide6.QtWidgets import QHBoxLayout

        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 8, 12)
        card_layout.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "border-radius: 17px;"
            "background-color: qradialgradient(cx:0.5 cy:0.42, radius:0.55, "
            "stop:0 #e0f7ff, stop:0.4 #38bdf8, stop:1 #0b1f3d);"
            "border: 2px solid #1e4a6d;"
        )

        text_column = QVBoxLayout()
        text_column.setSpacing(1)

        name = QLabel("Urav")
        name.setObjectName("userName")

        sub = QLabel("JARVIS v1.0")
        sub.setObjectName("userSub")

        text_column.addWidget(name)
        text_column.addWidget(sub)

        arrow = QLabel("›")
        arrow.setStyleSheet("color: #54688a; font-size: 16px;")

        card_layout.addWidget(avatar)
        card_layout.addLayout(text_column, 1)
        card_layout.addWidget(arrow)

        layout.addWidget(card)

    def _select(self, name: str, command):
        # Radio behavior: exactly one active section.
        for other_name, button in self._buttons.items():
            button.setChecked(other_name == name)

        if command and self.on_command is not None:
            self.on_command(command)
