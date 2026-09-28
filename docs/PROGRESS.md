# JARVIS V4 — PROGRESS LOG

Updated after each to-do. Format: DONE / NEXT / OPEN PROBLEMS.

---

## Session started (v4 kickoff)

**DONE**
- Repo surveyed; `docs/V4_PLAN.md` written; deps installed (send2trash, rapidfuzz, keyboard).
- `tools/computer_controller.py` REWRITTEN and live-tested: per-monitor DPI awareness,
  eased glide move_mouse(duration), real double-click (clicks param finally honored — v3
  silently ignored it), drag_mouse, abort_event kill-switch hook in every motion.
- `tools/shortcuts.py` (NEW): desktop + Public Desktop + SHGetFolderPath desktop enumeration;
  rapidfuzz matcher; open_shortcut(). LIVE-TESTED on real desktop: 'instagram'->Instagram 100,
  'comment'->Comet 83.3 (this also feeds bug 2.6's did-you-mean resolver).
- Catalogue: computer.mouse_double_click / mouse_drag / open_shortcut definitions added.
- ToolRuntime: handlers registered; computer.mouse_click now honors clicks; _open_shortcut
  lazy-imports shortcuts (no import cost at boot).
- Time reflex (2.2): `_TIME_QUESTION` regex + `_handle_time_question` in AgentRuntime.process()
  right after the sleep check — zero LLM, zero routing; router _SYSTEM_TERMS extended with
  time/date/day phrases; verified: all four phrasings -> ['system'] and reflex answers first.

**NEXT**
- Phase 1: session state machine (no mid-convo sleep), barge-in while speaking, chime on
  re-wake, budgeted step loop, did-you-mean resolver.
- Relaunch JARVIS and live-test the mouse glide / double-click / shortcut launch.

**OPEN PROBLEMS**
- Untracked `*.txt` dumps in repo root — not committing; flagged for user.
- str_replace on CRLF files is unreliable — verify with py_compile + grep after each edit.
- write_file cannot overwrite existing files in this env — use str_replace full-file replace.
- Time reflex must stay AFTER the reflex layer (pending-confirmation answers first) —
  regression covered by test_interrupt_and_confirm.py.

---

## PHASE 0 COMPLETE (all suites green)

**DONE**
- computer_controller.py: DPI aware, glide, real double-click, drag, abort hook (live-tested).
- tools/shortcuts.py + catalogue/runtime wiring; 'comment'->Comet 83.3 on real desktop.
- Time/date reflex (zero LLM) + router terms; regression lesson: reflex order matters.
- security/permissions.py + config/permissions.yaml (tiers, HIGH always confirms).
- security/audit.py (data/audit.jsonl, redaction, rotation, summarize_today).
- ConfirmationManager: 30 s expiry, FIFO queue, strict yes/no; executor audits auto+confirmed.
- filesystem delete: send2trash only; protected paths enforced (Downloads still cleanable).
- security/kill_switch.py: hotkey + voice phrase, abort fan-out, auto-clear.
- Provider honors a LIST of abort events (thinking_abort + kill switch both work).
- tests/test_phase0.py (50+ checks); ALL 8 suites + UI smoke pass.
- One legacy test updated deliberately (time reflex is zero-LLM now) — documented in changelog.

**OPEN PROBLEMS**
- Untracked `*.txt` dumps in repo root — not committing; flagged for user.
- Router public API is route_capabilities() (not route()); noted for tests.
- str_replace on CRLF files is unreliable in this env — prefer write_file for rewrites and
  verify with py_compile + grep after each edit.

---
