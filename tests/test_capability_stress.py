import json
import re
import time
from openai import RateLimitError

from ai.provider import GroqProvider

provider = GroqProvider()

TEST_CASES = [

    # ============================================================
    # 1. COMPUTER — INDIRECT / NATURAL LANGUAGE
    # ============================================================

    {
        "id": "stress_001",
        "request": "Put the cursor roughly in the middle of the display.",
        "expected": ["computer"],
    },
    {
        "id": "stress_002",
        "request": "Get the pointer over to the upper-right corner.",
        "expected": ["computer"],
    },
    {
        "id": "stress_003",
        "request": "Write hello into whatever window I'm currently using.",
        "expected": ["computer"],
    },
    {
        "id": "stress_004",
        "request": "Send an Enter key press to the current window.",
        "expected": ["computer"],
    },
    {
        "id": "stress_005",
        "request": "Move the pointer over to the left side of the desktop.",
        "expected": ["computer"],
    },
    {
        "id": "stress_006",
        "request": "Type today's date wherever the cursor is currently active.",
        "expected": ["computer"],
    },
    {
        "id": "stress_007",
        "request": "Hit Escape on the window I'm working in.",
        "expected": ["computer"],
    },
    {
        "id": "stress_008",
        "request": "Scroll down a little in the active window.",
        "expected": ["computer"],
    },
    {
        "id": "stress_009",
        "request": "Give the current window a few downward scrolls.",
        "expected": ["computer"],
    },
    {
        "id": "stress_010",
        "request": "Click where the pointer is currently positioned.",
        "expected": ["computer"],
    },


    # ============================================================
    # 2. APPLICATION — INDIRECT
    # ============================================================

    {
        "id": "stress_011",
        "request": "Bring up Microsoft's code editor.",
        "expected": ["application"],
    },
    {
        "id": "stress_012",
        "request": "Get Spotify running.",
        "expected": ["application"],
    },
    {
        "id": "stress_013",
        "request": "I need Discord open.",
        "expected": ["application"],
    },
    {
        "id": "stress_014",
        "request": "Close the music player.",
        "expected": ["application"],
    },
    {
        "id": "stress_015",
        "request": "Get File Explorer up for me.",
        "expected": ["application"],
    },
    {
        "id": "stress_016",
        "request": "Start the calculator.",
        "expected": ["application"],
    },
    {
        "id": "stress_017",
        "request": "Bring Notepad to the foreground.",
        "expected": ["application"],
    },
    {
        "id": "stress_018",
        "request": "Shut down the Discord application.",
        "expected": ["application"],
    },
    {
        "id": "stress_019",
        "request": "Launch the browser application.",
        "expected": ["application"],
    },
    {
        "id": "stress_020",
        "request": "Open my code editor and leave it running.",
        "expected": ["application"],
    },


    # ============================================================
    # 3. APPLICATION + COMPUTER
    # ============================================================

    {
        "id": "stress_021",
        "request": "Bring up Notepad and write my name into it.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_022",
        "request": "Start Calculator and enter 25.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_023",
        "request": "Open Paint and draw by clicking in the canvas.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_024",
        "request": "Launch Notepad and type out my study plan.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_025",
        "request": "Get Calculator open and press the plus button.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_026",
        "request": "Open File Explorer and click the Downloads folder.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_027",
        "request": "Start the calculator and use it to add 50 and 25.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_028",
        "request": "Bring Notepad up and paste the text I give you.",
        "expected": ["application", "computer"],
    },


    # ============================================================
    # 4. BROWSER — INDIRECT
    # ============================================================

    {
        "id": "stress_029",
        "request": "Take me to YouTube in Chrome.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_030",
        "request": "Navigate the current browser to Google's homepage.",
        "expected": ["browser"],
    },
    {
        "id": "stress_031",
        "request": "Find the search box on the page and use it.",
        "expected": ["browser"],
    },
    {
        "id": "stress_032",
        "request": "Go back to the previous webpage.",
        "expected": ["browser"],
    },
    {
        "id": "stress_033",
        "request": "Return to the page I was just looking at.",
        "expected": ["browser"],
    },
    {
        "id": "stress_034",
        "request": "Refresh what I'm currently viewing online.",
        "expected": ["browser"],
    },
    {
        "id": "stress_035",
        "request": "Scroll further down the webpage.",
        "expected": ["browser"],
    },
    {
        "id": "stress_036",
        "request": "Click the button that says Continue.",
        "expected": ["browser"],
    },
    {
        "id": "stress_037",
        "request": "Type my search into the box that's open in Chrome.",
        "expected": ["browser"],
    },
    {
        "id": "stress_038",
        "request": "Open the first result on this webpage.",
        "expected": ["browser"],
    },


    # ============================================================
    # 5. APPLICATION + BROWSER
    # ============================================================

    {
        "id": "stress_039",
        "request": "Bring Chrome up and look for JEE physics lectures on YouTube.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_040",
        "request": "Launch Chrome and take me to Gmail.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_041",
        "request": "Start the browser and open the OpenAI website.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_042",
        "request": "Get Chrome running and search for today's technology news.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_043",
        "request": "Open Firefox and find the Wikipedia page for Python.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_044",
        "request": "Launch the browser, visit YouTube, and play the first result.",
        "expected": ["application", "browser"],
    },


    # ============================================================
    # 6. WEB — INDIRECT INFORMATION REQUESTS
    # ============================================================

    {
        "id": "stress_045",
        "request": "Can you find out what the latest Python version is?",
        "expected": ["web"],
    },
    {
        "id": "stress_046",
        "request": "Look online and tell me about the James Webb telescope.",
        "expected": ["web"],
    },
    {
        "id": "stress_047",
        "request": "What does the internet say about the latest NVIDIA GPUs?",
        "expected": ["web"],
    },
    {
        "id": "stress_048",
        "request": "Do a quick online lookup for the current JEE exam dates.",
        "expected": ["web"],
    },
    {
        "id": "stress_049",
        "request": "Find some information online about quantum computing.",
        "expected": ["web"],
    },
    {
        "id": "stress_050",
        "request": "Check online whether Python 3.14 has been released.",
        "expected": ["web"],
    },
    {
        "id": "stress_051",
        "request": "I want to know what's currently happening with AI research.",
        "expected": ["web"],
    },
    {
        "id": "stress_052",
        "request": "Look up the latest information about the OpenAI API.",
        "expected": ["web"],
    },


    # ============================================================
    # 7. BROWSER vs WEB BOUNDARIES
    # ============================================================

    {
        "id": "stress_053",
        "request": "Open Chrome and look up the latest NVIDIA news on Google.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_054",
        "request": "Find the latest NVIDIA news online and summarize it.",
        "expected": ["web"],
    },
    {
        "id": "stress_055",
        "request": "Go to Google and search for the latest JEE updates.",
        "expected": ["browser"],
    },
    {
        "id": "stress_056",
        "request": "Search the web for the latest JEE updates.",
        "expected": ["web"],
    },
    {
        "id": "stress_057",
        "request": "Open YouTube and find a physics lecture.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_058",
        "request": "Find a good physics lecture online.",
        "expected": ["web"],
    },


    # ============================================================
    # 8. FILESYSTEM — INDIRECT
    # ============================================================

    {
        "id": "stress_059",
        "request": "Where did I put my physics notes?",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_060",
        "request": "Hunt down the document I was working on yesterday.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_061",
        "request": "Find the PDF with my optics material.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_062",
        "request": "Show me what files are sitting in my Downloads folder.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_063",
        "request": "I can't remember where I saved my Python project.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_064",
        "request": "Locate the presentation I made last week.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_065",
        "request": "What kind of file is this?",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_066",
        "request": "Make a new folder for my physics work.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_067",
        "request": "Move those notes into my JEE folder.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_068",
        "request": "Make a copy of the physics notes.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_069",
        "request": "Get rid of that old temporary file.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_070",
        "request": "Tell me how large that project folder is.",
        "expected": ["filesystem"],
    },


    # ============================================================
    # 9. FILESYSTEM + APPLICATION
    # ============================================================

    {
        "id": "stress_071",
        "request": "Find my Python project and open it in VS Code.",
        "expected": ["filesystem", "application"],
    },
    {
        "id": "stress_072",
        "request": "Locate my physics PDF and open it.",
        "expected": ["filesystem", "application"],
    },
    {
        "id": "stress_073",
        "request": "Find the spreadsheet from yesterday and open it in Excel.",
        "expected": ["filesystem", "application"],
    },
    {
        "id": "stress_074",
        "request": "Track down my presentation and open it.",
        "expected": ["filesystem", "application"],
    },
    {
        "id": "stress_075",
        "request": "Find the folder containing my project and bring it up in File Explorer.",
        "expected": ["filesystem", "application"],
    },


    # ============================================================
    # 10. SYSTEM — INDIRECT
    # ============================================================

    {
        "id": "stress_076",
        "request": "The audio is way too loud. Bring it down.",
        "expected": ["system"],
    },
    {
        "id": "stress_077",
        "request": "I can barely hear anything. Turn the sound up.",
        "expected": ["system"],
    },
    {
        "id": "stress_078",
        "request": "Mute everything for a moment.",
        "expected": ["system"],
    },
    {
        "id": "stress_079",
        "request": "How much juice does my laptop have left?",
        "expected": ["system"],
    },
    {
        "id": "stress_080",
        "request": "Is my Wi-Fi actually connected?",
        "expected": ["system"],
    },
    {
        "id": "stress_081",
        "request": "How much memory is the machine using right now?",
        "expected": ["system"],
    },
    {
        "id": "stress_082",
        "request": "Is my laptop getting low on storage?",
        "expected": ["system"],
    },
    {
        "id": "stress_083",
        "request": "Turn Bluetooth on.",
        "expected": ["system"],
    },
    {
        "id": "stress_084",
        "request": "Make the display brighter.",
        "expected": ["system"],
    },
    {
        "id": "stress_085",
        "request": "How hot is the CPU running?",
        "expected": ["system"],
    },


    # ============================================================
    # 11. SYSTEM + APPLICATION
    # ============================================================

    {
        "id": "stress_086",
        "request": "Open Spotify and make the laptop quieter.",
        "expected": ["application", "system"],
    },
    {
        "id": "stress_087",
        "request": "Launch Discord and switch Bluetooth on.",
        "expected": ["application", "system"],
    },
    {
        "id": "stress_088",
        "request": "Close Spotify and mute the speakers.",
        "expected": ["application", "system"],
    },
    {
        "id": "stress_089",
        "request": "Start Chrome and turn the brightness up.",
        "expected": ["application", "system"],
    },
    {
        "id": "stress_090",
        "request": "Open VS Code and tell me how much RAM is being used.",
        "expected": ["application", "system"],
    },


    # ============================================================
    # 12. SCREEN — INDIRECT
    # ============================================================

    {
        "id": "stress_091",
        "request": "What am I looking at right now?",
        "expected": ["screen"],
    },
    {
        "id": "stress_092",
        "request": "Tell me what's currently visible on my display.",
        "expected": ["screen"],
    },
    {
        "id": "stress_093",
        "request": "Have a look at the screen and describe what's there.",
        "expected": ["screen"],
    },
    {
        "id": "stress_094",
        "request": "Capture what I'm seeing right now.",
        "expected": ["screen"],
    },
    {
        "id": "stress_095",
        "request": "Can you inspect the current display for me?",
        "expected": ["screen"],
    },


    # ============================================================
    # 13. SCREEN vs BROWSER
    # ============================================================

    {
        "id": "stress_096",
        "request": "Read the article currently open in Chrome.",
        "expected": ["browser"],
    },
    {
        "id": "stress_097",
        "request": "Look at the screen and tell me which application is visible.",
        "expected": ["screen"],
    },
    {
        "id": "stress_098",
        "request": "Tell me what's visible inside the webpage.",
        "expected": ["screen"],
    },
    {
        "id": "stress_099",
        "request": "Read the text from the webpage I'm currently viewing.",
        "expected": ["browser"],
    },
    {
        "id": "stress_100",
        "request": "Take a picture of what is currently on my monitor.",
        "expected": ["screen"],
    },


    # ============================================================
    # 14. MEMORY — INDIRECT
    # ============================================================

    {
        "id": "stress_101",
        "request": "Do you remember what kind of projects I like working on?",
        "expected": ["memory"],
    },
    {
        "id": "stress_102",
        "request": "What was that preference I told you about earlier?",
        "expected": ["memory"],
    },
    {
        "id": "stress_103",
        "request": "Keep in mind that I prefer dark interfaces.",
        "expected": ["memory"],
    },
    {
        "id": "stress_104",
        "request": "Don't forget that my study sessions start in the evening.",
        "expected": ["memory"],
    },
    {
        "id": "stress_105",
        "request": "What have you saved about my preferences?",
        "expected": ["memory"],
    },
    {
        "id": "stress_106",
        "request": "Update what you remember about my study schedule.",
        "expected": ["memory"],
    },


    # ============================================================
    # 15. SKILL — INDIRECT
    # ============================================================

    {
        "id": "stress_107",
        "request": "Turn the steps I just described into something reusable.",
        "expected": ["skill"],
    },
    {
        "id": "stress_108",
        "request": "Make that routine something I can run again later.",
        "expected": ["skill"],
    },
    {
        "id": "stress_109",
        "request": "Use my saved study setup.",
        "expected": ["skill"],
    },
    {
        "id": "stress_110",
        "request": "What reusable routines do I have?",
        "expected": ["skill"],
    },
    {
        "id": "stress_111",
        "request": "Check whether that workflow is valid before I use it.",
        "expected": ["skill"],
    },


    # ============================================================
    # 16. COMPUTER + SYSTEM
    # ============================================================

    {
        "id": "stress_112",
        "request": "Move the pointer over to the Wi-Fi icon.",
        "expected": ["computer"],
    },
    {
        "id": "stress_113",
        "request": "Click the Bluetooth icon in the taskbar.",
        "expected": ["computer"],
    },
    {
        "id": "stress_114",
        "request": "Use the mouse to click the volume control.",
        "expected": ["computer"],
    },


    # ============================================================
    # 17. LARGE 3–4 CAPABILITY REQUESTS
    # ============================================================

    {
        "id": "stress_115",
        "request": (
            "Get me ready for studying: open Chrome and VS Code, "
            "find my physics notes, and lower the volume."
        ),
        "expected": ["application", "filesystem", "system"],
    },
    {
        "id": "stress_116",
        "request": (
            "I'm starting a coding session. Bring up VS Code and Chrome, "
            "find my project folder, and show me what's currently on screen."
        ),
        "expected": ["application", "filesystem", "screen"],
    },
    {
        "id": "stress_117",
        "request": (
            "Open Spotify, put the sound at a reasonable level, "
            "turn Bluetooth on, and take a screenshot."
        ),
        "expected": ["application", "system", "screen"],
    },
    {
        "id": "stress_118",
        "request": (
            "Find my physics notes, open them, and tell me what is visible "
            "on my screen afterward."
        ),
        "expected": ["filesystem", "application", "screen"],
    },
    {
        "id": "stress_119",
        "request": (
            "Launch Chrome, find a JEE lecture on YouTube, open it, "
            "and tell me what's visible on the screen."
        ),
        "expected": ["application", "browser", "screen"],
    },


    # ============================================================
    # 18. LARGE 5–6 CAPABILITY REQUESTS
    # ============================================================

    {
        "id": "stress_120",
        "request": (
            "Get my study setup ready: open Chrome, VS Code and Spotify, "
            "find my physics notes, search YouTube for a lecture, "
            "lower the volume, and take a screenshot."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
        ],
    },
    {
        "id": "stress_121",
        "request": (
            "I'm working on my project. Launch VS Code and Chrome, "
            "locate the project folder, open it, search online for the "
            "documentation I need, and remember that I'm working on this project today."
        ),
        "expected": [
            "application",
            "filesystem",
            "web",
            "memory",
        ],
    },
    {
        "id": "stress_122",
        "request": (
            "Open Chrome, search YouTube for a physics lecture, "
            "find my physics notes, launch VS Code, lower the sound, "
            "and capture the current screen."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
        ],
    },
    {
        "id": "stress_123",
        "request": (
            "Bring up Chrome, Discord and VS Code, find my project files, "
            "search the web for the latest Python documentation, "
            "turn Bluetooth on, and remember that I'm working on Python today."
        ),
        "expected": [
            "application",
            "filesystem",
            "web",
            "system",
            "memory",
        ],
    },


    # ============================================================
    # 19. HUGE REALISTIC JARVIS REQUESTS
    # ============================================================

    {
        "id": "stress_124",
        "request": (
            "I'm about to start studying. Get everything ready for me: "
            "open Chrome, VS Code, Spotify and File Explorer, "
            "find the physics notes I was using yesterday, "
            "open the relevant folder, search YouTube for a wave optics lecture, "
            "put the volume at a comfortable level, turn Bluetooth on, "
            "take a screenshot, and remember that I'm studying physics tonight."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
            "memory",
        ],
    },

    {
        "id": "stress_125",
        "request": (
            "I'm starting work on my AI project. Open Chrome, VS Code, "
            "and File Explorer, locate the project I worked on yesterday, "
            "open the relevant files, look up the latest documentation online, "
            "keep the sound low, take a screenshot of the current setup, "
            "and remember that this is my current project."
        ),
        "expected": [
            "application",
            "filesystem",
            "web",
            "system",
            "screen",
            "memory",
        ],
    },

    {
        "id": "stress_126",
        "request": (
            "Set me up for my evening routine. Bring up Chrome, Spotify, "
            "Discord and VS Code, find the notes for today's work, "
            "search YouTube for something related to the topic, "
            "quiet the laptop, switch Bluetooth on, show me what is on screen, "
            "and use my saved study setup."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
            "skill",
        ],
    },

    {
        "id": "stress_127",
        "request": (
            "I need to get my whole workspace sorted. Launch Chrome, "
            "VS Code, Spotify, Discord, WhatsApp and File Explorer, "
            "find my latest project folder, search the internet for "
            "the documentation I need, open the relevant webpage in Chrome, "
            "reduce the volume, take a screenshot, and remember what I'm working on."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "web",
            "system",
            "screen",
            "memory",
        ],
    },

    {
        "id": "stress_128",
        "request": (
            "Prepare everything for my study session: find my physics material, "
            "open the folder containing it, start Chrome and VS Code, "
            "look for a suitable lecture on YouTube, make the laptop quieter, "
            "check that Bluetooth is available, take a picture of my screen, "
            "and run my saved study routine."
        ),
        "expected": [
            "filesystem",
            "application",
            "browser",
            "system",
            "screen",
            "skill",
        ],
    },


    # ============================================================
    # 20. TRICKY BOUNDARY CASES
    # ============================================================

    {
        "id": "stress_129",
        "request": "The browser is already open. Take me to YouTube.",
        "expected": ["browser"],
    },
    {
        "id": "stress_130",
        "request": "Chrome isn't open yet. Start it and then take me to YouTube.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_131",
        "request": "Find my notes and tell me what they contain.",
        "expected": ["filesystem"],
    },
    {
        "id": "stress_132",
        "request": "Open Chrome and tell me what the webpage looks like.",
        "expected": ["application", "screen"],
    },
    {
        "id": "stress_133",
        "request": "Tell me what the webpage says.",
        "expected": ["browser"],
    },
    {
        "id": "stress_134",
        "request": "Tell me what the screen looks like.",
        "expected": ["screen"],
    },
    {
        "id": "stress_135",
        "request": "Find information online and don't open a browser.",
        "expected": ["web"],
    },
    {
        "id": "stress_136",
        "request": "Open the browser and interact with the website yourself.",
        "expected": ["application", "browser"],
    },
    {
        "id": "stress_137",
        "request": "Open Calculator and click the buttons needed to calculate 12 times 8.",
        "expected": ["application", "computer"],
    },
    {
        "id": "stress_138",
        "request": "Find the calculator application and launch it.",
        "expected": ["application"],
    },


    # ============================================================
    # 21. VERY NATURAL MULTI-TASK COMMANDS
    # ============================================================

    {
        "id": "stress_139",
        "request": (
            "Alright, I'm ready to study. Get Chrome and VS Code up, "
            "dig out those physics notes from yesterday, pull up a lecture "
            "on YouTube, turn the sound down a little, and let me see what "
            "my screen looks like."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
        ],
    },

    {
        "id": "stress_140",
        "request": (
            "I'm switching over to coding now. Get my editor and browser open, "
            "find the project I was working on, look up whatever documentation "
            "is current, keep the laptop quiet, and remember that this is "
            "what I'm working on today."
        ),
        "expected": [
            "application",
            "filesystem",
            "web",
            "system",
            "memory",
        ],
    },

    {
        "id": "stress_141",
        "request": (
            "Can you sort out my workspace? Bring up Discord, Chrome and VS Code, "
            "locate the files for my project, open the website I need, "
            "make the audio less annoying, and give me a snapshot of the setup."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "system",
            "screen",
        ],
    },

    {
        "id": "stress_142",
        "request": (
            "I want to repeat the same study setup as before. "
            "Find my physics stuff, open Chrome and the editor, "
            "get a lecture going, lower the volume, and run the routine "
            "I saved for this."
        ),
        "expected": [
            "filesystem",
            "application",
            "browser",
            "system",
            "skill",
        ],
    },

    {
        "id": "stress_143",
        "request": (
            "Before I start, open all the apps I need, find the material "
            "I was studying yesterday, search for something useful online, "
            "bring the relevant webpage up in Chrome, adjust the sound, "
            "check the screen, and remember what today's session is about."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "web",
            "system",
            "screen",
            "memory",
        ],
    },


    # ============================================================
    # 22. MAXIMUM-COMPLEXITY REQUESTS
    # ============================================================

    {
        "id": "stress_144",
        "request": (
            "Get my entire study workspace ready: launch Chrome, VS Code, "
            "Spotify, Discord and File Explorer; locate my physics notes "
            "from yesterday; open the folder; search the web for the latest "
            "information about wave optics; open the useful result in Chrome; "
            "find a suitable YouTube lecture; lower the volume; turn Bluetooth "
            "on; take a screenshot; remember that I'm studying wave optics "
            "tonight; and run my saved study routine."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "web",
            "system",
            "screen",
            "memory",
            "skill",
        ],
    },

    {
        "id": "stress_145",
        "request": (
            "I'm moving into my AI project now. Start Chrome, VS Code, "
            "File Explorer, Discord and Spotify; find the project folder "
            "and open it; search online for current documentation; open "
            "the relevant documentation in the browser; check what's visible "
            "on the screen; turn the sound down; make sure Bluetooth is on; "
            "remember that this is today's main project; and use my saved "
            "project setup routine."
        ),
        "expected": [
            "application",
            "browser",
            "filesystem",
            "web",
            "system",
            "screen",
            "memory",
            "skill",
        ],
    },
]

