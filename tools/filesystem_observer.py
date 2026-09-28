from pathlib import Path
from datetime import datetime
import shutil
import mimetypes
import os


class FileSystemObserver:
    def get_info(self, path: str):
        file_path = Path(path).expanduser()

        if not file_path.exists():
            return {
                "success": False,
                "error": f"File or folder not found: {path}",
            }

        try:
            stat = file_path.stat()
            size_bytes = stat.st_size

            return {
                "success": True,
                "name": file_path.name,
                "path": str(file_path.resolve()),
                "extension": file_path.suffix.lower(),
                "size_bytes": size_bytes,
                "size": self._format_size(size_bytes),
                "created": datetime.fromtimestamp(
                    stat.st_ctime
                ).isoformat(),
                "modified": datetime.fromtimestamp(
                    stat.st_mtime
                ).isoformat(),
                "is_file": file_path.is_file(),
                "is_directory": file_path.is_dir(),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def read_file(self, path: str, max_chars: int = 100_000):
        file_path = Path(path).expanduser()

        if not file_path.exists():
            return {
                "success": False,
                "error": f"File not found: {path}",
            }

        if not file_path.is_file():
            return {
                "success": False,
                "error": f"Path is not a file: {path}",
            }

        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            truncated = len(content) > max_chars

            if truncated:
                content = content[:max_chars]

            return {
                "success": True,
                "path": str(file_path.resolve()),
                "content": content,
                "truncated": truncated,
            }

        except (OSError, UnicodeError) as error:
            return {
                "success": False,
                "error": f"Could not read file: {error}",
            }

    def create(
        self,
        path: str,
        content: str = "",
        directory: bool = False,
        overwrite: bool = False,
    ):
        target = Path(path).expanduser()

        try:
            if target.exists() and not overwrite:
                return {
                    "success": False,
                    "error": f"Path already exists: {target}",
                }

            target.parent.mkdir(parents=True, exist_ok=True)

            if directory:
                target.mkdir(parents=True, exist_ok=True)

                return {
                    "success": True,
                    "operation": "create_directory",
                    "path": str(target.resolve()),
                }

            target.write_text(
                content,
                encoding="utf-8",
            )

            return {
                "success": True,
                "operation": "create_file",
                "path": str(target.resolve()),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def copy(self, source: str, destination: str):
        source_path = Path(source).expanduser()
        destination_path = Path(destination).expanduser()

        if not source_path.exists():
            return {
                "success": False,
                "error": f"Source not found: {source}",
            }

        try:
            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if source_path.is_dir():
                shutil.copytree(
                    source_path,
                    destination_path,
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy2(
                    source_path,
                    destination_path,
                )

            return {
                "success": True,
                "operation": "copy",
                "source": str(source_path.resolve()),
                "destination": str(destination_path.resolve()),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def move(self, source: str, destination: str):
        source_path = Path(source).expanduser()
        destination_path = Path(destination).expanduser()

        if not source_path.exists():
            return {
                "success": False,
                "error": f"Source not found: {source}",
            }

        try:
            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.move(
                str(source_path),
                str(destination_path),
            )

            return {
                "success": True,
                "operation": "move",
                "source": str(source_path),
                "destination": str(destination_path.resolve()),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def delete(self, path: str):
        r"""
        v4: send to the Recycle Bin (send2trash) instead of permanent
        deletion, and REFUSE protected locations outright: drive
        roots, C:\Windows, Program Files (and anything inside those
        system trees), the user profile root, the JARVIS project
        itself, and any .git directory. Deeper user folders
        (Downloads, Documents) stay deletable — Recycle Bin only.
        """

        target = Path(path).expanduser()

        if not target.exists():
            return {
                "success": False,
                "error": f"Path not found: {path}",
            }

        protected = self._protected_reason(target)

        if protected:
            return {
                "success": False,
                "error": (
                    f"Refusing to delete {target} — {protected}. "
                    "That location is protected, sir."
                ),
            }

        try:
            from send2trash import send2trash

            send2trash(str(target))

            return {
                "success": True,
                "operation": "recycle",
                "path": str(target),
                "message": (
                    f"Moved {target.name} to the Recycle Bin."
                ),
            }

        except ImportError:
            # send2trash unavailable: fail SAFE, never rmtree.
            return {
                "success": False,
                "error": (
                    "Recycle Bin support is missing; deletion "
                    "refused for safety."
                ),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    @staticmethod
    def _protected_reason(target: Path) -> str:
        r"""Return why this path must not be deleted, or "" if safe."""

        try:
            resolved = target.resolve()

        except OSError:
            resolved = target

        # Drive roots (C:\, D:\, ...).
        if resolved.drive and resolved.parent == resolved:
            return "it is a drive root"

        # Exact-match protected location: the profile root itself.
        # Its CHILDREN (Downloads/Documents) stay deletable.
        try:
            if resolved == Path.home().resolve():
                return "it is a protected location"

        except OSError:
            pass

        # System trees and the JARVIS project tree: nothing inside
        # them may be deleted.
        system_trees = [
            Path("C:\\Windows"),
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
            Path.cwd(),
        ]

        for directory in system_trees:
            try:
                resolved_parent = resolved.parent

                if resolved == directory or directory == resolved_parent or directory in resolved.parents:
                    return "it is inside a protected system location"

            except OSError:
                continue

        # Any .git directory.
        if ".git" in resolved.parts:
            return "it is inside a .git directory"

        return ""

    def get_type(self, path: str):
        target = Path(path).expanduser()

        if not target.exists():
            return {
                "success": False,
                "error": f"Path not found: {path}",
            }

        mime_type, _ = mimetypes.guess_type(str(target))

        if target.is_dir():
            file_type = "directory"
        elif mime_type:
            file_type = mime_type
        elif target.suffix:
            file_type = f"{target.suffix.lower()} file"
        else:
            file_type = "unknown"

        return {
            "success": True,
            "path": str(target.resolve()),
            "name": target.name,
            "extension": target.suffix.lower(),
            "type": file_type,
            "is_file": target.is_file(),
            "is_directory": target.is_dir(),
        }

    def get_state(self, path: str | None = None):
        if path:
            return self.get_info(path)

        home = Path.home()

        return {
            "success": True,
            "home": str(home),
            "desktop": str(home / "Desktop"),
            "downloads": str(home / "Downloads"),
            "documents": str(home / "Documents"),
            "pictures": str(home / "Pictures"),
            "videos": str(home / "Videos"),
            "music": str(home / "Music"),
        }

    def open_path(self, path: str):
        target = Path(path).expanduser()

        if not target.exists():
            return {
                "success": False,
                "error": f"Path not found: {path}",
            }

        try:
            os.startfile(str(target))

            return {
                "success": True,
                "path": str(target.resolve()),
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def _format_size(self, size_bytes: int):
        units = ["B", "KB", "MB", "GB", "TB"]

        size = float(size_bytes)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.2f} {unit}"

            size /= 1024