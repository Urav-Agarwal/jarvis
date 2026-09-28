from ai.planner import PlannedAction, TaskPlan


class PlanParser:
    """
    Converts validated LLM plan data into JARVIS TaskPlan objects.

    This class does not execute any tools.
    """

    def parse(self, data: dict) -> TaskPlan:
        if not isinstance(data, dict):
            raise ValueError("Plan data must be a dictionary.")

        if data.get("type") != "plan":
            raise ValueError("Plan data must have type='plan'.")

        actions = data.get("actions")

        if not isinstance(actions, list):
            raise ValueError("Plan actions must be a list.")

        plan = TaskPlan(
            description=data.get("description", "")
        )

        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise ValueError(
                    f"Action {index} must be a dictionary."
                )

            tool = action.get("tool")

            if not isinstance(tool, str) or not tool.strip():
                raise ValueError(
                    f"Action {index} is missing a valid tool."
                )

            parameters = action.get("parameters", {})

            if not isinstance(parameters, dict):
                raise ValueError(
                    f"Parameters for action {index} must be a dictionary."
                )

            description = action.get("description", "")

            if not isinstance(description, str):
                description = str(description)

            depends_on = action.get("depends_on", [])

            if not isinstance(depends_on, list):
                raise ValueError(
                    f"depends_on for action {index} must be a list."
                )

            for dependency in depends_on:
                if (
                    not isinstance(dependency, int)
                    or dependency < 0
                    or dependency >= index
                ):
                    raise ValueError(
                        f"Invalid dependency {dependency} "
                        f"for action {index}."
                    )

            plan.add_action(
                tool=tool,
                parameters=parameters,
                description=description,
                depends_on=depends_on,
            )

        return plan