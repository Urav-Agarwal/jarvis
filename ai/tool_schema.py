from dataclasses import dataclass, field

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    risk: str = "low"
    confirmation_required: bool = False
    category: str = "general"