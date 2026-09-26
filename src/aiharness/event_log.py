"""Small redacted JSONL event log for harness tool activity."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Union


MAX_EVENT_LOG_BYTES = 5_000_000


class RunEventLogger:
    """Append tool names and outcomes without recording arguments or content."""

    def __init__(self, path: Union[str, os.PathLike[str]]) -> None:
        self.path = Path(path).expanduser()
        self.backup_path = self.path.with_name(self.path.name + ".1")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def on_tool_call(self, name: str) -> None:
        self._write({"event": "tool_call", "tool": name})

    def on_tool_result(self, name: str, result: object) -> None:
        event: dict[str, object] = {"event": "tool_result", "tool": name}
        if isinstance(result, dict) and "error" in result:
            event["status"] = "error"
        elif name == "run_command" and isinstance(result, dict):
            code = result.get("returncode")
            event["status"] = "passed" if code == 0 else "failed"
            if isinstance(code, (int, type(None))):
                event["returncode"] = code
            if result.get("timed_out"):
                event["timed_out"] = True
        else:
            event["status"] = "ok"
        self._write(event)

    def _write(self, event: dict[str, object]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size + len(encoded.encode("utf-8")) > MAX_EVENT_LOG_BYTES:
            try:
                self.backup_path.unlink(missing_ok=True)
                os.replace(self.path, self.backup_path)
            except OSError:
                # Logging must not stop an otherwise safe coding task.
                pass
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