ROUTING_RULES = """
You are JARVIS's semantic capability router.

Identify EVERY capability genuinely required to fulfill the user's request. Evaluate by operations, not keywords. Use the most specific capability available. Return ONLY the capability names.

AVAILABLE:
application, browser, computer, filesystem, screen, web, system, memory, skill

DEFINITIONS:

application:
Launch, open, close, or bring up desktop applications.
Examples: open VS Code, launch Chrome, close Spotify.

filesystem:
Find, locate, read, create, copy, move, delete, or inspect files/folders.
If a file/folder is found and then explicitly opened in an application, use
filesystem + application.
"Find my spreadsheet and open it in Excel" → filesystem + application

computer:
Generic mouse/keyboard control of ordinary desktop applications.
Use only for explicit typing, clicking, pressing keys, scrolling, or mouse
movement. Never add computer merely because another capability may internally
use mouse/keyboard control.

browser:
Interact with a browser or webpage: navigate, search within a website,
click, type, scroll, read, inspect, or open web results.
Launching the browser alone is application.

web:
Retrieve information from the internet without browser UI interaction:
online research, news, facts, documentation, or information retrieval.

screen:
Visually inspect what is currently displayed: screenshots, visible content,
appearance, or what something looks like.

system:
OS/hardware controls or information: volume, brightness, battery, CPU, RAM,
storage, network, Wi-Fi, Bluetooth, lock, sleep, restart, shutdown.

memory:
Remember, recall, or update persistent user information.

skill:
Discover, create, validate, or execute an explicit reusable JARVIS
skill/workflow/routine.

KEY BOUNDARIES:

APPLICATION vs COMPUTER:
"Open Notepad" → application
"Open Notepad and type hello" → application + computer
"Launch Calculator and press 5" → application + computer

FILESYSTEM vs APPLICATION:
Finding/reading/managing files or folders → filesystem.
Opening a located file/folder in an application → filesystem + application.
Finding or launching an application itself → application, not filesystem.

BROWSER vs APPLICATION:
"Open Chrome" → application
"Open Chrome and go to YouTube" → application + browser

BROWSER vs WEB:
Use browser when the user interacts with a browser, webpage, or named website.
Use web when the user only wants internet information without browser UI.

"Search online for Python documentation" → web
"Search Google for Python documentation in Chrome" → application + browser
"Search YouTube for a physics lecture" → browser
"Open YouTube and click a video" → application + browser
"Find the latest documentation and open it in Chrome" → web + browser

Do NOT classify a named website as web merely because information is being
searched there. If the task involves YouTube, Google, Gmail, Wikipedia, or
another website being navigated/interacted with, use browser.

SCREEN vs BROWSER:
"What does the webpage look like?" → screen
"What's visible on my screen?" → screen
"What's visible inside the webpage?" → screen
"What does the webpage say?" → browser
"Read the webpage" → browser
If both visual inspection and webpage interaction/content are explicitly
requested, use screen + browser.

SPECIALIZATION:
Prefer specialized capabilities over generic computer.
Clicking a webpage button → browser, not browser + computer.
Opening a file → filesystem/application, not computer.

MULTI-TASK:
Break the request into individual operations and include EVERY capability
genuinely required. Do not omit a capability because another capability is
also present.

Do not add capabilities merely because a keyword is present. Determine what
JARVIS actually needs to perform.

SKILL vs MEMORY:
skill = explicit reusable/saved workflow or routine.
memory = persistent user information.

"Run my saved study setup" → skill
"Remember that I study physics" → memory
Do not add skill to ordinary multi-step tasks.
Do not use memory for saved workflows.

FINAL RULE:
Return ONLY the final capability list.
"""

