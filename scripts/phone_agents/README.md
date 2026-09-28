# Jarvis Phone Pack — Retell Call Agents

Adapted from Zubair Trabzada's Jarvis Phone Pack for the local
Freebuff JARVIS build. These are the three Retell AI agent scripts
(booking, inquiry, code-gated receptionist) plus setup rules, so
JARVIS can make real phone calls on your behalf.

## One-time setup

1. Retell AI account + a phone number (retellai.com). Buy the
   Verified Phone Number add-on on day one — it kills the
   "Spam Likely" caller ID.
2. Create three agents on Retell and paste the scripts below into
   the Agent Prompt of each (Scripts 1-3 in this folder).
3. Add the `end_call` and `press_digit` tools to each agent.
4. Set `begin_message` to an EMPTY STRING on the outbound agents
   (booking, inquiry). Empty means the agent waits for their hello;
   null means it talks over the pickup. This one character is the
   difference between charming and unhinged.
5. Give every `{{variable}}` a default. An unfiltered variable gets
   read aloud as "curly brace party underscore..." on a live call.
6. YOUR FIRST CALL IS TO YOURSELF. Point the booking agent at your
   own cell and play the restaurant. You'll hear every rule working.

## The voice

Optional: an ElevenLabs voice clone so the agents speak in your
voice. In Retell, set the agent voice to your ElevenLabs voice ID.
The same API key already powers JARVIS's desktop voice — see
`.env` (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`).

## JARVIS voice routes (already wired in the desktop build)

- "book a table for four at seven tonight" → the booking flow
  collects party/time/notes and launches the Retell call via
  webhook. (Requires the Retell API key in `.env`; the desktop
  agent will ask for it if missing.)
- "what calls did I make today?" → the call log in
  `data/call_log.jsonl`, readable through the Time Machine.

## Files

- `01_booking_agent.md` — outbound booking (tables, appointments,
  haircuts, service visits).
- `02_inquiry_agent.md` — outbound inquiry (hours, prices,
  availability questions).
- `03_receptionist_agent.md` — inbound code-gated receptionist.
