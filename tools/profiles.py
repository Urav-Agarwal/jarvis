from dataclasses import dataclass
from pathlib import Path
import json
import os
import re

@dataclass
class BrowserProfile:
    name: str
    directory: str
    user_data_directory: str


class ChromiumProfileResolver:
    def resolve_profile(self, profiles, requested_name):
        if not profiles:
            return None

        requested = requested_name.lower().strip()

        # Words that can wrap the real request: "my personal
        # profile", "the school one", "my main account".
        requested = re.sub(
            r"^(?:the\s+|my\s+)+", "", requested
        ).strip()

        requested = re.sub(
            r"\s+(?:one|profile|account|chrome\s+profile)$", "",
            requested,
        ).strip()

        default_aliases = {
            "default",
            "personal",
            "main",
            "my profile",
            "my account",
            "my main profile",
            "my personal profile",
            "my own profile",
            "own",
        }

        if requested in default_aliases:
            for profile in profiles:
                if profile.directory.lower() == "default":
                    return profile

        # Exact discovered profile name
        for profile in profiles:
            if profile.name.lower() == requested:
                return profile

        # Exact profile directory
        for profile in profiles:
            if profile.directory.lower() == requested:
                return profile

        # Natural variations such as:
        # "school account" -> "School"
        # "school profile" -> "School"
        matches = []

        for profile in profiles:
            profile_name = profile.name.lower().strip()

            if (
                requested.startswith(profile_name + " ")
                or requested.endswith(" " + profile_name)
            ):
                matches.append(profile)

        if len(matches) == 1:
            return matches[0]

        # Voice fuzzy match: "personal" -> "Urav Agarwal" when that
        # is the Default profile's real name, "my college account"
        # -> "School". A spoken alias rarely equals the stored name,
        # so rank every profile by word overlap and take a clear
        # winner only (ambiguous ties return None on purpose).
        request_words = {
            word
            for word in re.findall(r"[a-z0-9]+", requested)
            if word not in {"profile", "account", "one", "chrome"}
        }

        scored = []

        for profile in profiles:
            profile_words = set(
                re.findall(r"[a-z0-9]+", profile.name.lower())
            )

            directory_words = set(
                re.findall(r"[a-z0-9]+", profile.directory.lower())
            )

            overlap = len(request_words & profile_words)
            directory_overlap = len(request_words & directory_words)

            if overlap or directory_overlap:
                scored.append(
                    (max(overlap, directory_overlap), profile)
                )

        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)

            if len(scored) == 1 or scored[0][0] > scored[1][0]:
                return scored[0][1]

        return None
    def discover_profiles(self, user_data_directory):
        user_data_directory = Path(user_data_directory)
        local_state = user_data_directory / "Local State"

        if not local_state.exists():
            return []

        try:
            with local_state.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

        except (OSError, json.JSONDecodeError):
            return []

        profiles = []

        info_cache = (
            data
            .get("profile", {})
            .get("info_cache", {})
        )

        for directory, info in info_cache.items():
            name = info.get("name") or directory

            profile_directory = (
                user_data_directory / directory
            )

            if not profile_directory.exists():
                continue

            profiles.append(
                BrowserProfile(
                    name=name,
                    directory=directory,
                    user_data_directory=str(
                        user_data_directory
                    ),
                )
            )

        return profiles

class UserDataDirectoryFinder:
    def __init__(self):
        self.search_roots = [
            Path(os.environ.get("LOCALAPPDATA", "")),
            Path(os.environ.get("APPDATA", "")),
        ]

    def find_candidates(self):
        candidates = []

        for root in self.search_roots:
            if not root.exists():
                continue

            try:
                for local_state in root.rglob("Local State"):
                    if not local_state.is_file():
                        continue

                    user_data_directory = local_state.parent

                    candidates.append(
                        user_data_directory
                    )

            except (PermissionError, OSError):
                continue

        return candidates

    def find_for_browser(
        self,
        browser_name,
        executable_path,
    ):
        candidates = self.find_candidates()

        if not candidates:
            return None

        browser_tokens = self._tokenize(
            browser_name
        )

        executable_tokens = self._tokenize(
            Path(executable_path).stem
        )

        best_candidate = None
        best_score = 0

        for candidate in candidates:
            score = self._score_candidate(
                candidate,
                browser_tokens,
                executable_tokens,
            )

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_score == 0:
            return None

        return best_candidate

    def _tokenize(self, value):
        return {
            token.lower()
            for token in re.findall(
                r"[A-Za-z0-9]+",
                value,
            )
            if len(token) > 2
        }

    def _score_candidate(
        self,
        candidate,
        browser_tokens,
        executable_tokens,
    ):
        candidate_text = str(candidate).lower()

        score = 0

        for token in browser_tokens:
            if token in candidate_text:
                score += 2

        for token in executable_tokens:
            if token in candidate_text:
                score += 3

        return score