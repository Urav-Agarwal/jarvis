from tools.browser_detector import BrowserDetector
from tools.profiles import (
    UserDataDirectoryFinder,
    ChromiumProfileResolver,
)


class BrowserManager:
    def __init__(self):
        self.detector = BrowserDetector()
        self.user_data_finder = UserDataDirectoryFinder()
        self.profile_resolver = ChromiumProfileResolver()

        self.browsers = {}

        self.refresh_browsers()

    def refresh_browsers(self):
        self.browsers = self.detector.discover_browsers()

    def find_browser(self, name: str):
        requested = name.lower().strip()

        if requested in self.browsers:
            return self.browsers[requested]

        matches = [
            browser
            for browser_name, browser in self.browsers.items()
            if requested in browser_name
            or browser_name in requested
        ]

        if len(matches) == 1:
            return matches[0]

        return None

    def get_profiles(self, browser_name: str):
        browser = self.find_browser(browser_name)

        if browser is None:
            return []

        user_data_directory = (
            self.user_data_finder.find_for_browser(
                browser["name"],
                browser["executable"],
            )
        )

        if user_data_directory is None:
            return []

        return self.profile_resolver.discover_profiles(
            user_data_directory
        )

    def open_browser(self, name: str, profile_name=None):
        browser = self.find_browser(name)

        if browser is None:
            return False

        command = [browser["executable"]]

        if profile_name:
            profiles = self.get_profiles(name)

            profile = self.profile_resolver.resolve_profile(
                profiles,
                profile_name,
            )

            if profile is None:
                return False

            command.append(
                f"--profile-directory={profile.directory}"
            )

        try:
            import subprocess
            subprocess.Popen(command)
            return True
        except OSError:
            return False

    def get_browser_state(self, name: str):
        from tools.computer_observer import ComputerObserver

        browser = self.find_browser(name)

        if browser is None:
            return {
                "success": False,
                "error": f"Browser '{name}' was not found on this computer.",
            }

        executable = browser["executable"]
        executable_name = executable.rsplit("\\", 1)[-1].lower()

        observer = ComputerObserver()
        result = observer.get_running_applications()

        if not result.get("success"):
            return result

        matches = []

        for application in result.get("applications", []):
            process_name = application.get("name", "").lower()

            if process_name == executable_name:
                matches.append(application)

        return {
            "success": True,
            "browser": browser["name"],
            "running": bool(matches),
            "matches": matches,
        }


if __name__ == "__main__":
    manager = BrowserManager()

    print("BROWSER MANAGER READY")
    print()

    print(
        f"Browsers found: "
        f"{len(manager.browsers)}"
    )

    print()

    for name, browser in sorted(
        manager.browsers.items()
    ):
        print(
            f"- {browser['name']} -> "
            f"{browser['executable']}"
        )

    print()
    print("PROFILE TEST")
    print()

    for profile in manager.get_profiles("Chrome"):
        print(
            f"- {profile.name} -> {profile.directory}"
        )