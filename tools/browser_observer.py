from pathlib import Path

from tools.profiles import UserDataDirectoryFinder
from tools.browser_detector import BrowserDetector


class BrowserObserver:
    def __init__(self):
        self.detector = BrowserDetector()
        self.user_data_finder = UserDataDirectoryFinder()

    def inspect_browser(self, browser_name: str):
        browser = self._find_browser(browser_name)

        if browser is None:
            return {
                "success": False,
                "error": f"Browser '{browser_name}' was not found.",
            }

        user_data_directory = self.user_data_finder.find_for_browser(
            browser["name"],
            browser["executable"],
        )

        if user_data_directory is None:
            return {
                "success": False,
                "error": f"Could not locate the profile data for {browser['name']}.",
            }

        user_data_directory = Path(user_data_directory)

        return {
            "success": True,
            "browser": browser["name"],
            "executable": browser["executable"],
            "user_data_directory": str(user_data_directory),
            "files": self._list_relevant_files(user_data_directory),
        }

    def _find_browser(self, name: str):
        browsers = self.detector.discover_browsers()
        requested = name.lower().strip()

        if requested in browsers:
            return browsers[requested]

        matches = [
            browser
            for browser_name, browser in browsers.items()
            if requested in browser_name
            or browser_name in requested
        ]

        if len(matches) == 1:
            return matches[0]

        return None

    def _list_relevant_files(self, user_data_directory: Path):
        relevant_names = {
            "Local State",
            "History",
            "Current Session",
            "Current Tabs",
            "Last Session",
            "Last Tabs",
        }

        found = []

        for path in user_data_directory.rglob("*"):
            if not path.is_file():
                continue

            if path.name in relevant_names:
                found.append(str(path))

        return found