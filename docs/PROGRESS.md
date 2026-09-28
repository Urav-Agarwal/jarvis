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

## PHASE 1 COMPLETE (all suites green, committed)

**DONE**
- assistant/session.py: DORMANT->ACTIVE->substates machine; idle timeout 300 s
  (session.idle_timeout_seconds in settings.yaml); busy_check blocks sleep; no exchange cap.
- listen_and_process rewritten session-driven; silence rounds hold; go_to_sleep ends;
  idle farewell spoken once; interrupts keep the session alive.
- Greeting: briefing once per boot / 4 h idle; chime on other wakes; 1.2 s wake refractory.
- Barge-in: 0.7 s mic bursts + TTS duck_event (volume to 20% while judging) — fixes
  "hey jarvis while speaking"; duck cleared in finally.
- Budgeted loop: agent.max_reasoning_steps=12 (clamp 25) replaces fixed 4.
- CRITICAL: AgentBrain.think() dropped `then` on actions — production loop never chained
  steps; fixed + regression-tested (real 6-step chain).
- Did-you-mean resolver: open X -> fuzzy apps+shortcuts; "open comment browser" ->
  "Did you mean Comet, sir?" -> yes -> Comet opened (LIVE verified); narrow guard so
  profile repairs/diagnostics phrasings fall through to the brain.
- tests/test_phase1.py; all 9 suites + UI smoke green.

**NEXT (Session A of continuation prompt — audio/wake verification)**
- A1 scripts/audio_doctor.py: device listing, test tone, TTS through ElevenLabs AND Piper,
  peak amplitudes, duck restore check, red banner on TTS failure.
- A2 session transition log data/logs/session.log + end-to-end 10-min no-sleep simulation.
- A3 wake doctor: RMS meter + score logging, AGC, sensitivity config, streaming wake thread.

**OPEN PROBLEMS**
- User reports: cannot hear JARVIS speak (A1 — root cause not yet found, doctor first),
  still sleeps early (A2 — session machine exists; runtime path must be verified),
  must SHOUT the wake word (A3 — gain/threshold/streaming suspected).
- Piper .onnx model files may be missing from disk (only .onnx.json in git listing seen).
- Untracked *.txt dumps in root still present (user to delete).

---

## SILENT-REPLIES REGRESSION FIXED (Session B paused; voice first)

**ROOT CAUSE (evidence: data/boot_log.txt)**
- Every exchange raised AttributeError: 'Orchestrator' object has no
  attribute 'stop_listener_enabled' inside _speak_until_done — BEFORE
  TTS started. runtime_log showed 'Listener loop error' + exchange death.
- Cause: during the session-machine edit, _on_kill_switch was spliced
  into __init__ mid-file, so the old __init__ tail (speaking,
  stop_listener_enabled, _last_activity, restart-flag cleanup) became
  part of _on_kill_switch's body. Fresh Orchestrator = missing attrs =
  silent replies.
- NOT the duck logic, NOT the device selection, NOT the waveform/UI
  (no UI exists yet) — verified by git diff f629c1e..178709b on audio/.

**FIX**
- Boot tail moved back into __init__; _on_kill_switch now only handles
  its own job. Boot sanity check raises at startup if any reply-path
  attribute is missing (loud failure instead of mute operation).
- REAL playback test: Orchestrator()._speak_until_done('...') played
  through speakers; barge-in mic heard JARVIS's own voice ('BARGE-IN
  CHECK: This is the real thing') — acoustic confirmation.
- All 10 suites green. Committed 5c17839.

**NEXT: Session B (UI) — resume item 1 (orb), then panels, themes,
tray/mini mode, screenshots. Latency instrumentation (app/latency.py
trace + entity cache commit 629429f) already landed earlier this session.

---

## MIC GATE RECALIBRATED for the fixed mic (v4.1.2, commit c4b6ccd)

**EVIDENCE (data/runtime_log.txt + mic_debug.log design)**
- Wake scores with new mic: 0.96/0.48/0.43/0.29 at gain 1.0 — detector
  hears fine now; old AGC 25x risked amplifying room noise.
- 'Recording time: 10.18-10.23s' repeatedly = utterances ran to
  max_duration (old silence logic + followup loops: FOLLOW-UP 'So',
  'I cannot hear'...).
- 'I cannot hear that' string does NOT exist anywhere in code — it was
  the LLM's own reply to garbage/empty utterances reaching the brain.

**FIXES**
- Microphone: floor = median of first 0.5 s (locked); gate = floor*3
  clamped [0.012, 0.045] (config audio.speech_gate_min/max); utterance
  ends after 0.7 s below gate; normalization ONLY when peak < 0.05
  (strong 0.2-0.3 captures pass untouched); end-reason + per-frame
  decisions logged to data/logs/mic_debug.log.
- Wake AGC: gain 1.0 below rms 0.01 (no noise amplification), cap 2.0.
- Wake flow: chime ONLY (no spoken 'Yes, sir?'); no greeting when the
  session is already ACTIVE; wake ignored while speaking (barge-in owns
  that); refractory kept.
- 'Sorry, I didn't catch that.' spoken at most ONCE per session-loop,
  ONLY when STT got real audio and returned empty.
- tests/test_mic_gate.py (synthetic audio): noisy-room phrase ends <2.5s
  (not max_duration), trailing silence ends capture <3s, noise-only
  captures nothing, quiet-mic compat, AGC noise floor, chime-only wake,
  wake-ignored-while-speaking. ALL 11 SUITES GREEN.

**NEXT: resume Session B (UI): orb -> panels -> themes/tray ->
screenshots in docs/ui/. Watch data/logs/mic_debug.log on the user's
next live exchange to confirm end-of-utterance timing (~1s after speech).

---
