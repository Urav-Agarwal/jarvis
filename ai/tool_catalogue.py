from ai.tool_schema import ToolDefinition


class ToolCatalogue:
    def __init__(self):
        self.tools = [

            # =========================
            # COMPUTER
            # =========================

            ToolDefinition(
                name="computer.mouse_move",
                description="Move the mouse cursor to a screen position.",
                parameters={
                    "x": "integer",
                    "y": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.mouse_click",
                description="Click the mouse at the current cursor position or specified screen position.",
                parameters={
                    "button": "string",
                    "clicks": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.mouse_double_click",
                description="Double-click at the current cursor position (opens shortcuts, files, icons).",
                parameters={
                    "button": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.mouse_drag",
                description="Drag (hold left button, glide, release) to screen position x,y.",
                parameters={
                    "x": "integer",
                    "y": "integer",
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.open_shortcut",
                description=(
                    "Open a desktop shortcut (.lnk/.url) by name without "
                    "pixel clicking: 'open the Instagram shortcut on my "
                    "desktop'. Fuzzy-matches the shortcut name and starts "
                    "the target directly. USE THIS before trying to click "
                    "desktop icons." 
                ),
                parameters={
                    "name": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.mouse_scroll",
                description="Scroll the mouse wheel.",
                parameters={
                    "amount": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.keyboard_type",
                description="Type text using the keyboard.",
                parameters={
                    "text": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.keyboard_press",
                description="Press a keyboard key or key combination.",
                parameters={
                    "key": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.active_window",
                description="Get the currently active window on the entire computer. Use this when the user asks what application or window they are currently using, without specifying a particular application.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.running_apps",
                description="List applications currently running on the computer.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.history",
                description=(
                    "Time Machine: summarize what the user did on this "
                    "computer during a past period — commands given, apps "
                    "opened, tools run. Use for 'what was I doing last "
                    "Tuesday' or 'what did I do earlier today'."
                ),
                parameters={
                    "period": {
                        "type": "string",
                        "description": (
                            "Optional period: 'today', 'yesterday', or a "
                            "weekday like 'tuesday'. Defaults to today."
                        ),
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.background_apps",
                description="List applications and processes currently running in the background.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # APPLICATIONS
            # =========================

            ToolDefinition(
                name="application.discover",
                description="Discover applications installed or available through the Windows Start Menu.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="application.open",
                description="Open a discovered application.",
                parameters={
                    "application": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="application.close",
                description="Close an application.",
                parameters={
                    "application": "string",
                },
                risk="medium",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="application.close_all",
                description=(
                    "Gracefully close ALL visible running applications "
                    "at once (used for 'close all the applications'). "
                    "Windows shell and JARVIS itself are never closed."
                ),
                parameters={},
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="application.send_message",
                description=(
                    "Send a chat message through an installed messaging "
                    "app: app=whatsapp/discord/instagram/telegram, plus "
                    "contact and message. The app must be running and "
                    "signed in. WhatsApp is fully verified; other apps "
                    "use window automation."
                ),
                parameters={
                    "app": "string",
                    "contact": "string",
                    "message": "string",
                },
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="application.whatsapp_search",
                description=(
                    "Search WhatsApp chats by name WITHOUT sending "
                    "anything: types the name into WhatsApp's search "
                    "box and reads the visible contact/chat results. "
                    "Use BEFORE application.whatsapp_message when the "
                    "exact contact name is uncertain, or when the user "
                    "asked to message someone by a short name. Returns "
                    "the list of visible names so the user can pick." 
                ),
                parameters={
                    "query": {
                        "type": "string",
                        "description": "The contact name or partial name to search for.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="application.whatsapp_message",
                description=(
                    "Send a WhatsApp message to a contact from the "
                    "WhatsApp desktop app. WhatsApp must already be "
                    "running and signed in. Use for 'send this message "
                    "to this person on WhatsApp'."
                ),
                parameters={
                    "contact": "string",
                    "message": "string",
                },
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="application.state",
                description="Check whether a specific application is currently running on the computer.",
                parameters={
                    "name": {
                        "type": "string",
                        "description": "The name of the application to check."
                    }
                },
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # BROWSER
            # =========================

            ToolDefinition(
                name="browser.discover",
                description="Discover installed browsers on the computer.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.profiles",
                description="Discover available profiles for an installed browser.",
                parameters={
                    "browser": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.open",
                description="Open an installed browser, optionally using a discovered browser profile.",
                parameters={
                    "browser": "string",
                    "profile": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.search",
                description=(
                    "Search ON a website by opening that site's own "
                    "search page. Use for requests like 'search YouTube "
                    "for wave optics' or 'search Google for Python "
                    "documentation'. Opens the site's search results — "
                    "never a specific video or article link."
                ),
                parameters={
                    "site": {
                        "type": "string",
                        "description": (
                            "The site to search on, e.g. youtube, google, "
                            "github, wikipedia. Empty for a general web "
                            "search."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "What to search for.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.navigate",
                description="Navigate the active browser to a URL.",
                parameters={
                    "url": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.back",
                description="Navigate the active browser back one page.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.forward",
                description="Navigate the active browser forward one page.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.refresh",
                description="Refresh the active browser page.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.read",
                description="Read and extract useful visible information from the active browser page.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.close_tabs",
                description=(
                    "Close recent browser tabs, starting with the tabs "
                    "JARVIS opened this session. Use for 'close the tabs "
                    "you opened' or 'close the recent tabs'."
                ),
                parameters={
                    "count": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.click",
                description="Click an element on the active browser page.",
                parameters={
                    "target": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.type",
                description="Type text into a specified browser input or page element.",
                parameters={
                    "target": "string",
                    "text": "string",
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.scroll",
                description="Scroll the active browser page.",
                parameters={
                    "amount": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.inspect",
                description="Inspect the active browser page to identify useful interactive elements and page state.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.copy",
                description="Copy selected or identified text from the active browser page to the system clipboard.",
                parameters={
                    "target": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.state",
                description="Inspect the current state of a specific browser, including whether it is running and its current browser window.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.tab_state",
                description="Get information about the active browser tab, including its title and URL when available.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="browser.media_state",
                description="Determine the available media or video playback state of the active browser page.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # FILESYSTEM
            # =========================

            ToolDefinition(
                name="filesystem.search",
                description=(
                    "Search for files and folders by natural language, "
                    "partial filename, or keywords. Optionally restrict "
                    "the search to a specific folder."
                ),
                parameters={
                    "query": {
                        "type": "string",
                        "description": "The filename, partial filename, or keywords to search for.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional folder or directory to search in.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.read",
                description=(
                    "Read the text contents of a file. Use this when the user "
                    "asks JARVIS to read, show, or inspect the contents of a file."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The full path to the file to read.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional maximum number of characters to read.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.create",
                description=(
                    "Create a new file or folder at the specified path. "
                    "Use directory=true when creating a folder. "
                    "For a file, content can contain the initial text."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The path where the new file or folder should be created.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Optional initial text content for a file.",
                    },
                    "directory": {
                        "type": "boolean",
                        "description": "Set to true when creating a folder instead of a file.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether an existing path may be overwritten.",
                    },
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.copy",
                description=(
                    "Copy a file or folder from one location to another."
                ),
                parameters={
                    "source": {
                        "type": "string",
                        "description": "The source file or folder path.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "The destination path.",
                    },
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.move",
                description=(
                    "Move a file or folder from one location to another."
                ),
                parameters={
                    "source": {
                        "type": "string",
                        "description": "The source file or folder path.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "The destination path.",
                    },
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.delete",
                description=(
                    "Delete a file or folder. This is a destructive operation "
                    "and always requires user confirmation before execution."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The file or folder path to delete.",
                    },
                },
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="filesystem.info",
                description=(
                    "Get detailed metadata about a file or folder, including "
                    "name, path, extension, size, creation time, modification "
                    "time, and whether it is a file or directory."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The file or folder path.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.type",
                description=(
                    "Determine the type of a file or folder, such as text/plain, "
                    "PDF, image, directory, or another recognized file type."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The file or folder path.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.state",
                description=(
                    "Get filesystem state information. When a path is provided, "
                    "return information about that file or folder. When no path "
                    "is provided, return the user's standard filesystem locations."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "Optional file or folder path.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.open",
                description=(
                    "Open a file or folder using the appropriate Windows "
                    "application or Explorer."
                ),
                parameters={
                    "path": {
                        "type": "string",
                        "description": "The file or folder path to open.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # SYSTEM
            # =========================

            ToolDefinition(
                name="system.volume",
                description=(
                    "Get or change the computer volume. For actions other "
                    "than 'get', pass 'amount' (0-100 for set)."
                ),
                parameters={
                    "action": "string",
                    "amount": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.app_volume",
                description=(
                    "Get or change the volume of ONE application only, "
                    "like the volume of the video playing in Chrome or "
                    "music in Spotify, WITHOUT touching the overall "
                    "system volume. Use this whenever the user names an "
                    "app or a site's video and asks for ITS volume. "
                    "action: get/set/increase/decrease; amount for "
                    "set (0-100) or increase/decrease (delta)."
                ),
                parameters={
                    "application": "string",
                    "action": "string",
                    "amount": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.brightness",
                description="Get or change the display brightness.",
                parameters={
                    "action": "string",
                    "amount": "integer",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.time",
                description=(
                    "Get the current local date and time. Use for any "
                    "'what time is it' or 'what is the date' question."
                ),
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.battery",
                description="Get the current battery status.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.network",
                description="Inspect basic network and connectivity information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.lock",
                description="Lock the computer.",
                parameters={},
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="system.sleep",
                description="Put the computer to sleep.",
                parameters={},
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="system.restart",
                description="Restart the computer.",
                parameters={},
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="system.shutdown",
                description="Shut down the computer.",
                parameters={},
                risk="high",
                confirmation_required=True,
            ),

            ToolDefinition(
                name="system.cpu",
                description="Get current CPU usage and processor information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.memory",
                description="Get RAM usage, total RAM, available RAM, and related memory information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.storage",
                description="Get storage capacity, used space, and free space for the computer.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.gpu",
                description="Get GPU usage and available graphics hardware information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.wifi",
                description="Get Wi-Fi connection status and available network information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.wifi_speed",
                description="Get the available Wi-Fi link or connection speed information reported by the operating system.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.bluetooth",
                description="Get Bluetooth availability, adapter status, and available connected-device information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.laptop",
                description="Get general laptop hardware and system information.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="media.playback",
                description=(
                    "Control media playback on the active player: "
                    "play, pause, toggle, next or previous track. "
                    "Works with Spotify, YouTube in a browser, and "
                    "any app that honors media keys."
                ),
                parameters={
                    "action": {
                        "type": "string",
                        "description": "play / pause / toggle / next / previous",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.window",
                description=(
                    "Window management: focus (switch to), minimize, "
                    "maximize, or close a window by application or "
                    "title. Use for 'switch to Chrome', 'minimize "
                    "everything', 'maximize notepad'."
                ),
                parameters={
                    "action": {
                        "type": "string",
                        "description": "focus / minimize / maximize / close / minimize_all",
                    },
                    "target": {
                        "type": "string",
                        "description": "App or window title. Empty for the active window.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.clipboard",
                description=(
                    "Read the clipboard text aloud or write text to "
                    "the clipboard. Use for 'what's on my clipboard' "
                    "or 'copy this to the clipboard'."
                ),
                parameters={
                    "action": {
                        "type": "string",
                        "description": "read / write",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to write (write action only).",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # SCREEN / CAPTURE
            # =========================

            ToolDefinition(
                name="screen.screenshot",
                description="Capture the current computer screen and copy the screenshot to the clipboard.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="screen.analyze",
                description=(
                    "Analyze the current computer screen and answer a specific "
                    "question about what is visibly shown."
                ),
                parameters={
                    "question": {
                        "type": "string",
                        "description": (
                            "A specific question about the current visible screen."
                        ),
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="screen.pointer",
                description=(
                    "The Pointer: find WHERE a named control is on screen "
                    "and describe its location with screen coordinates. "
                    "Use for 'where do I click to send this email' or "
                    "'show me where the settings button is'."
                ),
                parameters={
                    "target": {
                        "type": "string",
                        "description": "The control/element to locate on screen.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="computer.driver",
                description=(
                    "The Careful Driver: take over mouse/keyboard to "
                    "perform a task step by step, narrating each action. "
                    "ALWAYS asks for a plan confirmation first. Hard "
                    "refusals: payments, card/bank details, passwords, "
                    "deleting files, or sending any message without the "
                    "exact text shown first."
                ),
                parameters={
                    "task": {
                        "type": "string",
                        "description": "The task to perform by driving the UI.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": (
                            "True when the user already approved the plan."
                        ),
                    },
                },
                risk="high",
                confirmation_required=True,
            ),

            # =========================
            # WEB
            # =========================

            ToolDefinition(
                name="web.search",
                description="Search the web for information.",
                parameters={
                    "query": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="web.fetch",
                description="Retrieve information from a specified web page.",
                parameters={
                    "url": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # MEMORY
            # =========================

            ToolDefinition(
                name="memory.remember",
                description="Store information in JARVIS memory.",
                parameters={
                    "information": "string",
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.recall",
                description="Retrieve relevant information from JARVIS memory.",
                parameters={
                    "query": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.update",
                description="Update previously stored information in JARVIS memory.",
                parameters={
                    "query": "string",
                    "information": "string",
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="filesystem.search_all",
                description=(
                    "Search everything at once: files, installed "
                    "applications, saved skills, and remembered facts. "
                    "Use when the user asks to find anything related to "
                    "a topic without specifying files only."
                ),
                parameters={
                    "query": {
                        "type": "string",
                        "description": "The topic or name to search for.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.forget",
                description="Remove a previously stored fact from JARVIS memory.",
                parameters={
                    "query": {
                        "type": "string",
                        "description": "Keywords identifying the fact to forget.",
                    },
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.remind",
                description=(
                    "Set a reminder. Accepts natural language such as "
                    "'remind me to submit the assignment at 8 PM' or "
                    "'in 20 minutes' or 'every evening at 9'."
                ),
                parameters={
                    "request": {
                        "type": "string",
                        "description": "The full reminder request with the time.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.reminders",
                description="List pending reminders.",
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="memory.cancel_reminder",
                description="Cancel a pending reminder by keywords.",
                parameters={
                    "query": {
                        "type": "string",
                        "description": "Keywords identifying the reminder.",
                    },
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="system.diagnostics",
                description=(
                    "Inspect JARVIS's own subsystems: provider, "
                    "microphone, network, tool registry, memory, and "
                    "skills. Use when the user asks why JARVIS is not "
                    "responding or to check JARVIS's health."
                ),
                parameters={},
                risk="low",
                confirmation_required=False,
            ),

            # =========================
            # SKILLS
            # =========================

            ToolDefinition(
                name="skill.discover",
                description="Find a saved JARVIS skill that may help accomplish a task.",
                parameters={
                    "query": "string",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="skill.create",
                description="Create a reusable declarative workflow from approved JARVIS capabilities.",
                parameters={
                    "name": "string",
                    "description": "string",
                    "steps": "array",
                },
                risk="medium",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="skill.validate",
                description="Validate a skill before it is saved or executed.",
                parameters={
                    "skill": "object",
                },
                risk="low",
                confirmation_required=False,
            ),

            ToolDefinition(
                name="skill.execute",
                description="Execute a previously validated JARVIS skill.",
                parameters={
                    "name": "string",
                    "parameters": "object",
                },
                risk="medium",
                confirmation_required=False,
            ),
        ]

        for tool in self.tools:
            tool.category = tool.name.split(".", 1)[0]

    def get_tools(self):
        return self.tools

    def get_tool(self, name: str):
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def get_tools_for_capabilities(self, capabilities):
        """
        Filter the catalogue down to tools relevant to the given
        capability list (from the capability router).

        Returns None when no capabilities are provided (use the full
        catalogue), or a possibly-empty list of matching tools.
        """
        if not capabilities:
            return None

        # Capability -> tool name prefixes.
        capability_prefixes = {
            "application": ("application.",),
            "browser": ("browser.",),
            "computer": ("computer.",),
            "filesystem": ("filesystem.",),
            "screen": ("screen.",),
            "web": ("web.",),
            "system": ("system.",),
            "memory": ("memory.",),
            "skill": ("skill.",),
        }

        prefixes = set()

        for capability in capabilities:
            prefixes.update(
                capability_prefixes.get(capability, ())
            )

        if not prefixes:
            return []

        return [
            tool
            for tool in self.tools
            if tool.name.startswith(tuple(prefixes))
        ]