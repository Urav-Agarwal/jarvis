import json
from tools.capabilities import CapabilityRegistry
from tools.browsers import BrowserManager

class IntentEngine:
    def __init__(self, ai_provider):
        self.ai = ai_provider
        self.capabilities = CapabilityRegistry()
        self.browsers = BrowserManager()

    def parse(self, user_input: str):
        capabilities = self.capabilities.all()

        capability_text = "\n".join(
            f"- {name}: {data['description']}"
            for name, data in capabilities.items()
        )

        prompt = f"""
    You are the intent engine for JARVIS, a Windows desktop voice assistant.

    Your job is to understand what the user wants and determine whether
    their request matches one of JARVIS's available capabilities.

    AVAILABLE CAPABILITIES:

    {capability_text}

    IMPORTANT RULES:

    1. Understand natural language.
    2. Different words and phrases can mean the same thing.
    3. Do not require the user to use the exact capability name.
    4. If the user's request clearly matches a capability, return that capability.
    5. If the request does not match any available capability, return "unknown".
    6. Never invent a capability that is not listed above.
    7. Return ONLY valid JSON.
    8. Do not use Markdown.
    9. Do not explain your answer.

    For open_application:

    - Extract the name of the application the user wants to open.
    - Preserve the application name as naturally as possible.
    - Return it using the "application" field.

    For open_browser:

    - Extract the name of the browser the user wants to open.
    - Return it using the "browser" field.
    - If the user does not specify a profile, do not include a profile field.

    For open_browser_profile:

    - Extract the name of the browser.
    - Extract the requested profile or profile alias.
    - Return the browser using the "browser" field.
    - Return the requested profile using the "profile" field.
    - The profile may be an actual discovered profile name such as "School" or "malti".
    - It may also be an alias such as "personal", "default", "main", or "my profile".
    - Do not invent profile names.

    Examples:

    {{"intent": "open_browser", "browser": "Google Chrome"}}

    {{"intent": "open_browser_profile", "browser": "Google Chrome", "profile": "School"}}

    {{"intent": "open_browser_profile", "browser": "Chrome", "profile": "personal"}}

    {{"intent": "open_browser_profile", "browser": "Comet", "profile": "School account"}}

    Example:

    {{"intent": "open_application", "application": "Google Chrome"}}

    For capabilities that require an amount or percentage:

    - volume_up:
    Extract the requested percentage.
    If no amount is given, use 10.

    - volume_down:
    Extract the requested percentage.
    If no amount is given, use 10.

    - set_volume:
    Extract the requested percentage.
    "maximum", "max", or "full" means 100.
    "minimum", "min", "zero", or "silent" means 0.

    JSON examples:

    {{"intent": "lock_laptop"}}

    {{"intent": "volume_up", "amount": 20}}

    {{"intent": "volume_down", "amount": 10}}

    {{"intent": "set_volume", "amount": 50}}

    {{"intent": "volume_mute"}}

    {{"intent": "volume_unmute"}}

    {{"intent": "unknown"}}

    {{"intent": "open_browser", "browser": "Google Chrome"}}
    {{"intent": "open_browser_profile", "browser": "Google Chrome", "profile": "School"}}
    {{"intent": "open_browser_profile", "browser": "Google Chrome", "profile": "personal"}}

    User request:
    {user_input}
    """

        response = self.ai.generate(prompt)

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            return {"intent": "unknown"}

        intent = result.get("intent")

        if intent != "unknown" and not self.capabilities.exists(intent):
            return {"intent": "unknown"}

        return result
    