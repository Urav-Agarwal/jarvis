"""
Canonical capability definitions for JARVIS.

A capability describes the TYPE OF OPERATION a user request requires,
not the specific tool that will execute it. The capability router
(router/capability_router_v2.py) classifies requests into these
capabilities; tool selection happens later, in the agent/planner layer.

Routing logic does NOT belong in this module.
"""

# ============================================================
# CAPABILITY DEFINITIONS
# ============================================================

CAPABILITIES = {
    "application": {
        "description": (
            "Launch, open, close, switch to, or bring up desktop "
            "applications."
        ),
        "examples": [
            "open VS Code",
            "launch Chrome",
            "close Spotify",
            "bring Calculator to the front",
        ],
    },

    "browser": {
        "description": (
            "Interact with a web browser or webpage: navigation, webpage "
            "interaction, reading webpage content, browser-specific "
            "actions, and named-website interaction."
        ),
        "examples": [
            "go to YouTube in Chrome",
            "click the search button on a webpage",
            "navigate back",
            "read the webpage",
        ],
    },

    "computer": {
        "description": (
            "Generic mouse and keyboard interaction with ordinary desktop "
            "applications. Only used when the user explicitly requests "
            "that interaction, never because another capability uses "
            "mouse/keyboard internally."
        ),
        "examples": [
            "move the mouse",
            "click a desktop button",
            "type hello",
            "press Enter",
            "scroll down",
        ],
    },

    "filesystem": {
        "description": (
            "File and folder operations: find, locate, read, create, "
            "copy, move, rename, delete, inspect, and access."
        ),
        "examples": [
            "find my physics notes",
            "read notes.txt",
            "move this file",
            "open the folder containing my project",
        ],
    },

    "screen": {
        "description": (
            "Visual inspection of what is currently displayed on the "
            "screen: screenshots, visible content, and appearance."
        ),
        "examples": [
            "take a screenshot",
            "what is visible on my screen?",
            "what does this look like?",
        ],
    },

    "web": {
        "description": (
            "Retrieve information from the internet without requiring "
            "browser UI control: online search, research, news, facts, "
            "and documentation retrieval."
        ),
        "examples": [
            "search the internet for the latest Python release",
            "find information about the James Webb Telescope",
        ],
    },

    "system": {
        "description": (
            "Operating-system and hardware control or information: "
            "volume, brightness, battery, CPU, RAM, storage, network, "
            "Wi-Fi, Bluetooth, lock, sleep, restart, shutdown."
        ),
        "examples": [
            "set volume to 40%",
            "check battery",
            "how much RAM am I using?",
            "turn Bluetooth on",
        ],
    },

    "memory": {
        "description": (
            "Persistent user information: remember, recall, update, and "
            "forget. Not the same as saved workflows."
        ),
        "examples": [
            "remember that I prefer dark mode",
            "what do you remember about my projects?",
            "forget my old preference",
        ],
    },

    "skill": {
        "description": (
            "Reusable JARVIS skills/workflows: discover, create, "
            "validate, run, and manage saved routines. Only involved "
            "when the user explicitly refers to a reusable or saved "
            "workflow."
        ),
        "examples": [
            "create a morning study routine",
            "run my saved study routine",
        ],
    },
}

# Canonical, deterministic ordering for the final capability list.
CAPABILITY_ORDER = [
    "application",
    "browser",
    "computer",
    "filesystem",
    "screen",
    "web",
    "system",
    "memory",
    "skill",
]

# Convenience tuple of all capability names (canonical order).
CAPABILITY_NAMES = tuple(CAPABILITY_ORDER)


# ============================================================
# HELPERS
# ============================================================

def get_capability_names() -> list:
    """Return all capability names in canonical order."""
    return list(CAPABILITY_ORDER)


def get_capability(name) -> dict:
    """Return the definition for a capability, or None if unknown."""
    return CAPABILITIES.get(name)


def is_valid_capability(name) -> bool:
    """Return True if name is a known capability."""
    return name in CAPABILITIES


def validate_capabilities(capabilities) -> list:
    """
    Validate, deduplicate, and order a capability list.

    - Unknown capability names are rejected.
    - Duplicates are removed.
    - The canonical order is preserved.
    """
    seen = set()
    validated = []

    for capability in capabilities:
        if not isinstance(capability, str):
            continue

        if not is_valid_capability(capability):
            continue

        if capability in seen:
            continue

        seen.add(capability)
        validated.append(capability)

    return sorted(validated, key=CAPABILITY_ORDER.index)


