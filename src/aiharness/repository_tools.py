"""Bounded repository inspection, editing, and command tools.

These tools constrain paths and process settings, but they are not an OS-level
sandbox. Callers should only use them on repositories they are authorized to
modify.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Optional, Sequence


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
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
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

    def write_file(self, path: str, content: str) -> None:
        """Create or replace a UTF-8 text file inside the repository atomically."""
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise ToolError(
                f"Written content exceeds the {self.max_file_bytes}-byte limit."
            )
        target = self._safe_path(path, allow_missing_parents=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-check after creating parents to catch symlinked path components.
        target = self._safe_path(path)
        temporary_name: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent,
                prefix=".aiharness-", suffix=".tmp", delete=False,
            ) as stream:
                temporary_name = stream.name
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        except OSError as exc:
            raise ToolError(f"Could not write {path}: {exc}") from None
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
