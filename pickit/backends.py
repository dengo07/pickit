"""LLM backends. Each exposes complete(system, messages) -> str.

`messages` is a list of {"role": "user"|"assistant", "content": str}.
"""

import functools
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import runtime

OLLAMA_URL = "http://localhost:11434"
OLLAMA_SUGGESTED = "qwen3.5:9b"
OLLAMA_REPLY_TOKENS = 6144  # a widget spec is 0.5–4k tokens; more means the model is looping
OPENROUTER_URL = "https://openrouter.ai/api/v1"
RATE_LIMIT_WAITS = (5, 15)  # seconds between retries after HTTP 429/502/503
OPENROUTER_MODEL = "anthropic/claude-sonnet-5"
OPENROUTER_SUGGESTIONS = ("anthropic/claude-sonnet-5", "google/gemini-3.8-flash", "deepseek/deepseek-v4.1-flash",
                          "nvidia/nemotron-3-ultra-550b-a55b:free", "qwen/qwen3.8-27b:free")
NOTHING_SET_UP = ("No AI backend is set up yet. In Settings, choose one of: Claude Code (uses your Claude "
                  "login), an Anthropic API key, Ollama (free, runs on your computer) or an OpenRouter key.")


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

    def _exe(self) -> str:
        exe = runtime.find_claude()
        if not exe:
            raise SetupError("Claude Code (the `claude` command) isn't installed. Install it and log in, "
                             "or choose another backend in Settings.")
        return exe

    def check(self) -> str:
        return f"Found Claude Code at {self._exe()}"

    def complete(self, system: str, messages: list[dict]) -> str:
        exe = self._exe()
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

    def _client(self):
        try:
            import anthropic
        except ImportError:
            raise SetupError("The `anthropic` package is not installed. Run: pip install anthropic") from None
        try:
            client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
        except anthropic.AnthropicError:
            raise SetupError("No Anthropic API key is set. Add one in Settings "
                             "(console.anthropic.com → API keys).") from None
        return anthropic, client

    def check(self) -> str:
        anthropic, client = self._client()
        try:
            client.models.retrieve(self.model)
        except anthropic.AuthenticationError:
            raise SetupError("The Anthropic API key was rejected. Check it in Settings.") from None
        except anthropic.NotFoundError:
            raise SetupError(f"The model \"{self.model}\" doesn't exist. Check the model name.") from None
        except anthropic.APIError as e:
            raise BackendError(f"Anthropic API error: {e}") from None
        return f"Key works · {self.model} is available"

    def complete(self, system: str, messages: list[dict]) -> str:
        anthropic, client = self._client()
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


# --- plain HTTP helpers (standard library only, so no extra dependencies) ------------------
CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
              "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem")


@functools.cache
def _ssl_context():
    """HTTPS with the system's certificates. The AppImage's OpenSSL looks where its build distro
    (Ubuntu) keeps them, so on other distros point it at theirs."""
    paths = ssl.get_default_verify_paths()
    if paths.cafile or paths.capath:
        return ssl.create_default_context()
    for bundle in CA_BUNDLES:
        if os.path.exists(bundle):
            return ssl.create_default_context(cafile=bundle)
    try:
        import certifi  # if installed
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class HTTPError(BackendError):
    def __init__(self, status: int, body: str, retry_after: str | None = None):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status, self.body, self.retry_after = status, body, retry_after


def _request(url, payload=None, headers=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    context = _ssl_context() if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
            return json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, e.read().decode(errors="replace"), e.headers.get("Retry-After")) from None


def _chat_messages(system, messages):
    return [{"role": "system", "content": system}] + [{"role": m["role"], "content": m["content"]}
                                                       for m in messages]


