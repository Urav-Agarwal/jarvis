# JARVIS — Personal Desktop AI Assistant

JARVIS is a local Windows desktop AI agent. You speak or type naturally;
it determines what operations are required, selects the right tools, plans
multi-step workflows, executes them on your computer, and reports back.

## What JARVIS can do

- **Applications** — open/close apps (Start Menu discovery + Store-app fallbacks)
- **Browser** — open browsers with profiles, navigate, refresh, back/forward,
  read page text, get the active tab URL
- **Files** — search, read, create, copy, move, delete (confirmation-gated),
  inspect, open
- **System** — volume, brightness, battery, CPU, RAM, storage, Wi-Fi,
  Bluetooth, GPU, network; lock/sleep/restart/shutdown (confirmation-gated)
- **Screen** — screenshots and visual question-answering about your screen
- **Web** — search the internet and fetch pages without touching a browser
- **Memory** — "remember that ..." persists in `data/memory.json`
- **Skills** — save reusable workflows ("run my study setup") in
  `data/skills.json`; confirmation-required tools are never auto-executed
- **Voice** — "Hey JARVIS" wake word → speech → answer, fully local

## Architecture

```
voice/text → Orchestrator → AgentRuntime
                             ├─ CapabilityRouter (deterministic-first,
                             │        LLM only for ambiguity)
                             ├─ AgentBrain (question/action/plan decision,
                             │        capability-filtered tool menu)
                             ├─ ToolRuntime (60+ registered tools)
                             └─ ConfirmationManager (high-risk gating)
```

The capability router classifies requests into nine capabilities
(application, browser, computer, filesystem, screen, web, system, memory,
skill) by **operation, not keywords**, then the agent picks concrete tools
from only those domains. Most requests route with zero LLM calls.

## Setup

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```
GROQ_API_KEY=your_key_here
```

Run:

```powershell
python -m app.main
```

Say "Hey JARVIS", then speak naturally: *"Find my physics notes and open
them"*, *"How much battery do I have?"*, *"Open Chrome and go to YouTube"*,
*"Remember that I'm studying wave optics"*, *"Run my study setup"*.

## Tests

```powershell
# Offline (no API cost):
python -m tests.test_capability_router_v2
python -m tests.test_plan_parser
python -m tests.test_agent_plan

# Groq-backed (uses quota):
python -m tests.test_capability_stress
```

## Notes

- Windows 10/11, developed and tested on Windows 11.
- The LLM decides *what* to do; deterministic code decides *what is allowed*.
  High-risk actions always require explicit confirmation.
