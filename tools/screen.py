from io import BytesIO
import win32clipboard
from PIL import ImageGrab



class ScreenController:
    def take_screenshot(self):
        screenshot = ImageGrab.grab()

        # Copy screenshot directly to Windows clipboard
        output = BytesIO()
        screenshot.convert("RGB").save(output, "BMP")

        bmp_data = output.getvalue()[14:]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(
                win32clipboard.CF_DIB,
                bmp_data,
            )
        finally:
            win32clipboard.CloseClipboard()

        return "Screenshot copied to clipboard."


if __name__ == "__main__":
    controller = ScreenController()

    result = controller.take_screenshot()

    print(result)