# ============================================================
# LEGACY: INTENT-LEVEL REGISTRY
# ============================================================
#
# The IntentEngine (assistant/intent_engine.py) still classifies
# requests into legacy intent-level capabilities such as
# "lock_laptop" or "volume_up". That registry lives here until the
# intent system is retired; it is NOT the capability model above.

class CapabilityRegistry:
    def __init__(self):
        self.capabilities = {
            "lock_laptop": {
                "description": "Lock the Windows laptop.",
                "risk": "high",
                "confirmation_required": True,
            },

            "sleep_laptop": {
                "description": "Put the Windows laptop to sleep.",
                "risk": "high",
                "confirmation_required": True,
            },

            "restart_laptop": {
                "description": "Restart the Windows laptop.",
                "risk": "high",
                "confirmation_required": True,
            },

            "shutdown_laptop": {
                "description": "Shut down the Windows laptop.",
                "risk": "high",
                "confirmation_required": True,
            },

            "volume_up": {
                "description": "Increase the system volume.",
                "risk": "low",
                "confirmation_required": False,
            },

            "volume_down": {
                "description": "Decrease the system volume.",
                "risk": "low",
                "confirmation_required": False,
            },

            "set_volume": {
                "description": "Set the system volume to a percentage.",
                "risk": "low",
                "confirmation_required": False,
            },

            "volume_mute": {
                "description": "Mute system audio.",
                "risk": "low",
                "confirmation_required": False,
            },

            "volume_unmute": {
                "description": "Unmute system audio.",
                "risk": "low",
                "confirmation_required": False,
            },

            "open_application": {
                "description": "Open an installed application.",
                "risk": "low",
                "confirmation_required": False,
            },

            "open_browser": {
                "description": (
                    "Open an installed web browser, optionally using a "
                    "specific browser profile."
                ),
                "risk": "low",
                "confirmation_required": False,
            },

            "open_browser_profile": {
                "description": (
                    "Open an installed web browser using a specific "
                    "browser profile."
                ),
                "risk": "low",
                "confirmation_required": False,
            },

            "take_screenshot": {
                "description": "Capture an image of the current screen.",
                "risk": "low",
                "confirmation_required": False,
            },
        }

    def exists(self, capability_name) -> bool:
        return capability_name in self.capabilities

    def get(self, capability_name):
        return self.capabilities.get(capability_name)

    def all(self):
        return self.capabilities.copy()


class LegacyKeywordRouter:
    """
    LEGACY keyword-based category detector (was CapabilityRouter).

    Kept only for backward compatibility. The hybrid router in
    router/capability_router_v2.py supersedes this class.
    """

    CATEGORY_KEYWORDS = {
        "computer": {
            "mouse", "cursor", "click", "scroll", "keyboard", "type",
            "press", "key", "active window", "running apps",
            "running applications",
        },

        "application": {
            "open app", "open application", "launch app",
            "launch application", "start app", "start application",
            "close app", "close application", "quit app",
            "quit application", "application", "app",
        },

        "browser": {
            "browser", "chrome", "comet", "edge", "opera", "opera gx",
            "firefox", "youtube", "website", "webpage", "url", "tab",
            "navigate", "search online",
        },

        "filesystem": {
            "file", "files", "folder", "folders", "directory",
            "directories", "document", "documents", "pdf", "notes",
            "resume", "delete file", "delete folder", "copy file",
            "move file", "read file", "open file",
        },

        "system": {
            "volume", "sound", "mute", "brightness", "battery", "cpu",
            "processor", "ram", "memory", "storage", "disk", "wifi",
            "wi-fi", "bluetooth", "network", "restart", "shutdown",
            "shut down", "sleep", "lock laptop", "lock computer",
        },

        "screen": {
            "screenshot", "screen", "what is on my screen",
            "look at my screen", "analyze my screen",
        },

        "web": {
            "web search", "search the web", "internet search",
            "search online", "fetch webpage",
        },

        "memory": {
            "remember", "remember this", "recall",
            "what did i tell you", "forget",
        },

        "skill": {
            "skill", "workflow", "routine",
        },
    }

    def detect(self, user_input) -> list:
        """Return relevant capability categories for a user request."""
        text = user_input.lower().strip()

        if not text:
            return []

        detected = []

        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    detected.append(category)
                    break

        return detected


# Backward-compatible alias for existing imports.
CapabilityRouter = LegacyKeywordRouter


if __name__ == "__main__":
    registry = CapabilityRegistry()

    print("CAPABILITIES:")

    for name, capability in CAPABILITIES.items():
        print(f"- {name}: {capability['description']}")

    print()
    print("LEGACY INTENT CAPABILITIES:")

    for name, capability in registry.all().items():
        print(
            f"- {name}: "
            f"{capability['description']} "
            f"[risk={capability['risk']}]"
        )
