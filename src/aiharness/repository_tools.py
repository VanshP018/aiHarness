"""Bounded repository inspection, editing, and command tools.

These tools constrain paths and process settings, but they are not an OS-level
sandbox. Callers should only use them on repositories they are authorized to
modify.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from typing import Optional, Sequence
import uuid


class ToolError(RuntimeError):
    """Raised when a repository tool cannot safely complete an operation."""


@dataclass(frozen=True)
class SearchMatch:
    path: str
    line: int
    text: str


class RepositoryTools:
    """Tools scoped to one repository root."""

    EXCLUDED_DIRS = {
        ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".aiharness",
    }
    EXCLUDED_FILENAMES = {
        ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
        "credentials.json", "service-account.json", "secrets.yaml", "secrets.yml",
    }
    EXCLUDED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}

    def __init__(
        self,
        repo_root: str | os.PathLike[str],
        *,
        max_file_bytes: int = 1_000_000,
        max_output_chars: int = 24_000,
        command_timeout: int = 60,
    ) -> None:
        self.root = Path(repo_root).expanduser().resolve()
        if not self.root.is_dir():
            raise ToolError(f"Repository root is not a directory: {self.root}")
        self.max_file_bytes = max_file_bytes
        self.max_output_chars = max_output_chars
        self.command_timeout = command_timeout

    def list_files(self, path: str = ".", limit: int = 200) -> list[str]:
        """List repository files under a relative directory, excluding secrets and generated trees."""
        if limit < 1 or limit > 2000:
            raise ToolError("File listing limit must be between 1 and 2000.")
        start = self._safe_path(path, allow_root=True)
        if not start.is_dir():
            raise ToolError(f"Not a directory: {path}")

        results: list[str] = []
        for current, dirs, files in os.walk(start, followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(
                name for name in dirs
                if name.lower() not in self.EXCLUDED_DIRS
                and not name.lower().startswith(".env")
                and not (current_path / name).is_symlink()
            )
            for filename in sorted(files):
                candidate = current_path / filename
                if self._is_excluded(candidate) or candidate.is_symlink():
                    continue
                relative = candidate.relative_to(self.root).as_posix()
                results.append(relative)
                if len(results) >= limit:
                    return results
        return results

    def read_file(self, path: str) -> str:
        """Read a bounded UTF-8 text file inside the repository."""
        target = self._safe_path(path)
        if not target.is_file():
            raise ToolError(f"Not a regular file: {path}")
        if target.stat().st_size > self.max_file_bytes:
            raise ToolError(
                f"File is larger than the {self.max_file_bytes}-byte read limit: {path}"
            )
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"File is not UTF-8 text: {path}") from None

    def search_text(
        self,
        query: str,
        *,
        path: str = ".",
        glob: str = "*",
        limit: int = 50,
        case_sensitive: bool = True,
    ) -> list[SearchMatch]:
        """Search literal text in bounded, non-secret repository files."""
        if not query:
            raise ToolError("Search query cannot be empty.")
        if limit < 1 or limit > 500:
            raise ToolError("Search result limit must be between 1 and 500.")
        start = self._safe_path(path, allow_root=True)
        if not start.is_dir():
            raise ToolError(f"Not a directory: {path}")

        needle = query if case_sensitive else query.casefold()
        matches: list[SearchMatch] = []
        for relative in self.list_files(path, limit=2000):
            candidate = self.root / relative
            if not fnmatch.fnmatch(candidate.name, glob):
                continue
            try:
                if candidate.stat().st_size > self.max_file_bytes:
                    continue
                contents = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(contents.splitlines(), start=1):
                haystack = line if case_sensitive else line.casefold()
                if needle in haystack:
                    matches.append(SearchMatch(relative, line_number, line[:1000]))
                    if len(matches) >= limit:
                        return matches
        return matches

    def write_file(self, path: str, content: str) -> str:
        """Snapshot then create or replace a UTF-8 text file inside the repository."""
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise ToolError(
                f"Written content exceeds the {self.max_file_bytes}-byte limit."
            )
        target = self._safe_path(path, allow_missing_parents=True)
        snapshot_id = self._create_snapshot(path, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-check after creating parents to catch symlinked path components.
        target = self._safe_path(path)
        self._atomic_write(target, content.encode("utf-8"))
        return snapshot_id

    def repository_map(self, limit: int = 120, max_chars: int = 8_000) -> str:
        """Build a compact path map to guide focused repository reads."""
        files = self.list_files(limit=limit)
        priority = {"README.md": 0, "pyproject.toml": 1, "package.json": 2, "Makefile": 3}
        files.sort(key=lambda name: (priority.get(name, 10), name.count("/"), name))
        lines = ["Repository file map (paths only; inspect relevant files before editing):"]
        lines.extend(f"- {name}" for name in files)
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[: max_chars - 32] + "\n[repository map truncated]"
        return result

    def project_instructions(self, max_chars: int = 12_000) -> Optional[tuple[str, str]]:
        """Return a bounded root AGENTS.md instruction file, if present."""
        for name in ("AGENTS.md", "AIHARNES.md"):
            try:
                content = self.read_file(name)
            except ToolError as exc:
                if not (self.root / name).exists():
                    continue
                raise exc
            return name, content[:max_chars]
        return None

    def list_snapshots(self) -> list[dict[str, str]]:
        """List local per-file checkpoints without exposing their saved contents."""
        directory = self._snapshot_directory(create=False)
        if not directory:
            return []
        snapshots = []
        for snapshot_file in directory.glob("*.json"):
            try:
                record = json.loads(snapshot_file.read_text(encoding="utf-8"))
                if isinstance(record, dict) and record.get("snapshot_id") == snapshot_file.stem:
                    snapshots.append({
                        "snapshot_id": record["snapshot_id"],
                        "path": record["path"],
                        "created_at": record["created_at"],
                    })
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(snapshots, key=lambda item: item["created_at"], reverse=True)

    def restore_snapshot(self, snapshot_id: str = "latest") -> dict[str, str]:
        """Restore one checkpointed file and checkpoint the current version first."""
        snapshots = self.list_snapshots()
        if snapshot_id == "latest":
            if not snapshots:
                raise ToolError("No snapshots are available for this repository.")
            snapshot_id = snapshots[0]["snapshot_id"]
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", snapshot_id):
            raise ToolError("Invalid snapshot ID.")
        directory = self._snapshot_directory(create=False)
        if not directory:
            raise ToolError("No snapshots are available for this repository.")
        snapshot_file = directory / f"{snapshot_id}.json"
        try:
            record = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ToolError(f"Snapshot not found: {snapshot_id}") from None
        if not isinstance(record, dict) or record.get("snapshot_id") != snapshot_id:
            raise ToolError("Snapshot is malformed.")
        path = record.get("path")
        if not isinstance(path, str):
            raise ToolError("Snapshot is malformed: missing path.")
        target = self._safe_path(path, allow_missing_parents=True)
        rollback_id = self._create_snapshot(path, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._safe_path(path)
        if record.get("before_exists"):
            try:
                previous = base64.b64decode(record["before_content"], validate=True)
            except (KeyError, ValueError, TypeError):
                raise ToolError("Snapshot is malformed: invalid saved content.") from None
            self._atomic_write(target, previous)
        elif target.exists():
            target.unlink()
        return {"restored": snapshot_id, "path": path, "rollback_snapshot": rollback_id}

    def _create_snapshot(self, path: str, target: Path) -> str:
        if target.exists() and not target.is_file():
            raise ToolError(f"Cannot checkpoint a non-file target: {path}")
        previous = b""
        exists = target.is_file()
        if exists:
            if target.stat().st_size > self.max_file_bytes:
                raise ToolError(
                    f"Cannot safely checkpoint files larger than {self.max_file_bytes} bytes."
                )
            previous = target.read_bytes()
        directory = self._snapshot_directory(create=True)
        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
        record = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "path": Path(path).as_posix(),
            "before_exists": exists,
            "before_content": base64.b64encode(previous).decode("ascii"),
        }
        snapshot_file = directory / f"{snapshot_id}.json"
        try:
            with snapshot_file.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
            os.chmod(snapshot_file, 0o600)
        except OSError as exc:
            raise ToolError(f"Could not save snapshot: {exc}") from None
        return snapshot_id

    def _snapshot_directory(self, *, create: bool) -> Optional[Path]:
        hidden = self.root / ".aiharness"
        directory = hidden / "snapshots"
        if hidden.is_symlink() or directory.is_symlink():
            raise ToolError("Snapshot directory cannot be a symlink.")
        if create:
            hidden.mkdir(mode=0o700, exist_ok=True)
            directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.exists():
            return None
        return directory

    @staticmethod
    def _atomic_write(target: Path, content: bytes) -> None:
        temporary_name: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=".aiharness-", suffix=".tmp", delete=False
            ) as stream:
                temporary_name = stream.name
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        except OSError as exc:
            raise ToolError(f"Could not write {target.name}: {exc}") from None
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def run_command(
        self,
        argv: Sequence[str],
        *,
        cwd: str = ".",
        timeout: Optional[int] = None,
    ) -> dict[str, object]:
        """Run an argv command without a shell, in the repository, with a minimal environment."""
        if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ToolError("Command must be a non-empty list of text arguments.")
        executable = Path(argv[0]).name.lower()
        if executable in {"sh", "bash", "zsh", "fish", "dash", "cmd", "powershell", "pwsh"}:
            raise ToolError("Shell interpreters are not allowed; pass a command as an argument list.")
        if executable in {"rm", "sudo", "chmod", "chown", "curl", "wget", "ssh", "scp"}:
            raise ToolError(f"Command is blocked by the repository tool policy: {executable}")
        if executable == "git" and len(argv) > 1 and argv[1] in {
            "push", "reset", "clean", "rebase", "checkout", "switch",
        }:
            raise ToolError(f"Git subcommand is blocked by the repository tool policy: {argv[1]}")

        working_directory = self._safe_path(cwd, allow_root=True)
        if not working_directory.is_dir():
            raise ToolError(f"Command working directory is not a directory: {cwd}")
        allowed_timeout = self.command_timeout if timeout is None else timeout
        if allowed_timeout < 1 or allowed_timeout > 300:
            raise ToolError("Command timeout must be between 1 and 300 seconds.")

        # Deliberately omit API keys and other application credentials.
        safe_environment = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT"}
        }
        try:
            result = subprocess.run(
                list(argv),
                cwd=working_directory,
                env=safe_environment,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=allowed_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._bounded_output(exc.stdout or "")
            stderr = self._bounded_output(exc.stderr or "")
            return {
                "returncode": None,
                "timed_out": True,
                "stdout": stdout,
                "stderr": stderr,
            }
        except OSError as exc:
            raise ToolError(f"Could not run command: {exc}") from None

        return {
            "returncode": result.returncode,
            "timed_out": False,
            "stdout": self._bounded_output(result.stdout),
            "stderr": self._bounded_output(result.stderr),
        }

    def summary(self, limit: int = 100) -> str:
        """Return a compact inventory of likely project files."""
        files = self.list_files(limit=limit)
        if not files:
            return "No readable project files found."
        suffixes: dict[str, int] = {}
        for name in files:
            suffix = Path(name).suffix or "[no extension]"
            suffixes[suffix] = suffixes.get(suffix, 0) + 1
        extensions = ", ".join(
            f"{suffix}: {count}" for suffix, count in sorted(suffixes.items())
        )
        return f"Files ({len(files)} shown):\n" + "\n".join(files) + f"\n\nTypes: {extensions}"

    def _safe_path(
        self,
        raw_path: str,
        *,
        allow_root: bool = False,
        allow_missing_parents: bool = False,
    ) -> Path:
        path_text = str(raw_path)
        supplied = PurePosixPath(path_text)
        if supplied.is_absolute() or ".." in supplied.parts or "\x00" in path_text:
            raise ToolError("Paths must be relative to the repository and cannot traverse upward.")
        if any(part.lower() in self.EXCLUDED_DIRS for part in supplied.parts):
            raise ToolError("Access to generated or Git metadata directories is blocked.")
        if any(
            part.lower() in self.EXCLUDED_FILENAMES or part.lower().startswith(".env")
            for part in supplied.parts
        ):
            raise ToolError("Access to environment and secret files is blocked.")
        if Path(supplied.name).suffix.lower() in self.EXCLUDED_SUFFIXES:
            raise ToolError("Access to credential and key files is blocked.")
        if not supplied.parts or path_text in {"", "."}:
            if allow_root:
                return self.root
            raise ToolError("A repository-relative file path is required.")

        current = self.root
        parts = supplied.parts
        for index, part in enumerate(parts):
            current = current / part
            if current.is_symlink():
                raise ToolError("Symlink paths are blocked by the repository tool policy.")
            if not current.exists() and allow_missing_parents:
                continue
            if current.exists():
                resolved = current.resolve()
                try:
                    resolved.relative_to(self.root)
                except ValueError:
                    raise ToolError("Path resolves outside the repository.") from None
                current = resolved
            elif index < len(parts) - 1 and not allow_missing_parents:
                # Paths may contain a missing final component but not missing parent folders.
                raise ToolError(f"Parent path does not exist: {part}")
        if current == self.root and not allow_root:
            raise ToolError("A repository-relative file path is required.")
        return current

    def _is_excluded(self, path: Path) -> bool:
        name = path.name.lower()
        return (
            name in self.EXCLUDED_FILENAMES
            or name.startswith(".env")
            or path.suffix.lower() in self.EXCLUDED_SUFFIXES
        )

    def _bounded_output(self, value: object) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value)
        if len(text) > self.max_output_chars:
            return text[: self.max_output_chars] + "\n[output truncated]"
        return text
