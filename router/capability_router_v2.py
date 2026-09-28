"""
JARVIS Hybrid Capability Router V2

Routes user requests to the capabilities required to fulfill them.

Strategy:
1. The request is split into clauses and analyzed by operations,
   not raw keywords.
2. Deterministic rules handle operations that are unambiguous.
3. If ANY clause carries a capability signal that deterministic rules
   cannot confidently resolve, the whole request falls back to the
   semantic (LLM) classifier. A partial guess is never returned.
4. Results are validated against the canonical capability definitions
   in tools/capabilities.py before being returned.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from tools.capabilities import (
    CAPABILITY_NAMES,
    validate_capabilities,
)
from ai.provider import GroqProvider


# ============================================================
# WORD LISTS
# ============================================================

_APPLICATION_TARGETS = [
    "vscode", "vs code", "visual studio code",
    "notepad", "calculator", "paint", "word", "excel", "powerpoint",
    "spotify", "discord", "whatsapp", "file explorer", "explorer",
    "code editor", "editor", "browser application", "browser",
]

_BROWSER_NAMES = [
    "chrome", "firefox", "edge", "brave", "opera", "comet", "safari",
]

_WEBSITE_NAMES = [
    "youtube", "google", "gmail", "wikipedia", "github",
]

_SYSTEM_TERMS = [
    "volume", "sound", "audio", "brightness", "battery",
    "cpu", "processor", "ram", "memory usage", "memory is being used",
    "storage", "disk", "wifi", "wi-fi", "bluetooth", "network",
    "lock the laptop", "lock my laptop", "lock the computer",
    "lock my computer", "sleep", "restart", "shutdown", "shut down",
]

# Observation of which apps/windows are open ("what applications are
# open right now") is a COMPUTER capability (computer.running_apps),
# NOT system hardware info and NEVER a file search.
_RUNNING_APPS_PATTERN = re.compile(
    r"\b(?:what|which|whats|list|show|tell|see|any)\b[^.?!]{0,40}"
    r"\b(?:apps?|applications?|programs?|windows?)\b[^.?!]{0,30}"
    r"\b(?:open|running|active|started)\b"
    r"|\b(?:what(?:'s| is)\s+)?(?:open|running)\s+(?:right\s+)?now\b",
    re.IGNORECASE,
)

# News / release-info requests are always web lookups — never
# answered from training data ("what are the updates on ChatGPT").
_NEWS_PATTERN = re.compile(
    r"\bupdates?\s+(?:on|about|regarding|for)\b"
    r"|\bwhat(?:'s| is| are)(?:\s+the)?\s+"
    r"(?:latest|newest|current|recent|new)\b"
    r"|\b(?:latest|current|recent)\s+(?:news|updates?|version|release)\b"
    r"|\bany\s+(?:news|updates)\b"
    r"|\b(?:tell me|give me)(?:\s+the)?\s+(?:latest|news|updates)\b",
    re.IGNORECASE,
)

# Self-diagnostics phrasings route to system (system.diagnostics).
_DIAGNOSTICS_PATTERN = re.compile(
    r"\b(?:diagnostics|self[- ]check|are you (?:there|okay|ok|working)"
    r"|why aren'?t you|why are you not|something wrong with you"
    r"|check yourself)\b"
)

# Unified search phrasing: "find everything related to X" (context 53).
_SEARCH_ALL_PATTERN = re.compile(
    r"\b(?:find|search|look)\s+(?:for\s+)?(?:everything|anything|all)\b"
)

_FILESYSTEM_TERMS = [
    "file", "files", "folder", "folders", "directory", "directories",
    "document", "documents", "spreadsheet", "presentation", "pdf",
    "notes",
]

# Word-boundary matching so "documentation" does not match
# "document" and "profile" does not match "file".
_FS_TERMS_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in _FILESYSTEM_TERMS) + r")\b"
)

_MEMORY_PATTERNS = [
    r"\bremember\b", r"\bforget\b", r"\brecall\b",
    r"\bremind me\b", r"\breminders?\b",
    r"\bwhat was that\b", r"\bkeep in mind\b", r"\bdon'?t forget\b",
    r"\bwhat have you saved\b", r"\bupdate what you remember\b",
    r"\bdo you remember\b",
]

_SKILL_PATTERNS = [
    r"\bsaved (skill|workflow|routine|setup|study setup|project setup routine)\b",
    r"\bmy (saved )?(routine|workflow|skill)\b",
    r"\breusable\b", r"\bworkflow\b", r"\broutine\b",
    r"\bsomething i can run again\b",
    r"\bturn .* into something\b",
]

_SCREEN_PATTERNS = [
    r"\bscreenshot\b",
    r"\bsnapshot\b",
    r"\btake a picture\b",
    r"\bcapture\b",
    r"\bwhat(?:'s| is) (?:currently )?(?:on|visible on) (?:my |the )?(?:screen|display|monitor)\b",
    r"\bwhat(?:'s| is) visible\b",
    r"\bwhat(?:'s| is) shown on the (?:screen|page)\b",
    r"\bwhat .* looks like\b",
    r"\bwhat do .* look like\b",
    r"\blook at (?:my |the )?(?:screen|display)\b",
    r"\bon (?:my |the )?screen\b",
    r"\bcheck (?:the )?screen\b",
    r"\binspect (?:the )?(?:current )?display\b",
    r"\bshow me what(?:'s| is) (?:currently )?(?:on screen|on my screen)\b",
    r"\bwhat am i looking at\b",
    r"\bhave a look at the screen\b",
]

# Signals that a clause is about webpage content/UI interaction
# (browser) rather than visual inspection (screen).
_BROWSER_ACTION_PATTERNS = [
    r"\bnavigate\b", r"\bgo to\b", r"\btake me to\b", r"\bvisit\b",
    r"\bbrowse\b", r"\brefresh\b", r"\bgo back\b",
    r"\bprevious (?:page|webpage)\b",
    r"\bsearch (?:for|in|on|youtube|google)\b",
    r"\b(?:look for|find|hunt for) .+\bon (?:youtube|google)\b",
    r"\bopen the (?:first|top) result\b",
    r"\bopen .* in (?:chrome|firefox|edge|brave|opera|the browser)\b",
    r"\bopen (?:the |a )?(?:relevant |first |top |last )?(?:webpage|web page|website|link|url|site)\b",
    r"\bclick\b", r"\btype\b", r"\bplay\b", r"\bread\b", r"\bscroll\b",
    r"\bwhat .* (?:says|say)\b",
    r"\bwhat(?:'s| is) written\b",
    r"\binteract with\b",
]

# Web (information retrieval) signals.
_WEB_PATTERNS = [
    r"\bsearch (?:the )?(?:web|internet|online)\b",
    r"\bsearch online\b",
    r"\blook (?:up|online)\b",
    r"\bresearch\b",
    r"\bfind (?:some )?information(?: online)?\b",
    r"\bfind out\b",
    r"\bcheck online\b",
    r"\blatest\b.*\b(?:news|documentation|information|version|release)\b",
    r"\bwhat(?:'s| is) (?:currently )?happening\b",
    r"\b(?:online|quick online) lookup\b",
]

# Signals that a clause is about generic desktop interaction (computer).
_COMPUTER_PATTERNS = [
    r"\bmouse\b", r"\bcursor\b", r"\bpointer\b",
    r"\bmove (?:the|my) (?:mouse|cursor|pointer)\b",
    r"\b(?:double|right)[- ]click\b", r"\bclick\b",
    r"\bpress\b", r"\bhit\b",
    r"\btype\b", r"\bwrite\b", r"\bpaste\b", r"\benter\b",
    r"\bscroll\b", r"\bdrag\b",
]

_COMPUTER_GENERIC_TARGETS = [
    "the button", "that button", "the icon", "the taskbar",
    "the canvas", "the plus button", "the volume control",
    "the downloads folder", "the window", "the current window",
    "the active window", "the desktop", "whatever window",
    "wherever the cursor", "where the pointer",
]

_CLAUSE_SPLIT = re.compile(
    r"[.;\n]|\b(?:and then|then|after that|afterward[s]?)\b",
    re.IGNORECASE,
)

# A click/press aimed at a desktop UI element (icon, button, control)
# is generic computer interaction, not a system/filesystem operation.
_UI_CLICK_TARGET = re.compile(
    r"\b(?:icon|control|button|slider|taskbar|desktop)\b"
)


# ============================================================
# ROUTER
# ============================================================

class CapabilityRouter:
    """
    Hybrid capability router.

    Deterministic rules are preferred because they are:
    - faster
    - cheaper
    - predictable
    - independent of model availability

    Groq is only used when the request cannot be resolved
    confidently through deterministic rules.
    """

    def __init__(self, provider: GroqProvider | None = None):
        self.provider = provider or GroqProvider()

    # ========================================================
    # PUBLIC API
    # ========================================================

    def route(self, request: str) -> list[str]:
        """Return the capabilities required for a user request."""

        if not isinstance(request, str):
            raise TypeError("request must be a string")

        request = request.strip()

        if not request:
            return []

        deterministic, needs_semantic = self._deterministic_route(request)

        if needs_semantic:
            return self._semantic_route(request)

        return validate_capabilities(deterministic)

    # ========================================================
    # DETERMINISTIC ROUTING
    # ========================================================

    def _deterministic_route(
        self,
        request: str,
    ) -> tuple[list[str], bool]:
        """
        Analyze the request clause by clause, as operations.

        Returns:
            (capabilities, needs_semantic)
        """

        text = request.lower()
        clauses = self._split_clauses(text)

        # "What are the updates on ChatGPT" -> web, deterministically.
        if _NEWS_PATTERN.search(text):
            return ["web"], False

        capabilities: list[str] = []
        unresolved = False

        for index, clause in enumerate(clauses):
            clause_caps = self._analyze_clause(clause)

            if clause_caps is None and index > 0:
                # Pronoun continuation: "The audio is way too loud.
                # Bring it down." Re-analyze merged with the previous
                # clause before paying for an LLM call.
                clause_caps = self._analyze_clause(
                    f"{clauses[index - 1]}. {clause}"
                )

            if clause_caps is None:
                # Pure context statement ("the browser is already
                # open"): contributes nothing IF some other clause in
                # the request resolves. Otherwise the request falls
                # back to semantic routing below.
                unresolved = True
                continue

            capabilities.extend(clause_caps)

        if unresolved and not capabilities:
            # No clause could be classified at all.
            return [], True

        return capabilities, False

    def _analyze_clause(self, clause: str) -> list[str] | None:
        """
        Classify ONE clause. Returns None when the clause carries
        signals that deterministic rules cannot resolve confidently.
        """

        if not clause.strip():
            return []

        caps: list[str] = []
        matched = False

        # A click/press targeting a desktop UI element ("click the
        # Bluetooth icon") is computer interaction; the system term is
        # the TARGET, not a requested system operation.
        interaction = self._matches_any_pattern(clause, _COMPUTER_PATTERNS)
        ui_click_target = bool(interaction and _UI_CLICK_TARGET.search(clause))

        # ------------------------------------------------
        # MEMORY
        # ------------------------------------------------
        if self._matches_any_pattern(clause, _MEMORY_PATTERNS):
            caps.append("memory")
            matched = True

        # ------------------------------------------------
        # SKILL
        # ------------------------------------------------
        if self._matches_any_pattern(clause, _SKILL_PATTERNS):
            caps.append("skill")
            matched = True

        # ------------------------------------------------
        # SCREEN
        # ------------------------------------------------
        if self._matches_any_pattern(clause, _SCREEN_PATTERNS):
            caps.append("screen")
            matched = True

        # ------------------------------------------------
        # PRONOUN OPEN ("open it", "open them")
        # ------------------------------------------------
        # Opening a previously located file or folder happens in an
        # application (stress_072/118 pattern).
        if (
            re.search(r"\bopen (?:it|them|that|this|these|those)\b", clause)
            and not self._contains_any(clause, _APPLICATION_TARGETS)
            and not self._contains_any(clause, _BROWSER_NAMES)
            and not self._contains_any(clause, _WEBSITE_NAMES)
        ):
            caps.append("application")
            matched = True

        # ------------------------------------------------
        # RUNNING-APPS OBSERVATION (before system/filesystem so
        # "what applications are open" can never degrade into a
        # file search or hardware answer).
        # ------------------------------------------------
        if _RUNNING_APPS_PATTERN.search(clause):
            caps.append("computer")
            matched = True

        # ------------------------------------------------
        # SYSTEM
        # ------------------------------------------------
        if (
            self._contains_any(clause, _SYSTEM_TERMS)
            and not ui_click_target
        ) or _DIAGNOSTICS_PATTERN.search(clause):
            caps.append("system")
            matched = True

        # ------------------------------------------------
        # WEB (information retrieval)
        # ------------------------------------------------
        if self._matches_any_pattern(clause, _WEB_PATTERNS):
            caps.append("web")
            matched = True

        # ------------------------------------------------
        # FILESYSTEM
        # ------------------------------------------------
        if (
            (
                _FS_TERMS_PATTERN.search(clause)
                or _SEARCH_ALL_PATTERN.search(clause)
            )
            and (
                self._has_fs_action(clause)
                or _SEARCH_ALL_PATTERN.search(clause)
            )
            and not ui_click_target
        ):
            caps.append("filesystem")
            matched = True

        # ------------------------------------------------
        # APPLICATION (launch/open/close an app or browser)
        # ------------------------------------------------
        if self._is_application_launch(clause):
            caps.append("application")
            matched = True

        # ------------------------------------------------
        # BROWSER (webpage/website interaction)
        # ------------------------------------------------
        browser = self._is_browser_interaction(clause)

        if browser:
            caps.append("browser")
            matched = True

        # ------------------------------------------------
        # COMPUTER (generic desktop interaction)
        # ------------------------------------------------
        if self._is_generic_computer(clause, caps):
            caps.append("computer")
            matched = True

        if not matched:
            # No recognizable operation at all.
            return None

        return caps

    # --------------------------------------------------------
    # OPERATION DETECTORS
    # --------------------------------------------------------

    def _is_application_launch(self, clause: str) -> bool:
        """
        True when the clause explicitly launches/opens/closes an
        application (including a browser AS an application).
        """

        if not re.search(
            r"\b(?:open|launch|start|bring up|close|quit|run)\b"
            r"|\bget .*\b(?:running|open|up)\b"
            r"|\bbring .*\b(?:up|front|foreground)\b",
            clause,
        ):
            return False

        # "The browser is already open" is a state, not a launch.
        if re.search(
            r"\b(?:is|are|was|were|am|'s|isn't|aren't|not)\s+(?:already\s+)?open\b",
            clause,
        ):
            return False

        # Negated launches: "don't open a browser" (stress_135).
        if re.search(
            r"\b(?:don'?t|do not|never|without)\s+(?:\w+\s+)?(?:open|opening|launch|launching|start|starting|run|running)\b",
            clause,
        ):
            return False

        # "Read the article currently open in Chrome" — "open in
        # <browser>" describes WHERE something is, not a launch
        # (stress_096).
        if re.search(
            r"\bopen(?:ed)?\s+in\s+\w+\b",
            clause,
        ):
            return False

        if self._contains_any(clause, _APPLICATION_TARGETS):
            return True

        if self._contains_any(clause, _BROWSER_NAMES):
            return True

        return False

    def _is_browser_interaction(self, clause: str) -> bool:
        """
        True when the clause explicitly interacts with a webpage,
        website, or browser UI.
        """

        # A named website being interacted with.
        for site in _WEBSITE_NAMES:
            if site in clause and self._matches_any_pattern(
                clause, _BROWSER_ACTION_PATTERNS
            ):
                return True

            # "Find the Wikipedia page for Python" — a page/article on
            # a named site is browser interaction (stress_043).
            if site in clause and re.search(
                r"\b(?:page|article|video|channel)\b", clause
            ):
                return True

        # Explicit browser/webpage words WITH an interaction action.
        if re.search(
            r"\b(?:webpage|web page|website|browser|tab|article)\b",
            clause,
        ):
            if self._matches_any_pattern(
                clause, _BROWSER_ACTION_PATTERNS
            ):
                return True

            # Merely mentioning a webpage without interaction is not
            # browser (e.g. "open Chrome and tell me what the webpage
            # looks like").
            return False

        return False

    def _is_generic_computer(
        self,
        clause: str,
        caps: list[str],
    ) -> bool:
        """
        True for explicit generic desktop interaction (mouse/keyboard)
        that is not already covered by a specialized capability.

        IMPORTANT: browser interaction ("click the button that says
        Continue" on a webpage) must NOT become computer.
        """

        if "browser" in caps:
            return False

        if not self._matches_any_pattern(clause, _COMPUTER_PATTERNS):
            return False

        # Click/type/scroll targeting a named website belongs to
        # browser, handled elsewhere.
        if self._contains_any(clause, _WEBSITE_NAMES):
            return False

        # Everything else counts: generic targets ("the button",
        # "the icon", "the taskbar") and bare interactions ("type
        # hello", "move the mouse") alike.
        return True

    def _has_fs_action(self, clause: str) -> bool:
        return bool(
            re.search(
                r"\b(?:find|locate|search|look for|hunt|track down|open|read|create|make|copy|move|rename|delete|remove|get rid of|inspect|show|tell me|where|what)\b",
                clause,
            )
        )

    # --------------------------------------------------------
    # HELPERS
    # --------------------------------------------------------

    @staticmethod
    def _split_clauses(text: str) -> list[str]:
        clauses = [c.strip() for c in _CLAUSE_SPLIT.split(text) if c.strip()]
        return clauses or [text]

    @staticmethod
    def _contains_any(text: str, values: Iterable[str]) -> bool:
        return any(value in text for value in values)

    @staticmethod
    def _matches_any_pattern(text: str, patterns: Iterable[str]) -> bool:
        return any(re.search(p, text) for p in patterns)

    # ========================================================
    # SEMANTIC FALLBACK
    # ========================================================

    def _semantic_route(self, request: str) -> list[str]:
        """
        Ask Groq to classify only requests that deterministic
        routing could not confidently resolve.
        """

        prompt = f"""You are JARVIS's capability classifier.

Determine every capability genuinely required by the request.

Available capabilities:
application, browser, computer, filesystem, screen, web, system, memory, skill

Rules:
- Classify by operations, not keywords.
- application = launch/open/close desktop applications.
- browser = interact with a browser or webpage.
- computer = generic mouse/keyboard interaction with ordinary desktop apps.
- filesystem = file/folder operations.
- screen = inspect what is visually displayed on screen.
- web = retrieve internet information without browser UI interaction.
- system = OS/hardware controls and information.
- memory = remember/recall/update persistent user information.
- skill = discover/create/validate/run saved reusable workflows.

Boundaries:
- "Open Chrome" alone = application. Browser only when the webpage is interacted with.
- "Search online / the web / the internet" = web. Searching YouTube/Google inside a browser = browser.
- "What does the webpage look like" = screen. "What does the webpage say" = browser.
- Reading a file = filesystem. Opening a found file in an app = filesystem + application.
- Do not add computer when a specialized capability applies.
- Include every capability required by multi-task requests.

Return ONLY JSON: {{"capabilities": ["capability1", "capability2"]}}

Request:
{request}"""

        try:
            response = self.provider.generate(prompt)
        except Exception:
            # Provider failure: fail closed with an empty result
            # rather than crashing the assistant.
            return []

        capabilities = self._extract_capabilities(response)

        return validate_capabilities(capabilities)

    # ========================================================
    # RESPONSE PARSING
    # ========================================================

    def _extract_capabilities(self, response: str) -> list[str]:
        """
        Extract capability names from Groq's response.

        JSON is preferred, but a small fallback parser is kept
        so malformed model formatting does not crash routing.
        """

        if not response:
            return []

        text = response.strip()

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------
        try:
            data = json.loads(text)

            if isinstance(data, dict):
                result = data.get("capabilities")

                if isinstance(result, list):
                    return [
                        item
                        for item in result
                        if isinstance(item, str)
                    ]

        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------
        found = []

        for capability in CAPABILITY_NAMES:
            if re.search(
                rf"\b{re.escape(capability)}\b",
                text.lower(),
            ):
                found.append(capability)

        return found


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

_default_router: CapabilityRouter | None = None


def get_router() -> CapabilityRouter:
    """Return the shared router instance."""

    global _default_router

    if _default_router is None:
        _default_router = CapabilityRouter()

    return _default_router


def route_capabilities(request: str) -> list[str]:
    """Convenience API for JARVIS."""

    return get_router().route(request)


# ============================================================
# DEVELOPMENT TEST
# ============================================================

if __name__ == "__main__":
    router = CapabilityRouter()

    examples = [
        "Open Notepad and type hello.",
        "Search online for the latest Python documentation.",
        "Open Chrome and go to YouTube.",
        "Find my physics notes.",
        "Turn the volume down.",
        "Tell me what's visible on my screen.",
        "Remember that I am studying physics.",
    ]

    for request in examples:
        print(f"\nRequest: {request}")
        print(f"Capabilities: {router.route(request)}")