def _param_count(model: dict) -> float:
    """"9.7B" -> 9.7e9, from Ollama's model details."""
    size = str((model.get("details") or {}).get("parameter_size", ""))
    try:
        return float(size[:-1]) * {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[size[-1:].upper()]
    except (KeyError, ValueError):
        return 0


class OllamaBackend:
    """A local model served by Ollama (https://ollama.com): free and private."""

    name = "Ollama (local)"
    repair_attempts = 2  # small local models benefit from a second try

    def __init__(self, model: str = "", url: str = "", context: int = 16384, timeout: int = 900):
        self.url = (url or os.environ.get("OLLAMA_HOST") or OLLAMA_URL).rstrip("/")
        if self.url.startswith(":"):  # OLLAMA_HOST may be just a port
            self.url = "127.0.0.1" + self.url
        if not self.url.startswith(("http://", "https://")):
            self.url = "http://" + self.url
        self.model, self.context, self.timeout = model, context, timeout

    def check(self) -> str:
        installed = self.models()
        if not installed:
            raise SetupError("Ollama is running but has no models. Download one, e.g. "
                             f"`ollama pull {OLLAMA_SUGGESTED}`.")
        if self.model and self.model not in installed and f"{self.model}:latest" not in installed:
            raise SetupError(f"The model \"{self.model}\" isn't installed. Run: ollama pull {self.model}")
        return f"Connected to Ollama · {len(installed)} model{'s' if len(installed) != 1 else ''} installed"

    def models(self) -> list[str]:
        """Installed chat models, largest first (bigger models write better widgets).
        Raises SetupError if Ollama isn't reachable."""
        try:
            data = _request(f"{self.url}/api/tags", timeout=5)
        except (urllib.error.URLError, OSError, HTTPError):
            raise SetupError(f"Ollama isn't running at {self.url}. Install it from ollama.com, or start it "
                             "with `ollama serve`.") from None
        chat = [m for m in (data or {}).get("models", [])
                if "embed" not in m["name"] and "bert" not in str((m.get("details") or {}).get("families"))]
        return [m["name"] for m in sorted(chat, key=lambda m: -_param_count(m))]

    def complete(self, system: str, messages: list[dict]) -> str:
        model = self.model
        if not model:
            installed = self.models()
            if not installed:
                raise SetupError(f"Ollama has no models yet. Download one, e.g. `ollama pull {OLLAMA_SUGGESTED}`,"
                                 " then pick it in Settings.")
            model = installed[0]
        chat = _chat_messages(system, messages)
        # Pickit's instructions alone are ~8k tokens, and Ollama silently cuts off whatever doesn't fit
        # its window (often 4k by default). Refining a big widget can need more than the configured size.
        needed = sum(len(m["content"]) for m in chat) // 3 + OLLAMA_REPLY_TOKENS  # ~3 chars per token
        context = max(self.context, -(-needed // 4096) * 4096)
        payload = {
            "model": model, "messages": chat, "stream": False,
            "format": "json",  # constrains the output to valid JSON
            # Measured with qwen3.5:9b: thinking took the same time but produced a much smaller widget.
            "think": False,
            "options": {"num_ctx": context, "num_predict": OLLAMA_REPLY_TOKENS, "temperature": 0.4},
        }
        try:
            data = _request(f"{self.url}/api/chat", payload, timeout=self.timeout)
        except HTTPError as e:
            if e.status == 404 or "not found" in e.body.lower():
                raise SetupError(f"The model \"{model}\" isn't installed in Ollama. Run: ollama pull {model}") \
                    from None
            raise BackendError(f"Ollama error {e.status}: {e.body[:300]}") from None
        except TimeoutError:
            raise BackendError(f"Ollama took longer than {self.timeout // 60} minutes. Try a smaller model.") \
                from None
        except (urllib.error.URLError, OSError):
            raise SetupError(f"Ollama isn't running at {self.url}. Install it from ollama.com, or start it "
                             "with `ollama serve`.") from None
        if (data or {}).get("done_reason") == "length":
            raise BackendError(f"The model \"{model}\" didn't finish its reply (small models sometimes get "
                               "stuck repeating themselves). Try again, or use a bigger model.")
        return ((data or {}).get("message") or {}).get("content", "")


class OpenRouterBackend:
    """Any model on OpenRouter (https://openrouter.ai) through one API key."""

    name = "OpenRouter"
    repair_attempts = 1

    def __init__(self, model: str = "", api_key: str = "", timeout: int = 600):
        self.model = model or OPENROUTER_MODEL
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.timeout = timeout

    def _headers(self):
        if not self.api_key:
            raise SetupError("No OpenRouter API key is set. Create one at openrouter.ai/keys and add it in "
                             "Settings.")
        # OpenRouter's app attribution headers.
        return {"Authorization": f"Bearer {self.api_key}", "HTTP-Referer": "https://github.com/dengo07/pickit",
                "X-Title": "Pickit"}

    def check(self) -> str:
        """Validate the key and the model; returns a short description."""
        try:
            data = (_request(f"{OPENROUTER_URL}/key", headers=self._headers(), timeout=15) or {}).get("data") or {}
            _request(f"{OPENROUTER_URL}/models/{urllib.parse.quote(self.model, safe='/:')}/endpoints", timeout=15)
        except HTTPError as e:
            raise self._error(e) from None
        except (urllib.error.URLError, OSError) as e:
            raise BackendError(f"Could not reach OpenRouter: {e}") from None
        limit = data.get("limit_remaining")
        return "Key works" + (f" · ${limit:.2f} credit left" if isinstance(limit, (int, float)) else "") + \
            f" · {self.model} is available"

    @staticmethod
    def _detail(e: HTTPError) -> str:
        """OpenRouter's own explanation, preferring the provider's raw message."""
        try:
            err = json.loads(e.body).get("error") or {}
            detail = str((err.get("metadata") or {}).get("raw") or err.get("message") or "")
            return detail.split(". ")[0].rstrip(".")[:200]  # the first sentence says what happened
        except (ValueError, AttributeError):
            return ""

    def _error(self, e: HTTPError) -> BackendError:
        body = e.body.lower()
        if e.status == 401:
            return SetupError("OpenRouter rejected the API key. Check it in Settings (openrouter.ai/keys).")
        if e.status == 402:
            return BackendError("Your OpenRouter account is out of credits. Add credits, or pick a free "
                                "model (ending in :free).")
        if e.status == 404 or "not a valid model" in body or "no endpoints" in body:
            return SetupError(f"OpenRouter doesn't offer the model \"{self.model}\". Pick another one in "
                              "Settings.")
        if e.status == 429:
            detail = self._detail(e)
            return BackendError(f"OpenRouter: {detail or 'rate limit reached'}. Free models share a limited "
                                "pool, so try again in a minute or pick another model in Settings.")
        return BackendError(f"OpenRouter error {e.status}: {self._detail(e) or e.body[:300]}")

    def complete(self, system: str, messages: list[dict]) -> str:
        payload = {"model": self.model, "messages": _chat_messages(system, messages),
                   "response_format": {"type": "json_object"}}
        headers = self._headers()
        waits = list(RATE_LIMIT_WAITS)
        while True:
            try:
                data = _request(f"{OPENROUTER_URL}/chat/completions", payload, headers, timeout=self.timeout)
                break
            except HTTPError as e:
                # Not every model supports JSON mode: ask again without it.
                if e.status == 400 and "response_format" in payload:
                    del payload["response_format"]
                    continue
                # Rate limits and overloaded providers (common on free models) usually pass within seconds.
                if e.status in (429, 502, 503) and waits:
                    wait = waits.pop(0)
                    try:
                        wait = min(float(e.retry_after), 30) if e.retry_after else wait
                    except ValueError:
                        pass
                    time.sleep(wait)
                    continue
                raise self._error(e) from None
            except TimeoutError:
                raise BackendError(f"OpenRouter took longer than {self.timeout // 60} minutes.") from None
            except (urllib.error.URLError, OSError) as e:
                raise BackendError(f"Could not reach OpenRouter: {e}") from None
        if "error" in (data or {}):  # some provider errors arrive with HTTP 200
            err = data["error"]
            raise BackendError(f"OpenRouter: {err.get('message', err) if isinstance(err, dict) else err}")
        choice = ((data or {}).get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise BackendError("The response was cut off. Try a simpler widget or another model.")
        content = (choice.get("message") or {}).get("content") or ""
        if isinstance(content, list):  # some providers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content


def _anthropic_key_available(cfg) -> bool:
    env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR")
    return bool(cfg.get("anthropic_api_key") or any(os.environ.get(v) for v in env)
                or (Path.home() / ".config" / "anthropic").is_dir())  # an `ant auth login` profile


def _ollama_available(cfg) -> bool:
    try:
        return bool(OllamaBackend(url=cfg.get("ollama_url", "")).models())
    except SetupError:
        return False


def resolve_auto(cfg: dict) -> str:
    """The backend "auto" means right now: Claude Code, Anthropic key, Ollama, then OpenRouter."""
    if runtime.find_claude():
        return "claude-cli"
    if _anthropic_key_available(cfg):
        return "anthropic"
    if _ollama_available(cfg):
        return "ollama"
    if cfg.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    raise SetupError(NOTHING_SET_UP)


def from_config(cfg: dict):
    backend = cfg.get("backend", "auto")
    if backend == "auto":
        backend = resolve_auto(cfg)
    if backend == "anthropic":
        return AnthropicBackend(cfg.get("api_model") or "claude-opus-5", cfg.get("anthropic_api_key", ""))
    if backend == "ollama":
        return OllamaBackend(cfg.get("ollama_model", ""), cfg.get("ollama_url", ""),
                             int(cfg.get("ollama_context") or 16384))
    if backend == "openrouter":
        return OpenRouterBackend(cfg.get("openrouter_model", ""), cfg.get("openrouter_api_key", ""))
    return ClaudeCLIBackend(cfg.get("cli_model", ""))
