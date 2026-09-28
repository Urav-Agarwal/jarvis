import re
import winreg


class BrowserDetector:
    REGISTRY_PATH = r"SOFTWARE\Clients\StartMenuInternet"

    def discover_browsers(self):
        browsers = {}

        registry_locations = [
            winreg.HKEY_LOCAL_MACHINE,
            winreg.HKEY_CURRENT_USER,
        ]

        for root in registry_locations:
            try:
                with winreg.OpenKey(
                    root,
                    self.REGISTRY_PATH,
                ) as registry_key:

                    index = 0

                    while True:
                        try:
                            browser_name = winreg.EnumKey(
                                registry_key,
                                index,
                            )

                            index += 1

                            executable = self._get_executable(
                                root,
                                browser_name,
                            )

                            if executable:
                                key = browser_name.lower()

                                browsers[key] = {
                                    "name": browser_name,
                                    "executable": executable,
                                }

                        except OSError:
                            break

            except OSError:
                continue

        return browsers

    def _get_executable(self, root, browser_name):
        command_path = (
            self.REGISTRY_PATH
            + "\\"
            + browser_name
            + r"\shell\open\command"
        )

        try:
            with winreg.OpenKey(
                root,
                command_path,
            ) as command_key:

                command, _ = winreg.QueryValueEx(
                    command_key,
                    "",
                )

        except OSError:
            return None

        return self._extract_executable(command)

    def _extract_executable(self, command):
        command = command.strip()

        match = re.match(
            r'^"([^"]+\.exe)"',
            command,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

        match = re.search(
            r'(.+?\.exe)(?:\s|$)',
            command,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

        return None


if __name__ == "__main__":
    detector = BrowserDetector()

    browsers = detector.discover_browsers()

    print("BROWSER DISCOVERY READY")
    print()
    print(f"Browsers found: {len(browsers)}")
    print()

    for browser in sorted(
        browsers.values(),
        key=lambda item: item["name"].lower(),
    ):
        print(
            f"- {browser['name']} -> "
            f"{browser['executable']}"
        )