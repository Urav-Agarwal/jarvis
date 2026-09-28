from ai.provider import GroqProvider


provider = GroqProvider()


prompt = """
You are JARVIS's capability router.

Identify ALL capability categories required to fulfill the user's request.

Available categories:

computer:
Mouse, keyboard, clicking, scrolling, typing, screen interaction,
active window, running applications.

application:
Opening, closing, launching, or checking installed applications.

browser:
Opening browsers, navigating websites, interacting with webpages,
tabs, browser controls, and web pages.

filesystem:
Finding, reading, creating, copying, moving, deleting, or opening
files and folders.

system:
Volume, brightness, battery, CPU, RAM, storage, Wi-Fi, Bluetooth,
network, sleep, restart, shutdown, and laptop state.

screen:
Screenshots and visual analysis of the current screen.

web:
Internet search and fetching information from webpages.

memory:
Remembering, recalling, or updating information about the user.

skill:
Reusable workflows and multi-step routines.

Return ONLY valid JSON:

{
    "capabilities": ["category1", "category2"]
}

Routing rules:

1. Choose capabilities based on the user's INTENDED TASK, not on the
   low-level actions that may be required to execute it.

2. APPLICATION vs BROWSER:
   - Use "application" when JARVIS must launch, open, close, or inspect
     a desktop application.
   - Use "browser" when JARVIS must control an already-open browser or
     interact with websites inside the browser.
   - If a request requires BOTH launching a browser application AND then
     interacting with that browser, include BOTH "application" and "browser".
   - Do not assume that browser.open replaces application.open.

3. BROWSER vs WEB:
   - Use "browser" when JARVIS must control a browser UI.
   - This includes navigating websites, clicking links/buttons, typing into
     webpages, scrolling webpages, reading webpage content, managing tabs,
     and searching YouTube/Google through the browser.
   - Use "web" when JARVIS only needs to retrieve information from the
     internet without controlling a browser UI.
   - Do NOT include "web" merely because the browser is accessing online
     information.

4. APPLICATION vs COMPUTER:
   - Use "application" when the user asks JARVIS to launch, open,
     close, or inspect a desktop application.
   - Also use "computer" when the user asks JARVIS to directly
     interact with that desktop application's interface by typing,
     pressing keys, clicking, scrolling, or performing other generic
     mouse/keyboard actions.
   - This applies to ordinary desktop applications that do not have
     their own specialized interaction capability.
   - If a specialized capability exists for the application or domain,
     prefer that specialized capability instead of "computer".
   - For example:
       "Open Notepad and type hello" → application + computer
       "Launch Calculator and press 5" → application + computer
       "Open Chrome and click a webpage button" → application + browser

5. BROWSER vs COMPUTER:
   - Use "browser" for interactions that happen inside a browser.
   - Do NOT add "computer" merely because clicking, typing, scrolling,
     or keyboard/mouse input will be used internally to control the browser.
   - Use "computer" for generic desktop interaction outside specialized
     capabilities, such as controlling arbitrary windows or interacting
     directly with the desktop.

6. APPLICATION:
   - Use "application" when the user explicitly asks to open, close,
     launch, or inspect a desktop application.
   - Do not use "application" simply because an application happens to be
     involved in another task.

7. SCREEN:
   - Use "screen" when the user asks for a screenshot or visual analysis
     of what is currently visible on the computer screen.

8. SYSTEM:
   - Use "system" for volume, brightness, battery, CPU, RAM, storage,
     Wi-Fi, Bluetooth, sleep, restart, shutdown, and other laptop-level
     system controls.

9. A capability may be combined with other capabilities when the user's
   request genuinely requires multiple domains.

10. Return only the capabilities genuinely required to fulfill the user's
   request.

11. Never add a capability solely because another capability may internally
   use it.

12. Do not invent capability categories.

User request:
Open Chrome, go to YouTube, search for a JEE physics lecture, open the first relevant result, and tell me what is shown on the page.
"""

print(provider.generate(prompt))