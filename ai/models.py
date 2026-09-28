from dataclasses import dataclass


@dataclass
class AIResponse:
    text: str
    provider: str = ""
    model: str = ""