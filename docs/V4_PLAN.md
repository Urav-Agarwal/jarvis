# JARVIS V4 PLAN

## Current architecture (v3, verified from source)

```
app/main.py                 JarvisWindow + AssistantBridge + listener thread; tray; single-instance port 57654
assistant/orchestrator.py   Orchestrator: wake word loop, listen()/listen_and_process(max_followups),
                            _interrupt_watcher (stop/"hey jarvis" while thinking), thinking_abort Event,
                            greeting TTL (90 s), _listen_followup, TTS barge-in (interrupt_speech)
ai/agent_runtime.py         AgentRuntime.process(): sleep check -> ReflexLayer -> deterministic handlers
                            (message fast-path, profile request, artifact follow-ups, teaching) ->
                            BrainV3 loop. _executor() = THE single gate (confirmations + receipts)
ai/brain.py                 BrainV3: reason -> act -> observe loop, MAX_STEPS=4, ReflexLayer,
                            _compose_and_judge, plans with gated-step parking, InterruptedError re-raise
ai/agent.py                 AgentBrain (reasoner): think() -> ONE decision JSON; compose(); _extract_json
ai/provider.py              GroqProvider; abort_event -> InterruptedError from generate()
router/capability_router_v2.py  deterministic capability routing + LLM fallback for ambiguity
ai/tool_catalogue.py        ToolDefinition list (~80 tools) with risk + confirmation_required
ai/tool_runtime.py          ToolRuntime: tool implementations
security/confirmations.py   ConfirmationManager — ONE slot, no expiry, loose yes-matching  (UPGRADE)
security/audit.py           EMPTY  (FILL)
security/permissions.py     EMPTY  (FILL)
tools/                      applications, computer_controller (SetCursorPos = teleport; no double-click),
                            filesystem_observer.delete = shutil.rmtree (DANGEROUS), whatsapp (window
                            automation, brittle), mouse.py EMPTY, skills, recorder, ...
audio/                      wake_word (openwakeword, 2-frame confirm), microphone, speech_to_text, tts
config/settings.yaml        audio, wake_word, agent (tone, context_turns=4, max_consecutive_failures)
data/                       memory.json, skills.json, runtime_log.txt, audit (new)
```

Kept as-is (user approved): capability router idea, THE JUDGE receipt rule, single executor gate,
learned skills, action recorder, clean_for_speech, offline tests.

## Phase plan and file changes

### PHASE 0 — Stabilize + safety foundation
| Area | Files | Change |
|---|---|---|
| 2.1 mouse | tools/computer_controller.py | DPI awareness (SetProcessDpiAwareness(2)); smooth eased glide move_mouse(duration); click_mouse(button, clicks) with real double-click timing; drag_mouse |
| 2.1 shortcuts | tools/shortcuts.py (NEW), ai/tool_catalogue.py, ai/tool_runtime.py | enumerate Desktop + Public Desktop .lnk/.url, fuzzy match, os.startfile; tools computer.open_shortcut, computer.mouse_double_click, computer.mouse_drag |
| 2.2 time | assistant/orchestrator.py, router/capability_router_v2.py | zero-LLM time/date/day reflex; time/date/day terms in _SYSTEM_TERMS |
| 2.5 greeting | assistant/orchestrator.py | greeting once per boot (TTL 4 h), chime on re-wake; verify no re-greet within session |
| 3.A safety | security/permissions.py, security/audit.py, security/confirmations.py | READ/LOW/MEDIUM/HIGH tiers (config/permissions.yaml); append-only data/audit.jsonl; ConfirmationManager: 30 s expiry, queue, strict whole-utterance yes, exact-action read-back |
| 3.A delete | tools/filesystem_observer.py | send2trash; refuse drive roots, C:\Windows, Program Files, user profile root, project dir, .git |
| 3.A kill switch | scripts + assistant | global hotkey Ctrl+Alt+Shift+J + "emergency stop" phrase -> cancel all, safe idle |
| deps | requirements.txt | send2trash, rapidfuzz, keyboard |
| tests | tests/test_phase0.py | time reflex, shortcut fuzzy match, tiers, audit, confirmation expiry/queue/strict-yes, protected delete, glide math |

### PHASE 1 — Session + voice engine
- assistant/session.py (NEW): state machine DORMANT->ACTIVE->(LISTENING|THINKING|ACTING|SPEAKING)->ACTIVE; idle_timeout 300 s (settings.yaml session.idle_timeout_seconds); no max exchanges; never sleeps mid-task/pending question.
- app/main.py + orchestrator: replace max_followups loop with session-aware hold; "that's all/bye" ends session.
- Barge-in 2.4: duck TTS on candidate, higher wake threshold while speaking, kill stream within ~300 ms.
- Budgeted loop: BrainV3 max_steps from config (25), max_consecutive_failures respected, progress announcements for long tasks.
- STT vocabulary: app names + browser names + contacts into whisper initial_prompt/hotwords; rapidfuzz resolver + "Did you mean X?" clarify.

### PHASE 2 — Personality + memory
- config/persona.yaml, ai/persona.py: every spoken reply routed through persona; dry-witted butler, no status-printer phrases; one smart clarifying question when ambiguous/destructive; occasional next-step offers.
- assistant/memory.py: profile + episodic memory (SQLite FTS5), "forget X", "what do you know about me", privacy switch.
- Proactive v2: daily briefing, battery/CPU/reminder alerts, quiet hours.

### PHASE 3 — Full computer control
- pywinauto/uiautomation-first window control, vision fallback; window management tools; settings toggles; computer.driver plan->screenshot->verify loop with AUTONOMOUS CONTROL indicator; dictation mode; document Q&A.

### PHASE 4 — Always online
- scripts/install_startup.py via schtasks (+uninstall); tray start; supervisor watchdog; wake word before UI; offline fallback path.

### PHASE 5 — Messaging
- tools/messaging/base.py MessagingProvider; WhatsApp via Playwright persistent profile (decision recorded); read unread/reply/send file with HIGH-tier confirm; email later.

### PHASE 6+ — Integrations hub, UI/Galaxy, hardening (see master prompt).

## Risks
- Mouse click verification needs vision round-trips (latency) — mitigate with quick post-act window-title check first, screenshot fallback.
- Barge-in echo: mic hears JARVIS's TTS; without AEC use threshold + ducking; accept some false negatives.
- WhatsApp automation ToS risk — prefer Playwright+QR (user's own account) with rate caps; document honestly.
- keyboard global hotkey can fail without admin — guarded try/except, voice phrase always available.
- v3 test contracts must not regress (executor-side gate, legacy question mapping).
