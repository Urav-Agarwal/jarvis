"""
JARVIS application entry point.

Architecture: the voice listener is the primary process. It starts
automatically (desktop shortcut / Windows startup), runs always in the
background, and answers to "Hey JARVIS" with the wake orb — even when
no main window is visible. The main window (conversation, status,
memory) is an OPTIONAL view on top of the always-running agent.

Closing the window hides it to the tray; JARVIS keeps listening.
Right-click the tray icon to reopen the window or quit JARVIS.
"""

import os
import sys
import time
from pathlib import Path

# Bootstrap: allow launching as a script ("pythonw app\main.py" from
# a shortcut) by putting the project root on the import path.
ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ANCHOR THE CWD: every data path in the app (data/, config/, the
# TTS cache, skills) is relative. Launching from a shortcut or the
# Task Scheduler with a different working directory made "data"
# resolve into e.g. C:\Windows\System32\data -> PermissionError ->
# the listener thread died at startup and "Hey JARVIS" went deaf.
os.chdir(ROOT)

# --------------------------------------------------------------
# BOOT LOG: pythonw has no console, so uncaught boot errors are
# invisible. Capture stderr to data/boot_log.txt (size-capped).
# --------------------------------------------------------------
try:
    _boot_log = ROOT / "data" / "boot_log.txt"

    _boot_log.parent.mkdir(parents=True, exist_ok=True)

    if _boot_log.exists() and _boot_log.stat().st_size > 1_000_000:
        _boot_log.unlink()

    _boot_err = open(
        _boot_log,
        "a",
        buffering=1,
        encoding="utf-8",
    )

    sys.stderr = _boot_err

except OSError:
    _boot_err = None

from threading import Thread

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from assistant.orchestrator import Orchestrator
from ui.components.conversation import ConversationView
from ui.components.core import JarvisCore
from ui.components.sidebar import Sidebar
from ui.components.system_rail import SystemRail
from ui.components.title_bar import TitleBar
from ui.components.wake_overlay import get_overlay


class AssistantBridge(QObject):
    user_message = Signal(str)
    jarvis_message = Signal(str)
    status_message = Signal(str)
    state_message = Signal(str)
    show_requested = Signal()


def _tray_icon() -> QIcon:
    """Generated glowing-orb icon (assets/jarvis.ico/png)."""

    icon_path = ROOT / "assets" / "jarvis.ico"

    if icon_path.exists():
        return QIcon(str(icon_path))

    png_path = ROOT / "assets" / "jarvis.png"

    if png_path.exists():
        return QIcon(str(png_path))

    return QIcon()


def _tray_icon_pixmap() -> QIcon:
    """Backwards-compatible alias."""

    return _tray_icon()


class JarvisWindow(QMainWindow):
    """The optional JARVIS view. The agent runs without it."""

    def __init__(self, bridge: AssistantBridge):
        super().__init__()

        self.bridge = bridge

        self.setWindowTitle("JARVIS")
        self.setMinimumSize(1180, 760)
        self.resize(1533, 864)

        # Glowing-orb icon for window + taskbar.
        self.setWindowIcon(_tray_icon())

        self.setStyleSheet("""
            QMainWindow {
                background-color: #070a0f;
            }

            QLabel {
                color: #e6eefb;
                font-family: 'Segoe UI';
            }

            QPushButton#chip {
                color: #c9d8ee;
                background-color: rgba(14, 24, 42, 230);
                border: 1px solid #1b2c48;
                border-radius: 15px;
                padding: 7px 14px;
                font-size: 12px;
            }

            QPushButton#chip:hover {
                color: #ffffff;
                border: 1px solid #2c5fc4;
                background-color: rgba(23, 37, 63, 240);
            }
        """)

        # Frameless window: the custom title bar handles dragging,
        # minimize, close, and double-click maximize.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        central_widget = QWidget()
        central_widget.setStyleSheet(
            "background: qlineargradient(x1:0 y1:0, x2:0 y2:1,"
            " stop:0 #0d1526, stop:0.5 #0a0f1a, stop:1 #070a0f);"
        )

        self.setCentralWidget(central_widget)

        root = QVBoxLayout(central_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ------------------------------------------------
        # TITLE BAR: orb brand, greeting, clock, controls
        # ------------------------------------------------
        self.title_bar = TitleBar(self)
        root.addWidget(self.title_bar)

        # ------------------------------------------------
        # BODY ROW: sidebar | chat (stretch) | system rail
        # ------------------------------------------------
        body = QHBoxLayout()
        body.setContentsMargins(14, 12, 14, 10)
        body.setSpacing(12)

        self.sidebar = Sidebar(on_command=self._send_chip_text)
        body.addWidget(self.sidebar)

        # ------------------------------------------------
        # CENTER COLUMN: hero card + action cards + input bar
        # + chips + chat + big core orb (mockup-exact)
        # ------------------------------------------------
        center = QWidget()
        center.setObjectName("centerPane")
        center.setStyleSheet(
            "QWidget#centerPane { background-color: rgba(8, 14, 26, 190);"
            " border: 1px solid #13233a; border-radius: 18px; }"
        )

        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(18, 14, 18, 12)
        center_layout.setSpacing(10)

        # ------------------------------------------------
        # HERO: greeting + description + helmet art (mockup)
        # ------------------------------------------------
        hero_row = QHBoxLayout()
        hero_row.setSpacing(10)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)

        hero_label = QLabel("JARVIS")
        hero_label.setStyleSheet(
            "color: #7d94b4; font-size: 11px; letter-spacing: 4px;"
            "background: transparent;"
        )

        hero_heading = QLabel(
            '<span style="color:#eaf2ff;">Hey </span>'
            '<span style="color:#a78bfa;">Urav</span>'
        )
        hero_heading.setTextFormat(Qt.RichText)
        hero_heading.setStyleSheet(
            "font-size: 34px; font-weight: 800; background: transparent;"
        )

        hero_body = QLabel(
            "I'm JARVIS, your desktop assistant.\n"
            "Just speak a command — I can open apps,\n"
            "find files, search the web, control your\n"
            "laptop, set reminders and much more."
        )
        hero_body.setWordWrap(True)
        hero_body.setStyleSheet(
            "color: #8fa8c4; font-size: 13px; background: transparent;"
        )

        hero_text.addWidget(hero_label)
        hero_text.addWidget(hero_heading)
        hero_text.addSpacing(4)
        hero_text.addWidget(hero_body)
        hero_text.addStretch(1)

        helmet = QLabel("🤖")
        helmet.setFixedSize(190, 170)
        helmet.setAlignment(Qt.AlignCenter)
        helmet.setStyleSheet(
            "font-size: 92px;"
            "background-color: qradialgradient(cx:0.5 cy:0.45, radius:0.75, "
            "stop:0 rgba(109, 40, 217, 110), stop:0.55 rgba(30, 27, 75, 60), "
            "stop:1 rgba(0, 0, 0, 0));"
            "border-radius: 24px;"
        )

        hero_row.addLayout(hero_text, 1)
        hero_row.addWidget(helmet, 0, Qt.AlignTop)

        # ------------------------------------------------
        # CHAT (scrolling conversation, inside the panel)
        # ------------------------------------------------
        conversation = ConversationView()

        # ------------------------------------------------
        # CHIPS ROW (mockup-exact labels)
        # ------------------------------------------------
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        chips = [
            ("⚡", "Open VS Code", "open vs code"),
            ("🔍", "Search about JEE",
             "search the web for JEE exam pattern and syllabus"),
            ("📄", "Find my notes", "find my physics notes"),
            ("⏰", "Set a reminder", "remind me to drink water at 7 PM"),
            ("🌐", "Open Chrome", "open chrome"),
            ("•••", "More", "what can you do"),
        ]

        for icon, label, command in chips:
            chip = QPushButton(f"{icon}  {label}")
            chip.setObjectName("chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, c=command: self._send_chip_text(c)
            )

            chips_row.addWidget(chip)

        chips_row.addStretch(1)

        # ------------------------------------------------
        # CORE ORB + "Listening..." (bottom of the panel)
        # ------------------------------------------------
        core_row = QHBoxLayout()

        core = JarvisCore()
        core.setMinimumSize(230, 230)
        core.setMaximumSize(250, 250)

        core_row.addStretch(1)
        core_row.addWidget(core)
        core_row.addStretch(1)

        self.status_caption = QLabel("Listening...")
        self.status_caption.setAlignment(Qt.AlignCenter)
        self.status_caption.setStyleSheet(
            "color: #c9d8ee; font-size: 14px; font-weight: 600;"
            "background: transparent;"
        )

        # ------------------------------------------------
        # STACK IT (one panel, mockup-exact)
        # ------------------------------------------------
        center_layout.addLayout(hero_row)
        center_layout.addSpacing(6)
        center_layout.addLayout(chips_row)
        center_layout.addWidget(conversation, 1)
        center_layout.addLayout(core_row)
        center_layout.addWidget(self.status_caption)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        content.addWidget(center, 1)

        self.rail = SystemRail(on_chip=self._send_chip_text)
        content.addWidget(self.rail)

        body.addLayout(content, 1)

        root.addLayout(body, 1)

        # Greeting in the header, mockup-exact.
        self.title_bar.set_greeting(
            "Good Evening, Urav",
            "\u201cJust say the word, I'll handle the rest.\u201d",
        )

        self.core_widget = core
        self.conversation_view = conversation

        # Set once the listener thread has built the orchestrator.
        self.orchestrator = None

        self.overlay = get_overlay()

        self.bridge.user_message.connect(
            conversation.add_user_message
        )

        # User messages also feed the activity rail.
        self.bridge.user_message.connect(self._note_activity)

        self.bridge.jarvis_message.connect(
            conversation.add_jarvis_message
        )

        self.bridge.state_message.connect(self._set_state)

        # ------------------------------------------------
        # GLOBAL HOTKEY: Ctrl+Shift+J toggles the listener mute
        # from anywhere (v2 controllability). Uses a polling timer
        # on GetAsyncKeyState — no extra dependency, works global.
        # ------------------------------------------------
        self._hotkey_state = False

        from PySide6.QtCore import QTimer as _QTimer

        self._hotkey_timer = _QTimer(self)
        self._hotkey_timer.timeout.connect(
            self._poll_global_hotkey
        )
        self._hotkey_timer.start(120)

    def _poll_global_hotkey(self):
        """Ctrl+Shift+J anywhere: mute/unmute the wake-word ear."""

        try:
            import ctypes

            user32 = ctypes.windll.user32

            pressed = (
                user32.GetAsyncKeyState(0x11)  # VK_CONTROL
                and user32.GetAsyncKeyState(0x10)  # VK_SHIFT
                and user32.GetAsyncKeyState(0x4A)  # VK_J
            ) and 0x8000  # currently-down bit

        except Exception:
            return

        if pressed and not self._hotkey_state:
            self._hotkey_state = True
            self._toggle_listener()

        elif not pressed:
            self._hotkey_state = False

    def _toggle_listener(self):
        """Mute/pause/resume the wake-word listener."""

        orchestrator = self.orchestrator

        if orchestrator is None:
            return

        muted = not getattr(orchestrator, "stop_listener_enabled", True)

        orchestrator.stop_listener_enabled = muted

        note = (
            "Ears off, sir. Ctrl+Shift+J brings me back."
            if muted
            else "Ears back on, sir."
        )

        self._note_activity(note)

        if orchestrator.text_to_speech is not None:
            try:
                orchestrator.speak(note)

            except Exception:
                pass

        # ------------------------------------------------
        # SYSTEM TRAY: JARVIS keeps running when closed.
        # ------------------------------------------------
        self.tray = QSystemTrayIcon(_tray_icon_pixmap(), self)

        tray_menu = QMenu()

        show_action = QAction("Show JARVIS", self)

        show_action.triggered.connect(self.show_up)

        tray_menu.addAction(show_action)

        quit_action = QAction("Quit JARVIS", self)

        quit_action.triggered.connect(self.quit_all)

        tray_menu.addAction(quit_action)

        self.tray.setContextMenu(tray_menu)

        self.tray.setToolTip("JARVIS — say 'Hey JARVIS'")

        self.tray.activated.connect(self._tray_activated)

        self.tray.show()

    # ----------------------------------------------------
    # WINDOW BEHAVIOR
    # ----------------------------------------------------

    def show_up(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

        # Window is back on screen: the desktop orb stands down.
        self.overlay.sleep()

    def changeEvent(self, event):
        """
        Taskbar restore / minimize: keep the orb rule exact — the
        desktop orb only lives while the window is hidden or
        minimized AND a task is active. When the window becomes
        visible again, the orb stands down immediately.
        """

        super().changeEvent(event)

        from PySide6.QtCore import QEvent

        if event.type() == QEvent.WindowStateChange:
            if not self.isMinimized() and not self.isHidden():
                self.overlay.sleep()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_up()

    def closeEvent(self, event):
        # Closing the window hides it; JARVIS keeps listening. The
        # desktop orb is NOT woken here — it must only appear during
        # real activity (wake word / running task) while the window
        # is hidden. A fixed wake here made it glow forever.
        event.ignore()
        self.hide()

        self.overlay.sleep()

        self.tray.showMessage(
            "JARVIS is still listening",
            "I'm running in the background. Say 'Hey JARVIS' anytime. "
            "Use the tray icon to reopen or quit.",
            QSystemTrayIcon.Information,
            4000,
        )

    def quit_all(self):
        """
        Tray/menu quit: let the orchestrator say goodbye / stop speech,
        then exit the whole process.
        """

        self.tray.hide()
        self.overlay.sleep()

        if self.orchestrator is not None:
            self.orchestrator.request_shutdown()
            return

        QApplication.quit()

    # ----------------------------------------------------
    # STATE
    # ----------------------------------------------------

    _STATE_META = {
        "IDLE": (
            "#7dd3fc", "Standing by",
            "Say 'Hey JARVIS' to wake me. I keep listening even when "
            "this window is closed.",
        ),
        "LISTENING": (
            "#4ade80", "Listening",
            "I'm all ears — ask me anything.",
        ),
        "THINKING": (
            "#fbbf24", "Thinking",
            "Working out how to do that, sir.",
        ),
        "EXECUTING": (
            "#f472b6", "Executing",
            "On it — running the steps now.",
        ),
        "WAITING_FOR_CONFIRMATION": (
            "#fb923c", "Needs your OK",
            "Say yes to confirm or no to cancel.",
        ),
        "SHUTTING_DOWN": (
            "#f87171", "Shutting down",
            "See you soon, sir.",
        ),
        "SPEAKING": (
            "#38bdf8", "Speaking",
            "Answering out loud.",
        ),
        "DONE": (
            "#4ade80", "Done",
            "Task complete.",
        ),
    }

    # Caption under the orb, mockup-exact position.
    _STATE_CAPTIONS = {
        "IDLE": "Standing by — say 'Hey JARVIS'.",
        "LISTENING": "Listening...",
        "THINKING": "Thinking...",
        "EXECUTING": "On it...",
        "WAITING_FOR_CONFIRMATION": "Say yes or no...",
        "SHUTTING_DOWN": "Powering down...",
        "SPEAKING": "Speaking...",
        "DONE": "Done!",
    }

    def _set_state(self, state: str):
        """Reflect the agent state in caption, rail, core, and orb."""

        # Cross-thread quit request from the listener (safe: this runs
        # on the Qt main thread via the signal).
        if state == "QUIT_APP":
            self.tray.hide()
            self.overlay.sleep()
            QApplication.quit()
            return

        color, title, body = self._STATE_META.get(
            state,
            ("#f87171", state.title(), ""),
        )

        self.title_bar.set_status(state.replace("_", " "), color)

        if hasattr(self, "status_caption"):
            caption = self._STATE_CAPTIONS.get(
                state,
                "Standing by — say 'Hey JARVIS'.",
            )

            self.status_caption.setText(caption)

        if hasattr(self, "rail"):
            self.rail.set_mode(state)
            self.rail.set_agent_status(title, body)

        # Chat typing dots while JARVIS works; gone when done.
        if state in ("THINKING", "EXECUTING"):
            self.conversation_view.show_typing()
        elif state in ("IDLE", "LISTENING"):
            self.conversation_view.hide_typing()

        self.core_widget.set_state_color(color)

        # v2 orb: the state drives the whole animation profile
        # (rings speed, swirl, satellite, waveform, checkmark), not
        # just the color.
        self.core_widget.set_state(state)

        # Waveform + gauges follow the state's color and energy.
        activity = {
            "IDLE": 0.15,
            "LISTENING": 0.55,
            "THINKING": 0.9,
            "EXECUTING": 0.8,
            "WAITING_FOR_CONFIRMATION": 0.45,
            "SHUTTING_DOWN": 0.3,
        }.get(state, 0.3)

        if hasattr(self, "rail"):
            self.rail.set_state_visuals(color, activity)

        # DESKTOP ORB RULE (strict): the orb appears ONLY when BOTH
        # are true — (1) a real activity state is running (not IDLE)
        # and (2) the window is hidden or minimized. Anything else:
        # off. Like before the redesign: wake word or running task =
        # visible; idle = never.
        window_hidden = (
            self.isHidden() or self.isMinimized()
        )

        if state == "IDLE" or not window_hidden:
            self.overlay.sleep()
        else:
            self.overlay.wake(color)

    def _note_activity(self, text):
        """Every user utterance (voice or chip) feeds the rail feed."""

        if hasattr(self, "rail"):
            self.rail.note_command()
            self.rail.add_activity(str(text)[:34])

    def _send_chip_text(self, text: str):
        """A suggestion chip was clicked: run it as if spoken."""

        self.bridge.user_message.emit(text)

        self.conversation_view.show_typing()

        def run():
            try:
                response = self.orchestrator.process(text) if (
                    self.orchestrator is not None
                ) else "I'm still starting up, one moment."

            except Exception:
                response = "Something went wrong running that."

            self.conversation_view.hide_typing()

            self.bridge.jarvis_message.emit(response)

        from threading import Thread as _Thread

        _Thread(target=run, daemon=True).start()


_INSTANCE_PORT = 57654  # Single-instance guard.

_guard_socket = None


def release_instance_guard():
    """Release the single-instance port (used by self-restart)."""

    global _guard_socket

    if _guard_socket is not None:
        try:
            _guard_socket.close()
        except OSError:
            pass

        _guard_socket = None


def main():
    global _guard_socket

    # pythonw has NO stdout at all: every print() (wake-word
    # detections, tool activity, listener errors) vanished. Keep a
    # runtime log — it is how wake-word behavior gets diagnosed.
    # (Applied only when actually running the app, never on import:
    # tests and smoke checks must keep their console output.)
    try:
        _runtime_log = ROOT / "data" / "runtime_log.txt"

        _runtime_log.parent.mkdir(parents=True, exist_ok=True)

        if _runtime_log.exists() and _runtime_log.stat().st_size > 2_000_000:
            _runtime_log.unlink()

        sys.stdout = open(
            _runtime_log,
            "a",
            buffering=1,
            encoding="utf-8",
        )

    except OSError:
        pass

    # ------------------------------------------------
    # SINGLE-INSTANCE GUARD: double-launching (desktop shortcut,
    # startup entry) must never create two listeners.
    # ------------------------------------------------
    import socket

    _guard_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        _guard_socket.bind(("127.0.0.1", _INSTANCE_PORT))

        _guard_socket.listen(1)

    except OSError:
        # Another JARVIS already owns the listener. Tell it to show
        # its window (so double-clicking the shortcut while JARVIS is
        # running brings it to the front instead of doing nothing),
        # then exit hard: sys.exit can hang in interpreter shutdown
        # under pythonw, leaving stray processes.
        try:
            notify = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            notify.settimeout(2)
            notify.connect(("127.0.0.1", _INSTANCE_PORT))
            notify.sendall(b"SHOW")
            notify.close()

        except OSError:
            pass

        os._exit(0)

    app = QApplication(sys.argv)

    app.setQuitOnLastWindowClosed(False)

    bridge = AssistantBridge()

    window = JarvisWindow(bridge)

    # Second-instance protocol: a new launch sends "SHOW" over the
    # guard port; this instance raises its window in response.
    bridge.show_requested.connect(window.show_up)

    def guard_server():
        while True:
            try:
                conn, _addr = _guard_socket.accept()

            except OSError:
                return

            try:
                data = conn.recv(64)

                if data.strip().upper() == b"SHOW":
                    bridge.show_requested.emit()

                conn.close()

            except OSError:
                pass

    Thread(target=guard_server, daemon=True).start()

    # Start always-on: the window is available but JARVIS does not
    # depend on it. Users can close it; the listener keeps running.
    window.show()

    # --------------------------------------------------------
    # DELAYED LISTENER: let the window paint FIRST, then load the
    # heavy audio stack (whisper, piper, openwakeword). Without
    # this delay the window shows blank for ~30 seconds.
    # --------------------------------------------------------
    from PySide6.QtCore import QTimer

    def start_listener():
        def run_assistant():
            # ------------------------------------------------
            # SELF-HEAL: if Orchestrator() raises (a transient file
            # lock, a full disk, a permissions hiccup), a dead
            # listener thread used to mean PERMANENT deafness — the
            # window stayed up but "Hey JARVIS" never worked. Retry
            # with backoff instead of dying.
            # ------------------------------------------------
            orchestrator = None

            for attempt in range(12):
                try:
                    orchestrator = Orchestrator(
                        on_user_message=bridge.user_message.emit,
                        on_jarvis_message=bridge.jarvis_message.emit,
                        on_state_change=bridge.state_message.emit,
                    )

                    break

                except Exception as error:
                    import traceback

                    traceback.print_exc()

                    print(
                        f"Orchestrator init failed "
                        f"(attempt {attempt + 1}): {error}"
                    )

                    time.sleep(5)

            if orchestrator is None:
                print("Orchestrator could not start. Giving up.")

                return

            # Tray quit and self-shutdown/restart need it.
            window.orchestrator = orchestrator

            while True:
                try:
                    # Passively waiting: orb asleep. The cooldown keeps
                    # JARVIS from hearing its own replies ("...just say
                    # 'Hey JARVIS'") and self-waking.
                    bridge.state_message.emit("IDLE")

                    orchestrator.wait_for_wake_word(
                        cooldown=orchestrator.wake_cooldown,
                    )

                    # Wake word detected: orb on for the whole
                    # exchange, including follow-up turns (so a
                    # "please confirm" is answered by just saying
                    # "yes" — no fresh wake word needed).
                    bridge.state_message.emit("LISTENING")

                    # v4: the session machine owns the hold now — no
                    # exchange cap, no 6-second drop. Arguments kept
                    # out for clarity; listen_and_process ignores them.
                    orchestrator.listen_and_process()

                except Exception as error:
                    # NEVER let an exception kill the listener thread:
                    # a dead thread leaves the orb stuck (yellow dot
                    # forever) and JARVIS mute. Log and keep listening.
                    print(f"Listener loop error: {error}")

                    import traceback

                    traceback.print_exc()

                    try:
                        bridge.state_message.emit("IDLE")

                    except Exception:
                        pass

        Thread(target=run_assistant, daemon=True).start()

    QTimer.singleShot(400, start_listener)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
