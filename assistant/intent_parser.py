import re


class IntentParser:
    def parse(self, user_input: str):
        text = user_input.lower().strip()

        # Remove punctuation.
        text = re.sub(r"[^\w\s%]", " ", text)

        # Normalize whitespace.
        text = re.sub(r"\s+", " ", text).strip()

        # -------------------------
        # LOCK LAPTOP
        # -------------------------

        if self._matches_action(
            text,
            action_words=("lock",),
            target_words=("laptop", "computer", "pc", "screen"),
        ):
            return "lock_laptop"

        # -------------------------
        # SLEEP LAPTOP
        # -------------------------

        if self._matches_action(
            text,
            action_words=("sleep", "suspend"),
            target_words=("laptop", "computer", "pc"),
        ):
            return "sleep_laptop"

        # -------------------------
        # RESTART LAPTOP
        # -------------------------

        if self._matches_action(
            text,
            action_words=("restart", "reboot"),
            target_words=("laptop", "computer", "pc"),
        ):
            return "restart_laptop"

        # -------------------------
        # SHUTDOWN LAPTOP
        # -------------------------

        if self._matches_action(
            text,
            action_words=("shutdown", "shut down", "power off"),
            target_words=("laptop", "computer", "pc"),
        ):
            return "shutdown_laptop"

        # -------------------------
        # SET VOLUME
        # -------------------------

        volume_match = re.search(
            r"\b(?:set|change|make|put)\b.*?\bvolume\b.*?(\d{1,3})\s*(?:percent|%)?",
            text,
        )

        if volume_match:
            percentage = int(volume_match.group(1))

            if 0 <= percentage <= 100:
                return ("set_volume", percentage)

        # -------------------------
        # MAXIMUM VOLUME
        # -------------------------

        if re.search(
            r"\b(set|put|make|turn)\b.*\bvolume\b.*\b(maximum|max|full)\b",
            text,
        ):
            return ("set_volume", 100)

        # -------------------------
        # ZERO VOLUME
        # -------------------------

        if re.search(
            r"\b(set|put|make|turn)\b.*\bvolume\b.*\b(minimum|min|zero|silent)\b",
            text,
        ):
            return ("set_volume", 0)

        # -------------------------
        # MUTE
        # -------------------------

        if self._matches_any(
            text,
            (
                r"\bmute\b",
                r"\bmake it silent\b",
                r"\bsilence\b.*\b(volume|sound|audio)?\b",
            ),
        ):
            return "volume_mute"

        # -------------------------
        # UNMUTE
        # -------------------------

        if self._matches_any(
            text,
            (
                r"\bunmute\b",
                r"\bturn the sound back on\b",
                r"\brestore the sound\b",
            ),
        ):
            return "volume_unmute"

        # -------------------------
        # VOLUME UP WITH AMOUNT
        # -------------------------

        volume_up_match = re.search(
            r"\b(increase|raise|boost)\b.*?(\d{1,3})\s*(?:percent|%)?",
            text,
        )

        if volume_up_match:
            amount = int(volume_up_match.group(2))

            if 0 <= amount <= 100:
                return ("volume_up", amount)

        volume_up_match = re.search(
            r"\b(increase|raise|boost)\b.*?(\d{1,3})\s*(?:percent|%)?",
            text,
        )

        if volume_up_match:
            amount = int(volume_up_match.group(1))

            if 0 <= amount <= 100:
                return ("volume_up", amount)


        # -------------------------
        # NORMAL VOLUME UP
        # -------------------------

        if self._matches_any(
            text,
            (
                r"\b(increase|raise|boost)\b.*\bvolume\b",
                r"\bvolume\b.*\b(up|higher|louder)\b",
                r"\b(make it louder)\b",
            ),
        ):
            return ("volume_up", 10)

        # -------------------------
        # VOLUME DOWN WITH AMOUNT
        # -------------------------

        volume_down_match = re.search(
            r"\b(decrease|lower|reduce)\b.*?(\d{1,3})\s*(?:percent|%)?",
            text,
        )

        if volume_down_match:
            amount = int(volume_down_match.group(2))

            if 0 <= amount <= 100:
                return ("volume_down", amount)

        volume_down_match = re.search(
            r"\bturn\b.*?\bvolume\b.*?\bdown\b.*?(\d{1,3})\s*(?:percent|%)",
            text,
        )

        if volume_down_match:
            amount = int(volume_down_match.group(1))

            if 0 <= amount <= 100:
                return ("volume_down", amount)

        # -------------------------
        # NORMAL VOLUME DOWN
        # -------------------------

        if self._matches_any(
            text,
            (
                r"\b(decrease|lower|turn down|reduce)\b.*\bvolume\b",
                r"\bvolume\b.*\b(down|lower|quieter)\b",
                r"\b(make it quieter)\b",
            ),
        ):
            return ("volume_down", 10)

        return None

    def _matches_any(self, text, patterns):
        for pattern in patterns:
            if re.search(pattern, text):
                return True

        return False

    def _matches_action(self, text, action_words, target_words):
        action_pattern = "|".join(
            re.escape(word) for word in action_words
        )

        target_pattern = "|".join(
            re.escape(word) for word in target_words
        )

        return (
            re.search(
                rf"\b({action_pattern})\b.*\b({target_pattern})\b",
                text,
            )
            or re.search(
                rf"\b({target_pattern})\b.*\b({action_pattern})\b",
                text,
            )
        )


if __name__ == "__main__":
    parser = IntentParser()

    test_commands = [
        "Increase the volume",
        "Increase the volume by 30%",
        "Turn the volume up by 20 percent",
        "Make it louder",

        "Decrease the volume",
        "Decrease the volume by 15%",
        "Turn the volume down by 25 percent",
        "Make it quieter",

        "Mute",
        "Mute the volume",
        "Make it silent",

        "Lock my screen",
        "Please lock my screen",
        "Can you lock the screen",

        "Unmute",
        "Unmute the volume",

        "Decrease the volume by 20",
        "Increase the volume by 30",

        "Set the volume to 50 percent",
        "Set the volume to maximum",
        "Set the volume to max",
        "Put the volume at 30 percent",
        "Set the volume to zero",
    ]

    for command in test_commands:
        print(command, "->", parser.parse(command))