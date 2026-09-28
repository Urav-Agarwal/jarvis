from pathlib import Path
import re


class FileSystemSearcher:
    def __init__(self):
        self.default_locations = self._get_default_locations()

    def _get_default_locations(self):
        home = Path.home()

        locations = [
            home / "Desktop",
            home / "Downloads",
            home / "Documents",
            home / "Pictures",
            home / "Videos",
            home / "Music",
            home / "Projects",
        ]

        return [location for location in locations if location.exists()]

    def search(self, query: str, location=None, max_results=10):
        query = query.lower().strip()

        if not query:
            return []

        search_locations = []

        if location:
            location_path = Path(location).expanduser()

            if location_path.exists():
                search_locations.append(location_path)
        else:
            search_locations = self.default_locations

        query_tokens = self._tokenize(query)
        matches = []

        for root in search_locations:
            try:
                for path in root.rglob("*"):
                    if not path.is_file():
                        continue

                    # Ignore Python cache files.
                    if "__pycache__" in path.parts:
                        continue

                    # Ignore common temporary/build directories.
                    ignored_directories = {
                        ".venv",
                        "node_modules",
                        ".git",
                        "dist",
                        "build",
                    }

                    if any(
                        directory in ignored_directories
                        for directory in path.parts
                    ):
                        continue

                    score = self._calculate_score(path, query_tokens)

                    if score > 0:
                        matches.append(
                            {
                                "name": path.name,
                                "path": str(path.resolve()),
                                "score": score,
                            }
                        )

            except (PermissionError, OSError):
                continue

        matches.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        return matches[:max_results]

    def _tokenize(self, text):
        return [
            token
            for token in re.findall(r"[a-zA-Z0-9]+", text.lower())
            if len(token) >= 2
        ]

    def _calculate_score(self, path: Path, query_tokens):
        filename = path.name.lower()
        stem = path.stem.lower()
        full_path = str(path).lower()

        score = 0

        for token in query_tokens:
            # Exact filename/stem matches are highly relevant.
            if token in stem:
                score += 10

            elif token in filename:
                score += 8

            elif token in full_path:
                score += 3

        # Strong bonus when the complete query matches the filename.
        normalized_stem = re.sub(
            r"[_\-]+",
            " ",
            stem,
        )

        normalized_query = " ".join(query_tokens)

        if normalized_query in normalized_stem:
            score += 20

        # Prefer normal user files over generated/cache files.
        if path.suffix.lower() in {".pyc", ".tmp", ".log"}:
            score -= 15

        return score