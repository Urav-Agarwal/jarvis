# JARVIS V4 CHANGELOG

## Phase 1 — Session + Voice Engine (this commit)

### Fixed (user-reported v3 bugs: sleep, repeated greetings, multi-step)
- **Session state machine** (`assistant/session.py`, NEW): DORMANT ->
  ACTIVE -> (LISTENING|THINKING|ACTING|SPEAKING) -> ACTIVE ... ->
  DORMANT. No exchange cap (the old 4-exchange max is gone); silence
  inside a session loops back to the mic instead of sleeping. Sleep
  only on explicit dismissal ("that's all" / self shutdown-restart)
  or the configurable idle timeout (`session.idle_timeout_seconds`,
  default 300 s) with NOTHING pending. Busy check (confirmations,
  drafts, contact picks, teaching saves, recorder, speech) blocks
  sleep at any idle time. One spoken farewell ("I'll be here if you
  need me, sir.") when the session ends from idle — never mid-task.
- **`listen_and_process` rewritten** to be session-driven: silence
  rounds keep the session; `go_to_sleep`/shutdown/restart end it;
  interrupts (`stop` / `hey jarvis` mid-think) keep it alive.
- **Greeting sanity**: briefing once per boot (or after 4+ hours
  idle — `_GREETING_TTL_SECONDS = 4*3600`); every other wake gets a
  short two-note **chime** instead of another spoken ack; wake-word
  refractory (1.2 s) swallows detector echo re-triggers.
- **Barge-in while speaking (2.4)**: the stop-listener now records in
  0.7 s bursts and sets the TTS `duck_event` the moment any sound is
  detected — JARVIS ducks to ~20% volume while judging the burst, so
  the user's "hey Jarvis" is no longer masked by his own voice.
  Ducking clears in a `finally` (never left stuck).
- **Budgeted step loop**: `agent.max_reasoning_steps` (default 12,
  clamp 1..25) replaces the fixed 4-step cap.
- **CRITICAL brain fix**: `AgentBrain.think()` DROPPED the `then`
  field on action decisions — in production the loop never continued
  past the first tool call (only the fake-reasoner tests saw chained
  steps). Now propagated; test_phase1 runs a real 6-step chain.
- **Did-you-mean resolver (2.6)**: `_handle_open_request` — rapidfuzz
  over Start-Menu apps + desktop shortcuts. Strong match opens
  directly through the executor; medium match asks "Did you mean
  Comet, sir?" and the next "yes" opens it (pending slot cleared on
  any non-yes). Verified live: "open comment browser" -> "Did you
  mean Comet, sir?" -> "yes" -> Comet launched. Deliberately narrow:
  >3 words, profile/multi-clause/diagnostics phrasings fall through
  to the brain (regression-tested against the profile repair).

### Tests
- `tests/test_phase1.py` (NEW): state machine (busy blocks sleep,
  dismissal mid-task, 50-exchange hold), orchestrator integration
  with fake mic/TTS (silence rounds hold, go_to_sleep ends, idle
  farewell), chime + refractory wake path, 6-step budgeted chain.
- Full suite (9) + UI smoke green.

### Known gaps (next sessions)
- Audio hardware verification + wake sensitivity (Session A of the
  continuation prompt).
- UI overhaul, persona layer, screen awareness, connectors.
