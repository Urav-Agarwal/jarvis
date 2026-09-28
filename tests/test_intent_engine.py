from ai.provider import GroqProvider
from assistant.intent_engine import IntentEngine


ai = GroqProvider()
engine = IntentEngine(ai)


test_commands = [
    "Lock my laptop",
    "I'm leaving, secure my computer",
    "Can you lock my screen?",
    "Make the volume louder",
    "Increase the volume by 25 percent",
    "Turn the sound down a little",
    "Put the volume at 50 percent",
    "Set the volume to maximum",
    "Mute the sound",
    "Turn the sound back on",
    "Take a picture of my display",
    "What is the capital of India?",
]


for command in test_commands:
    result = engine.parse(command)

    print()
    print("USER:", command)
    print("INTENT:", result)