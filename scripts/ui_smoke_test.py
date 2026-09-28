import sys
import traceback

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))

try:
    print("STEP: import PySide6", flush=True)
    from PySide6.QtWidgets import QApplication

    print("STEP: import app.main", flush=True)
    from app.main import AssistantBridge, JarvisWindow

    print("STEP: create QApplication", flush=True)
    app = QApplication([])

    print("STEP: create window", flush=True)
    window = JarvisWindow(AssistantBridge())

    print("STEP: show", flush=True)
    window.show()
    app.processEvents()

    print("STEP: grab pixels", flush=True)
    pix = window.grab()
    img = pix.toImage()

    colors = set()
    for x in range(0, img.width(), 20):
        for y in range(0, img.height(), 20):
            colors.add(img.pixel(x, y))

    print("RESULT_COLORS:", len(colors), flush=True)

    print("STEP: state sweep", flush=True)
    for state in ["LISTENING", "THINKING", "IDLE"]:
        window.bridge.state_message.emit(state)
        app.processEvents()

    print("SMOKE_OK", flush=True)

except BaseException:
    traceback.print_exc()
    print("SMOKE_FAILED", flush=True)
