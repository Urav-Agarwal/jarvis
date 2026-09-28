"""
Conversation view for the JARVIS window.

Modern chat-style layout: rounded speech bubbles (user right/teal,
JARVIS left/slate), timestamps, auto-scroll, dark glass theme.
"""

from datetime import datetime

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_STYLE = """
QScrollArea {
    background: transparent;
    border: none;
}

QLabel#avatarUser {
    background-color: qlineargradient(x1:0 y1:0, x2:1 y2:1,
        stop:0 #0e7490, stop:1 #155e75);
    color: #ecfeff;
    border-radius: 14px;
    font-size: 12px;
    font-weight: 700;
}

QLabel#avatarJarvis {
    background-color: qlineargradient(x1:0 y1:0, x2:1 y2:1,
        stop:0 #22d3ee, stop:1 #2563eb);
    color: #06121c;
    border-radius: 14px;
    font-size: 12px;
    font-weight: 800;
}

QLabel#bubbleUser {
    background-color: qlineargradient(x1:0 y1:0, x2:1 y2:1,
        stop:0 #0e7490, stop:1 #0c5a70);
    color: #ecfeff;
    border-radius: 14px;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 4px;
    padding: 10px 14px;
    font-size: 14px;
}

QLabel#bubbleJarvis {
    background-color: rgba(19, 28, 40, 215);
    color: #dbeafe;
    border: 1px solid #1e2c3d;
    border-radius: 14px;
    border-bottom-left-radius: 4px;
    border-bottom-right-radius: 14px;
    padding: 10px 14px;
    font-size: 14px;
}

QLabel#bubbleName {
    color: #7dd3fc;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}

QLabel#bubbleNameUser {
    color: #67e8f9;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}

QLabel#bubbleTime {
    color: #46586e;
    font-size: 10px;
    background: transparent;
}

QLabel#typingBubble {
    background-color: rgba(19, 28, 40, 215);
    color: #67e8f9;
    border: 1px solid #1e2c3d;
    border-radius: 12px;
    padding: 8px 14px;
    font-size: 13px;
    letter-spacing: 3px;
}
"""


class ConversationView(QWidget):
    def __init__(self):
        super().__init__()

        self.setStyleSheet(_STYLE)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")

        self.messages_layout = QVBoxLayout(self.container)
        self.messages_layout.setContentsMargins(4, 4, 4, 4)
        self.messages_layout.setAlignment(Qt.AlignTop)
        self.messages_layout.setSpacing(10)

        self.scroll.setWidget(self.container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.scroll)

        # Persistent typing indicator, hidden until JARVIS thinks.
        self.typing_label = QLabel("● ● ●")
        self.typing_label.setObjectName("typingBubble")
        self.typing_label.hide()

        self._typing_row = QHBoxLayout()
        self._typing_row.addWidget(self._make_avatar(is_user=False))
        self._typing_row.addWidget(self.typing_label)
        self._typing_row.addStretch(1)

        self.messages_layout.addLayout(self._typing_row)

        self._add_welcome()

    # ==================================================
    # PUBLIC API
    # ==================================================

    def add_user_message(self, message: str):
        self._add_message("YOU", message, is_user=True)

    def add_jarvis_message(self, message: str):
        self._add_message("JARVIS", message, is_user=False)

    def show_typing(self):
        self.typing_label.show()
        self._scroll_to_bottom()

    def hide_typing(self):
        self.typing_label.hide()

    # ==================================================
    # INTERNALS
    # ==================================================

    @staticmethod
    def _make_avatar(is_user: bool) -> QLabel:
        avatar = QLabel("Y" if is_user else "J")

        avatar.setObjectName("avatarUser" if is_user else "avatarJarvis")
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignCenter)

        return avatar

    def _add_welcome(self):
        welcome = QLabel(
            'Say "Hey JARVIS" and ask me anything —\nI\'m listening.'
        )

        welcome.setObjectName("bubbleJarvis")
        welcome.setWordWrap(True)
        welcome.setMaximumWidth(520)

        row = QHBoxLayout()
        row.addWidget(self._make_avatar(is_user=False))
        row.addWidget(welcome)
        row.addStretch(1)

        self.messages_layout.addLayout(row)

    def _add_message(self, sender: str, message: str, is_user: bool):
        bubble = QLabel(message)

        bubble.setObjectName("bubbleUser" if is_user else "bubbleJarvis")
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        bubble.setMaximumWidth(480)

        self._animate_in(bubble)

        timestamp = datetime.now().strftime("%H:%M")

        name = QLabel(sender)
        name.setObjectName("bubbleNameUser" if is_user else "bubbleName")

        time_label = QLabel(timestamp)
        time_label.setObjectName("bubbleTime")

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)

        if is_user:
            meta_row.addStretch(1)
            meta_row.addWidget(time_label)
            meta_row.addWidget(name)
        else:
            meta_row.addWidget(name)
            meta_row.addWidget(time_label)
            meta_row.addStretch(1)

        text_column.addLayout(meta_row)
        text_column.addWidget(bubble)

        row = QHBoxLayout()
        row.setSpacing(10)

        if is_user:
            row.addStretch(1)
            row.addLayout(text_column)
            row.addWidget(self._make_avatar(is_user=True), 0, Qt.AlignBottom)
        else:
            row.addWidget(self._make_avatar(is_user=False), 0, Qt.AlignBottom)
            row.addLayout(text_column)
            row.addStretch(1)

        self.messages_layout.addLayout(row)

        self._scroll_to_bottom()

    def _animate_in(self, bubble: QLabel):
        """Fade + rise entrance for new bubbles (600ms, smooth)."""

        effect = QGraphicsOpacityEffect(bubble)
        bubble.setGraphicsEffect(effect)

        animation = QPropertyAnimation(effect, b"opacity", bubble)
        animation.setDuration(600)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        animation.start(QPropertyAnimation.DeleteWhenStopped)

    def _scroll_to_bottom(self):
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
