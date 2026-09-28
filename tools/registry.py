from tools.applications import ApplicationManager
from tools.system import SystemController
from tools.screen import ScreenController
from security.confirmations import ConfirmationManager
from tools.browsers import BrowserManager



class ToolRegistry:
    def __init__(self):
        self.applications = ApplicationManager()
        self.system = SystemController()
        self.confirmations = ConfirmationManager()
        self.screen = ScreenController()
        self.browsers = BrowserManager()

    def take_screenshot(self):
        return self.screen.take_screenshot()

    def open_application(self, name: str) -> bool:
        return self.applications.open_application(name)

    def open_browser(self, name: str, profile_name=None):
        return self.browsers.open_browser(
            name,
            profile_name,
        )

    def get_volume(self):
        return self.system.get_volume()

    def set_volume(self, percentage):
        return self.system.set_volume(percentage)

    def increase_volume(self, amount=10):
        return self.system.increase_volume(amount)

    def decrease_volume(self, amount=10):
        return self.system.decrease_volume(amount)

    def mute(self):
        return self.system.mute()

    def unmute(self):
        return self.system.unmute()

    def get_brightness(self):
        return self.system.get_brightness()

    def set_brightness(self, percentage):
        return self.system.set_brightness(percentage)

    def increase_brightness(self, amount=10):
        return self.system.increase_brightness(amount)

    def decrease_brightness(self, amount=10):
        return self.system.decrease_brightness(amount)

    def battery_status(self):
        return self.system.battery_status()

    def uptime(self):
        return self.system.uptime()

    def wifi_status(self):
        return self.system.wifi_status()

    def bluetooth_status(self):
        return self.system.bluetooth_status()

    def network_info(self):
        return self.system.network_info()

    def lock(self):
        return self.system.lock()

    def sleep(self):
        return self.system.sleep()


if __name__ == "__main__":
    registry = ToolRegistry()

    print("TOOL REGISTRY READY")
    print("Available applications:", registry.applications.applications)
    print("Volume:", registry.get_volume(), "%")
    print("Brightness:", registry.get_brightness(), "%")
    print(registry.take_screenshot())
    print(registry.battery_status())
    print(registry.uptime())
    print(registry.wifi_status())
    print(registry.bluetooth_status())
    print(registry.network_info())