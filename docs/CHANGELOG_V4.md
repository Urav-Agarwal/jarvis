# JARVIS V4 CHANGELOG

## Phase 0 — Stabilize + Safety Foundation (this commit)

### Fixed (user-reported v3 bugs)
- **2.1 Desktop shortcut / invisible mouse**
  - `tools/computer_controller.py`: per-monitor DPI awareness at
    construction (`SetProcessDpiAwareness(2)`) so vision coordinates
    match physical pixels on scaled displays.
  - `move_mouse(x, y, duration=0.45)` now GLIDES with ease-in-out
    interpolation (visible motion instead of a teleport).
  - `click_mouse(button, clicks)` honors `clicks`; `clicks=2` is a
    real double-click (two down/up pairs 90 ms apart). v3 silently
    ignored the parameter — "double-click the Instagram shortcut"
    clicked once at best.
  - NEW `drag_mouse(x, y)` (press, glide, release).
  - Every motion checks `ComputerController.abort_event` (kill switch).
  - NEW `tools/shortcuts.py`: enumerate user + Public Desktop
    `.lnk`/`.url`, rapidfuzz match, `os.startfile` the target.
    NEW catalogue tools: `computer.open_shortcut`,
    `computer.mouse_double_click`, `computer.mouse_drag`.
- **2.2 "What time is it?" failed**
  - Zero-LLM time/date/day reflex in `AgentRuntime.process()`
    (`_handle_time_question`) — answers from the local clock
    instantly; also added time/date/day terms to the router's
    `_SYSTEM_TERMS`.
- **2.6 groundwork** — the shortcut fuzzy resolver already maps
  "comment" -> "Comet" (verified on the real desktop, score 83.3);
  the did-you-mean clarify flow lands in Phase 1.

### Safety foundation (3.A)
- `security/permissions.py` (was EMPTY): READ/LOW/MEDIUM/HIGH tiers,
  `config/permissions.yaml` overrides, HIGH always confirms.
- `security/audit.py` (was EMPTY): append-only `data/audit.jsonl`,
  secret redaction, size-capped rotation, `summarize_today()` for
  "what did you do today?". Executor audits every auto/confirmed run.
- `security/confirmations.py`: 30-second expiry, FIFO queue (multiple
  pending actions), strict whole-utterance yes ("ok so what time is
  it" can never execute a queued action), clear-no cancellation.
  Executor `request_confirmation` read-back names the exact action.
- `tools/filesystem_observer.delete`: Recycle Bin only (send2trash);
  refuses drive roots, C:\Windows, Program Files, the user profile
  root, the JARVIS project tree, and any .git directory.
- `security/kill_switch.py` (NEW): Ctrl+Alt+Shift+J global hotkey +
  "Jarvis, emergency stop" voice phrase; aborts mouse motion, LLM
  calls (provider polls a list of abort events), speech, and pending
  state; auto-clears after a grace period.

### Tests
- `tests/test_phase0.py` (NEW): 50+ checks — time reflex, shortcut
  matching, strict confirmations, expiry/queue, tiers, audit
  redaction, protected paths, kill switch, mouse contract.
- `tests/test_interrupt_and_confirm.py`: the "other input cancels"
  case now uses "what is the capital of france" — time questions are
  a zero-LLM reflex in v4, so the scripted LLM response would never
  be consumed (intentional behavior change).

### Config/deps
- Added `config/permissions.yaml`; deps: `send2trash`, `rapidfuzz`,
  `keyboard`.

### Known gaps (next phases)
- Session state machine (no mid-conversation sleep): Phase 1.
- Barge-in while speaking, chime instead of repeated greeting: Phase 1.
- Did-you-mean entity resolver for STT mishears: Phase 1.
- Personality layer: Phase 2. WhatsApp bridge: Phase 5.
