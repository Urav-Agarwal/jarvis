from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlannedAction:
    """
    One executable action in a JARVIS task plan.
    """

    tool: str
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: list[int] = field(default_factory=list)


@dataclass
class TaskPlan:
    """
    A sequence of actions that JARVIS intends to execute.
    """

    actions: list[PlannedAction] = field(default_factory=list)
    description: str = ""

    def add_action(
        self,
        tool: str,
        parameters: dict[str, Any] | None = None,
        description: str = "",
        depends_on: list[int] | None = None,
    ) -> PlannedAction:
        action = PlannedAction(
            tool=tool,
            parameters=parameters or {},
            description=description,
            depends_on=depends_on or [],
        )

        self.actions.append(action)
        return action

    def is_empty(self) -> bool:
        return len(self.actions) == 0

    def action_count(self) -> int:
        return len(self.actions)