from ai.agent import AgentBrain


class FakeProvider:
    def generate(self, prompt):
        return """
{
    "type": "plan",
    "description": "Open Chrome and set the volume",
    "actions": [
        {
            "tool": "application.open",
            "parameters": {
                "application": "Chrome"
            },
            "description": "Open Chrome",
            "depends_on": []
        },
        {
            "tool": "system.volume",
            "parameters": {
                "level": 40
            },
            "description": "Set the volume to 40 percent",
            "depends_on": [0]
        }
    ]
}
"""


brain = AgentBrain(FakeProvider())

result = brain.think(
    "Open Chrome and set my volume to 40"
)

print(result)