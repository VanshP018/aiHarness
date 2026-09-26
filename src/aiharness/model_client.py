"""Text-only HTTP client for OpenRouter text and tool-calling APIs."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aiharness.config import Settings


class ModelError(RuntimeError):
    """Raised when a model request fails or returns no usable text."""


class OpenRouterClient:
    def __init__(self, settings: Settings, timeout: float = 120.0) -> None:
        self.settings = settings
        self.timeout = timeout

    def generate(self, task: str) -> str:
        if not self.settings.api_key:
            raise ModelError(
                "AI_API_KEY is not set. Export it in the shell or add it to a local .env file."
            )

        payload = {
            "model": self.settings.model,
            "instructions": (
                "You are the language-model component of an AI coding harness. "
                "For this phase, answer the engineering task with a concise, actionable plan. "
                "Do not claim to have inspected or changed repository files."
            ),
            "input": task,
        }
        request = Request(
            self.settings.base_url.rstrip("/") + "/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ModelError(f"Model API returned HTTP {exc.code}: {details}") from None
        except URLError as exc:
            raise ModelError(f"Could not reach model API: {exc.reason}") from None
        except TimeoutError:
            raise ModelError(f"Model request timed out after {self.timeout:g} seconds.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ModelError("Model API returned an invalid JSON response.") from None

        text = self._extract_text(data)
        if not text:
            raise ModelError("Model API response contained no text output.")
        return text

    def chat_completion(self, messages: list[dict], tools: list[dict]) -> dict:
        """Request one non-streaming tool-capable OpenRouter chat-completion turn."""
        if not self.settings.api_key:
            raise ModelError(
                "AI_API_KEY is not set. Export it in the shell or add it to a local .env file."
            )
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens": 4000,
        }
        request = Request(
            self.settings.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.settings.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ModelError(f"Model API returned HTTP {exc.code}: {details}") from None
        except URLError as exc:
            raise ModelError(f"Could not reach model API: {exc.reason}") from None
        except TimeoutError:
            raise ModelError(f"Model request timed out after {self.timeout:g} seconds.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ModelError("Model API returned an invalid JSON response.") from None
        if not isinstance(data, dict):
            raise ModelError("Model API returned an invalid response object.")
        return data

    @staticmethod
    def _extract_text(data: dict) -> str:
        chunks = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    value = content.get("text")
                    if isinstance(value, str) and value:
                        chunks.append(value)
        return "\n".join(chunks).strip()
