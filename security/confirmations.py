class ConfirmationManager:
    def __init__(self):
        self.pending_action = None

    def request_confirmation(
        self,
        tool_name: str,
        parameters: dict,
        description: str,
    ) -> str:
        self.pending_action = {
            "tool": tool_name,
            "parameters": parameters,
            "description": description,
        }

        return f"Please confirm if you want me to {description}."

    def has_pending(self) -> bool:
        return self.pending_action is not None

    def get_pending(self):
        return self.pending_action

    def confirm(self) -> bool:
        if self.pending_action is None:
            return False

        return True

    def consume(self):
        action = self.pending_action
        self.pending_action = None
        return action

    def cancel(self):
        self.pending_action = None