import socket
import subprocess
import time

import psutil


class SystemObserver:
    """Collect read-only information about the Windows computer."""

    def get_cpu(self):
        return {
            "success": True,
            "usage_percent": psutil.cpu_percent(interval=0.5),
            "cores": psutil.cpu_count(logical=False),
            "logical_processors": psutil.cpu_count(logical=True),
        }

    def get_memory(self):
        memory = psutil.virtual_memory()

        return {
            "success": True,
            "usage_percent": memory.percent,
            "total": self._format_bytes(memory.total),
            "used": self._format_bytes(memory.used),
            "available": self._format_bytes(memory.available),
        }

    def get_storage(self):
        partitions = []

        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)

                partitions.append({
                    "drive": partition.mountpoint,
                    "total": self._format_bytes(usage.total),
                    "used": self._format_bytes(usage.used),
                    "free": self._format_bytes(usage.free),
                    "usage_percent": usage.percent,
                })
            except (PermissionError, OSError):
                continue

        return {
            "success": True,
            "partitions": partitions,
        }

    def get_battery(self):
        battery = psutil.sensors_battery()

        if battery is None:
            return {
                "success": True,
                "available": False,
                "message": "Battery information is not available.",
            }

        return {
            "success": True,
            "available": True,
            "percent": battery.percent,
            "plugged_in": battery.power_plugged,
            "seconds_remaining": (
                battery.secsleft
                if battery.secsleft != psutil.POWER_TIME_UNLIMITED
                else None
            ),
        }

    def get_network(self):
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
        except OSError:
            hostname = socket.gethostname()
            local_ip = None

        connections = psutil.net_connections(kind="inet")

        established = sum(
            1
            for connection in connections
            if connection.status == psutil.CONN_ESTABLISHED
        )

        return {
            "success": True,
            "hostname": hostname,
            "local_ip": local_ip,
            "active_connections": established,
        }

    def get_wifi(self):
        try:
            result = subprocess.run(
                [
                    "netsh",
                    "wlan",
                    "show",
                    "interfaces",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": "Could not read Wi-Fi information.",
                }

            details = self._parse_netsh_wifi(result.stdout)

            return {
                "success": True,
                "connected": details.get("state", "").lower() == "connected",
                "details": self._parse_netsh_wifi(result.stdout),
            }

        except (OSError, subprocess.SubprocessError) as error:
            return {
                "success": False,
                "error": str(error),
            }

    def get_wifi_speed(self):
        try:
            result = subprocess.run(
                [
                    "netsh",
                    "wlan",
                    "show",
                    "interfaces",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": "Could not read Wi-Fi speed.",
                }

            details = self._parse_netsh_wifi(result.stdout)

            return {
                "success": True,
                "receive_speed": details.get("receive_rate"),
                "transmit_speed": details.get("transmit_rate"),
            }

        except (OSError, subprocess.SubprocessError) as error:
            return {
                "success": False,
                "error": str(error),
            }

    def get_bluetooth(self):
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-PnpDevice -Class Bluetooth | "
                    "Select-Object Status, FriendlyName | "
                    "ConvertTo-Json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": "Could not read Bluetooth information.",
                }

            output = result.stdout.strip()

            if not output:
                return {
                    "success": True,
                    "available": False,
                    "devices": [],
                }

            return {
                "success": True,
                "available": True,
                "raw": output,
            }

        except (OSError, subprocess.SubprocessError) as error:
            return {
                "success": False,
                "error": str(error),
            }

    def get_gpu(self):
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Counter "
                    "'\\GPU Engine(*)\\Utilization Percentage' "
                    "-ErrorAction SilentlyContinue | "
                    "Select-Object -ExpandProperty CounterSamples | "
                    "Select-Object InstanceName,CookedValue | "
                    "ConvertTo-Json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "error": "Could not read GPU information.",
                }

            output = result.stdout.strip()

            if not output:
                return {
                    "success": True,
                    "usage_percent": 0.0,
                }

            import json

            data = json.loads(output)

            if isinstance(data, dict):
                data = [data]

            values = []

            for item in data:
                try:
                    value = float(item.get("CookedValue", 0))
                    values.append(value)
                except (TypeError, ValueError):
                    continue

            usage = max(values) if values else 0.0

            return {
                "success": True,
                "usage_percent": round(usage, 2),
            }

        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            return {
                "success": False,
                "error": str(error),
            }

    def get_laptop_state(self):
        return {
            "success": True,
            "cpu": self.get_cpu(),
            "memory": self.get_memory(),
            "battery": self.get_battery(),
            "network": self.get_network(),
        }

    def _parse_netsh_wifi(self, output):
        details = {}

        for line in output.splitlines():
            if ":" not in line:
                continue

            key, value = line.split(":", 1)

            key = key.strip().lower()
            value = value.strip()

            if key == "state":
                details["state"] = value

            elif key == "ssid":
                details["ssid"] = value

            elif key == "band":
                details["band"] = value

            elif key == "channel":
                details["channel"] = value

            elif key == "radio type":
                details["radio_type"] = value

            elif key == "receive rate (mbps)":
                details["receive_rate"] = value

            elif key == "transmit rate (mbps)":
                details["transmit_rate"] = value

            elif key == "signal":
                details["signal"] = value

            elif key == "rssi":
                details["rssi"] = value

            elif key == "profile":
                details["profile"] = value

        return details

    def _format_bytes(self, value):
        units = ["B", "KB", "MB", "GB", "TB"]

        size = float(value)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.2f} {unit}"

            size /= 1024