def extract_json(text):
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)

        if not match:
            raise

        return json.loads(match.group(0))


def classify_batch(batch):
    batch_prompt = f"""
{ROUTING_RULES}

Analyze every test case below.

Return exactly this JSON structure:

{{
    "results": [
        {{
            "id": "test_id",
            "capabilities": ["category1", "category2"]
        }}
    ]
}}

Rules:
- Return one result for every test case.
- Do not omit any test case.
- Do not include explanations.
- Return ONLY valid JSON.
- Capability order does not matter.

TEST CASES:

{json.dumps(
    [
        {
            "id": case["id"],
            "request": case["request"],
        }
        for case in batch
    ],
    indent=2,
)}
"""

    max_retries = 5

    for attempt in range(1, max_retries + 1):
        try:
            response = provider.generate(batch_prompt)

        except RateLimitError as error:
            print(
                f"  Groq rate limit reached "
                f"(attempt {attempt}/{max_retries})."
            )

            retry_after = 15

            print(
                f"  Waiting {retry_after} seconds before retrying..."
            )

            time.sleep(retry_after)
            continue

        if not response.strip():
            print(
                f"  Empty response from Groq "
                f"(attempt {attempt}/{max_retries}). Retrying..."
            )
            time.sleep(3)
            continue

        try:
            return extract_json(response)

        except (json.JSONDecodeError, ValueError) as error:
            print(
                f"  Invalid JSON from Groq "
                f"(attempt {attempt}/{max_retries}). Retrying..."
            )
            print(f"  Parser error: {error}")
            time.sleep(3)

    raise RuntimeError(
        "Groq failed to return valid JSON after 3 attempts."
    )

