"""LLM backends. Each exposes complete(system, messages) -> str.

`messages` is a list of {"role": "user"|"assistant", "content": str}.
"""

import json
import subprocess
from pathlib import Path

from . import runtime


class BackendError(RuntimeError):
    pass


class SetupError(BackendError):
    """The backend isn't configured (no CLI installed, no API key). The UI offers Settings."""


class ClaudeCLIBackend:
    """Runs the installed Claude Code CLI headless (`claude -p`)."""

    name = "Claude Code CLI"

    def __init__(self, model: str = "", timeout: int = 600):
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, messages: list[dict]) -> str:
        exe = runtime.find_claude()
        if not exe:
            raise SetupError("Claude Code (the `claude` command) isn't installed. Either install it "
                             "and log in, or choose the Anthropic API in Settings and enter an API key.")
        # The CLI takes a single prompt, so earlier turns are inlined as a transcript.
        if len(messages) == 1:
            prompt = messages[0]["content"]
        else:
            prompt = "\n\n".join(f"<{m['role']}>\n{m['content']}\n</{m['role']}>" for m in messages)
            prompt += "\n\nRespond to the last <user> message."
        cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
               "--system-prompt", system]
        if self.model:
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(runtime.host_argv(cmd), input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout, env=runtime.host_env(), cwd=str(Path.home()))
        except subprocess.TimeoutExpired:
            raise BackendError(f"Claude CLI timed out after {self.timeout}s") from None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise BackendError(f"Claude CLI failed (exit {proc.returncode}): "
                               f"{(proc.stderr or proc.stdout).strip()[:500]}") from None
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            raise BackendError(f"Claude CLI error: {str(data.get('result') or data)[:500]}")
        return data.get("result", "")


class AnthropicBackend:
    """Calls the Messages API through the official `anthropic` Python SDK."""

    name = "Anthropic API"

    def __init__(self, model: str = "claude-opus-5", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    def complete(self, system: str, messages: list[dict]) -> str:
        try:
            import anthropic
        except ImportError:
            raise SetupError("The `anthropic` package is not installed. Run: pip install anthropic") from None

        try:
            client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        except anthropic.AnthropicError:
            raise SetupError("No Anthropic API key is set. Add one in Settings "
                             "(console.anthropic.com → API keys).") from None
        try:
            # Streaming avoids HTTP timeouts on long generations; server-side
            # fallbacks re-route a refused request to another model automatically.
            with client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise SetupError("The Anthropic API key is missing or invalid. Add one in Settings "
                             "(console.anthropic.com → API keys).") from None
        except anthropic.RateLimitError:
            raise BackendError("Anthropic API rate limit hit — try again shortly.") from None
        except anthropic.APIStatusError as e:
            raise BackendError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise BackendError(f"Could not reach the Anthropic API: {e}") from e

        if message.stop_reason == "refusal":
            raise BackendError("The model declined this request.")
        if message.stop_reason == "max_tokens":
            raise BackendError("The response was cut off (max_tokens). Try a simpler widget.")
        return "".join(b.text for b in message.content if b.type == "text")


def from_config(cfg: dict):
    backend = cfg.get("backend", "auto")
    if backend == "auto":
        # Prefer an existing Claude Code login; otherwise use the API.
        backend = "claude-cli" if runtime.find_claude() else "anthropic"
    if backend == "anthropic":
        return AnthropicBackend(cfg.get("api_model") or "claude-opus-5", cfg.get("anthropic_api_key", ""))
    return ClaudeCLIBackend(cfg.get("cli_model", ""))
