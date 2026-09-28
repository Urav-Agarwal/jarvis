from tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self):
        self.tools = ToolRegistry()

    def execute(self, tool_name: str, parameters: dict):
        if tool_name == "browser.open":
            browser = parameters.get("browser")
            profile = parameters.get("profile")

            if not browser:
                return {
                    "success": False,
                    "result": "Browser name is required.",
                }

            success = self.tools.open_browser(browser, profile)

            if success:
                return {
                    "success": True,
                    "result": f"Opened {browser}.",
                }

            return {
                "success": False,
                "result": f"Could not open {browser}.",
            }

        if tool_name == "screen.screenshot":
            result = self.tools.take_screenshot()

            return {
                "success": True,
                "result": result,
            }

        return {
            "success": False,
            "result": f"Unknown tool: {tool_name}",
        }