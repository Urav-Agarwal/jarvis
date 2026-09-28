import subprocess
import time
import socket

import psutil
import screen_brightness_control as sbc

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from comtypes import CLSCTX_ALL


class SystemController:
    def __init__(self):
        self.volume = self._get_volume_controller()

    def _get_volume_controller(self):
        device = AudioUtilities.GetSpeakers()

        return device.EndpointVolume

    # -------------------------
    # VOLUME
    # -------------------------

    def get_volume(self):
        return round(self.volume.GetMasterVolumeLevelScalar() * 100)

    def set_volume(self, percentage):
        percentage = max(0, min(100, int(percentage)))

        self.volume.SetMasterVolumeLevelScalar(
            percentage / 100,
            None,
        )

        return f"Volume set to {percentage}%."

    def increase_volume(self, amount=10):
        new_volume = min(100, self.get_volume() + amount)

        self.volume.SetMasterVolumeLevelScalar(
            new_volume / 100,
            None,
        )

        return f"Volume increased to {new_volume}%."

    def decrease_volume(self, amount=10):
        new_volume = max(0, self.get_volume() - amount)

        self.volume.SetMasterVolumeLevelScalar(
            new_volume / 100,
            None,
        )

        return f"Volume decreased to {new_volume}%."

    def mute(self):
        self.volume.SetMute(1, None)
        return "Volume muted."

    def unmute(self):
        self.volume.SetMute(0, None)
        return "Volume unmuted."

    # -------------------------
    # PER-APPLICATION VOLUME
    # (Windows Volume Mixer: lets "increase the volume of the YouTube
    # video" target one app's session instead of the master volume.)
    # -------------------------

    @staticmethod
    def _find_app_session(app_name: str):
        """Find a Windows audio session whose process matches app_name."""

        from pycaw.pycaw import AudioUtilities

        requested = app_name.lower().strip().removesuffix(".exe")

        if not requested:
            return None, None

        sessions = AudioUtilities.GetAllSessions()

        for session in sessions:
            process = getattr(session, "Process", None)

            if process is None:
                continue

            process_name = (
                process.name() or ""
            ).lower().removesuffix(".exe")

            if requested in process_name or process_name in requested:
                return session, process_name

        return None, None

    def get_app_volume(self, app_name: str):
        session, process_name = self._find_app_volume_session(app_name)

        if session is None:
            return {
                "success": False,
                "error": (
                    f"No audio is playing from {app_name} right now, "
                    "so I can't adjust its volume."
                ),
            }

        volume = round(session.SimpleAudioVolume.GetMasterVolume() * 100)

        return {
            "success": True,
            "application": process_name,
            "volume_percent": volume,
            "message": (
                f"{process_name} volume is at {volume} percent."
            ),
        }

    # Alias kept for clarity at call sites.
    _find_app_volume_session = _find_app_session

    def set_app_volume(self, app_name: str, percentage: int):
        percentage = max(0, min(100, int(percentage)))

        session, process_name = self._find_app_volume_session(app_name)

        if session is None:
            return {
                "success": False,
                "error": (
                    f"No audio is playing from {app_name} right now, "
                    "so I can't adjust its volume."
                ),
            }

        session.SimpleAudioVolume.SetMasterVolume(
            percentage / 100,
            None,
        )

        return (
            f"{process_name} volume set to {percentage} percent. "
            "Your overall system volume is unchanged."
        )

    def adjust_app_volume(self, app_name: str, delta: int):
        current = self.get_app_volume(app_name)

        if not current.get("success"):
            return current

        new_value = max(
            0,
            min(
                100,
                int(current.get("volume_percent", 0)) + delta,
            ),
        )

        return self.set_app_volume(app_name, new_value)

    # -------------------------
    # BRIGHTNESS
    # -------------------------

    def get_brightness(self):
        values = sbc.get_brightness()

        if isinstance(values, list):
            return round(values[0])

        return round(values)

    def set_brightness(self, percentage):
        percentage = max(0, min(100, int(percentage)))

        sbc.set_brightness(percentage)

        return f"Brightness set to {percentage}%."

    def increase_brightness(self, amount=10):
        new_brightness = min(100, self.get_brightness() + amount)

        sbc.set_brightness(new_brightness)

        return f"Brightness increased to {new_brightness}%."

    def decrease_brightness(self, amount=10):
        new_brightness = max(0, self.get_brightness() - amount)

        sbc.set_brightness(new_brightness)

        return f"Brightness decreased to {new_brightness}%."

    # -------------------------
    # BATTERY
    # -------------------------

    def battery_status(self):
        battery = psutil.sensors_battery()

        if battery is None:
            return "Battery information is unavailable."

        percentage = round(battery.percent)

        if battery.power_plugged:
            return f"Battery is at {percentage}% and the laptop is charging."

        return f"Battery is at {percentage}%."

    # -------------------------
    # LOCK
    # -------------------------

    def lock(self):
        subprocess.run(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            check=False,
        )

        return "Locking the laptop."

    # -------------------------
    # SLEEP
    # -------------------------

    def sleep(self):
        subprocess.run(
            [
                "powershell",
                "-Command",
                "Start-Sleep -Seconds 1; Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"
            ],
            check=False,
        )

        return "Putting the laptop to sleep."

    # -------------------------
    # RESTART
    # -------------------------

    def restart(self):
        subprocess.run(
            ["shutdown", "/r", "/t", "5"],
            check=False,
        )

        return "The laptop will restart in 5 seconds."

    # -------------------------
    # SHUTDOWN
    # -------------------------

    def shutdown(self):
        subprocess.run(
            ["shutdown", "/s", "/t", "5"],
            check=False,
        )

        return "The laptop will shut down in 5 seconds."

    # -------------------------
    # SYSTEM INFO
    # -------------------------

    def uptime(self):
        seconds = time.time() - psutil.boot_time()

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)

        return f"The laptop has been running for {hours} hours and {minutes} minutes."

    def wifi_status(self):
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            check=False,
        )

        output = result.stdout

        if "State" in output and "connected" in output.lower():
            for line in output.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    ssid = line.split(":", 1)[1].strip()
                    return f"Wi-Fi is connected to {ssid}."

            return "Wi-Fi is connected."

        return "Wi-Fi is disconnected."

    def bluetooth_status(self):
        result = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-PnpDevice -Class Bluetooth | "
                "Where-Object {$_.Status -eq 'OK'} | "
                "Select-Object -First 1"
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            return "Bluetooth is available and enabled."

        return "Bluetooth is unavailable or disabled."

    def network_info(self):
        hostname = socket.gethostname()

        try:
            ip_address = socket.gethostbyname(hostname)
        except socket.gaierror:
            ip_address = "unavailable"

        return f"Hostname is {hostname}. Local IP address is {ip_address}."

if __name__ == "__main__":
    controller = SystemController()

    print("SYSTEM CONTROLLER READY")

    print("Volume:", controller.get_volume(), "%")
    print("Brightness:", controller.get_brightness(), "%")
    print(controller.battery_status())
    print(controller.uptime())