BATCH_SIZE = 4

all_results = []

for start in range(0, len(TEST_CASES), BATCH_SIZE):
    batch = TEST_CASES[start:start + BATCH_SIZE]

    print(
        f"Running batch "
        f"{start // BATCH_SIZE + 1}/"
        f"{(len(TEST_CASES) + BATCH_SIZE - 1) // BATCH_SIZE} "
        f"({len(batch)} tests)..."
    )

    data = classify_batch(batch)

    if not isinstance(data, dict):
        raise RuntimeError("Groq returned an invalid batch structure.")

    batch_results = data.get("results")

    if not isinstance(batch_results, list):
        raise RuntimeError(
            "Groq response does not contain a valid 'results' list."
        )

    all_results.extend(batch_results)


results = {
    item["id"]: item["capabilities"]
    for item in all_results
}


passed = 0
failed = 0


print()
print("=" * 70)
print("JARVIS SEMANTIC CAPABILITY ROUTER TEST")
print("=" * 70)
print()


for case in TEST_CASES:
    actual = results.get(case["id"])
    expected = case["expected"]

    actual_set = set(actual or [])
    expected_set = set(expected)

    if actual_set == expected_set:
        status = "PASS"
        passed += 1
    else:
        status = "FAIL"
        failed += 1

    print(f"[{status}] {case['id']}")
    print(f"  Request : {case['request']}")
    print(f"  Expected: {expected}")
    print(f"  Actual  : {actual}")
    print()


print("=" * 70)
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
print(f"TOTAL : {len(TEST_CASES)}")
print("=" * 70)