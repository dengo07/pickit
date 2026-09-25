"""Ollama and OpenRouter backends against a local mock HTTP server, and backend auto-detection."""

import json
import socket
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pickit import backends, generator
from pickit.backends import BackendError, OllamaBackend, OpenRouterBackend, SetupError

MESSAGES = [{"role": "user", "content": "a clock"}]


class MockServer:
    """Answers each path from `routes`: {path: (status, body) or [(status, body), ...] in order}."""

    def __init__(self, routes):
        self.routes = {k: list(v) if isinstance(v, list) else [v] for k, v in routes.items()}
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                server.requests.append({"path": self.path, "method": self.command,
                                        "headers": dict(self.headers), "body": body})
                answers = server.routes.get(self.path) or [(404, {"error": "no route"})]
                status, reply = answers.pop(0) if len(answers) > 1 else answers[0]
                data = json.dumps(reply).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def mock():
    servers = []

    def make(routes):
        servers.append(MockServer(routes))
        return servers[-1]
    yield make
    for s in servers:
        s.close()


def dead_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def chat_reply(content):
    return 200, {"message": {"role": "assistant", "content": content}, "done": True}


TAGS = (200, {"models": [{"name": "llama3.2:latest", "details": {"parameter_size": "3.2B"}},
                         {"name": "nomic-embed-text:latest", "details": {"families": ["nomic-bert"]}},
                         {"name": "qwen3.5:9b", "details": {"parameter_size": "9.7B"}},
                         {"name": "smollm2:135m", "details": {"parameter_size": "134.52M"}}]})


class TestOllama:
    def test_request_and_reply(self, mock):
        srv = mock({"/api/chat": chat_reply('{"name": "Clock"}')})
        out = OllamaBackend("qwen3.5:9b", srv.url, context=12000).complete("SYSTEM", MESSAGES)
        assert out == '{"name": "Clock"}'
        body = srv.requests[0]["body"]
        assert body["model"] == "qwen3.5:9b" and body["stream"] is False and body["format"] == "json"
        assert body["think"] is False
        assert body["options"]["num_ctx"] == 12000
        assert body["messages"] == [{"role": "system", "content": "SYSTEM"}] + MESSAGES

    def test_context_grows_for_long_requests(self, mock):
        srv = mock({"/api/chat": chat_reply("{}")})
        OllamaBackend("m", srv.url, context=16384).complete("S" * 60000, MESSAGES)
        assert srv.requests[0]["body"]["options"]["num_ctx"] == 28672  # 20000 + 6144 tokens, rounded up

    def test_runaway_reply(self, mock):
        srv = mock({"/api/chat": (200, {"message": {"content": "{   "}, "done_reason": "length"})})
        with pytest.raises(BackendError, match="didn't finish"):
            OllamaBackend("tiny", srv.url).complete("S", MESSAGES)

    def test_models_skip_embeddings_largest_first(self, mock):
        srv = mock({"/api/tags": TAGS})
        assert OllamaBackend("", srv.url).models() == ["qwen3.5:9b", "llama3.2:latest", "smollm2:135m"]

    def test_empty_model_uses_largest(self, mock):
        srv = mock({"/api/tags": TAGS, "/api/chat": chat_reply("{}")})
        OllamaBackend("", srv.url).complete("S", MESSAGES)
        assert srv.requests[-1]["body"]["model"] == "qwen3.5:9b"

    def test_no_models_installed(self, mock):
        srv = mock({"/api/tags": (200, {"models": []})})
        with pytest.raises(SetupError, match="ollama pull"):
            OllamaBackend("", srv.url).complete("S", MESSAGES)

    def test_missing_model(self, mock):
        srv = mock({"/api/chat": (404, {"error": "model 'nope' not found"})})
        with pytest.raises(SetupError, match="ollama pull nope"):
            OllamaBackend("nope", srv.url).complete("S", MESSAGES)

    def test_other_http_error(self, mock):
        srv = mock({"/api/chat": (500, {"error": "out of memory"})})
        with pytest.raises(BackendError, match="out of memory") as info:
            OllamaBackend("m", srv.url).complete("S", MESSAGES)
        assert not isinstance(info.value, SetupError)

    def test_not_running(self):
        with pytest.raises(SetupError, match="isn't running"):
            OllamaBackend("m", dead_url()).complete("S", MESSAGES)

    def test_url_from_env_and_scheme(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
        assert OllamaBackend().url == "http://10.0.0.5:11434"
        assert OllamaBackend(url="http://box:1/").url == "http://box:1"
        monkeypatch.setenv("OLLAMA_HOST", ":8080")
        assert OllamaBackend().url == "http://127.0.0.1:8080"

    def test_check(self, mock):
        srv = mock({"/api/tags": TAGS})
        assert "3 models" in OllamaBackend("qwen3.5:9b", srv.url).check()
        assert OllamaBackend("llama3.2", srv.url).check()  # ":latest" is implied
        with pytest.raises(SetupError, match="ollama pull gemma4"):
            OllamaBackend("gemma4", srv.url).check()


def completion(content, finish="stop"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


@pytest.fixture
def openrouter(mock, monkeypatch):
    def make(routes):
        srv = mock(routes)
        monkeypatch.setattr(backends, "OPENROUTER_URL", srv.url)
        return srv
    return make


class TestOpenRouter:
    def test_request_and_reply(self, openrouter):
        srv = openrouter({"/chat/completions": completion('{"name": "Clock"}')})
        out = OpenRouterBackend("google/gemini-3.8-flash", "sk-or-test").complete("SYSTEM", MESSAGES)
        assert out == '{"name": "Clock"}'
        req = srv.requests[0]
        assert req["headers"]["Authorization"] == "Bearer sk-or-test"
        assert req["body"]["model"] == "google/gemini-3.8-flash"
        assert req["body"]["response_format"] == {"type": "json_object"}
        assert req["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}

    def test_retries_without_json_mode(self, openrouter):
        srv = openrouter({"/chat/completions": [(400, {"error": {"message": "response_format unsupported"}}),
                                                completion("{}")]})
        assert OpenRouterBackend("qwen/qwen3.8-27b:free", "k").complete("S", MESSAGES) == "{}"
        assert "response_format" in srv.requests[0]["body"]
        assert "response_format" not in srv.requests[1]["body"]

    @pytest.mark.parametrize("status, error, kind", [
        (401, "API key", SetupError),
        (402, "credits", BackendError),
        (404, "doesn't offer", SetupError),
        (429, "try again in a minute", BackendError),
    ])
    def test_errors(self, openrouter, monkeypatch, status, error, kind):
        monkeypatch.setattr(backends, "RATE_LIMIT_WAITS", ())
        openrouter({"/chat/completions": (status, {"error": {"message": "nope"}})})
        with pytest.raises(kind, match=error):
            OpenRouterBackend("m", "k").complete("S", MESSAGES)

    def test_rate_limit_retries_then_explains(self, openrouter, monkeypatch):
        slept = []
        monkeypatch.setattr(backends.time, "sleep", slept.append)
        busy = (429, {"error": {"message": "Provider returned error",
                                "metadata": {"raw": "m:free is temporarily rate-limited upstream"}}})
        srv = openrouter({"/chat/completions": [busy, busy, busy, completion("{}")]})
        with pytest.raises(BackendError, match="temporarily rate-limited upstream"):
            OpenRouterBackend("m:free", "k").complete("S", MESSAGES)
        assert slept == [5, 15] and len(srv.requests) == 3

    def test_rate_limit_recovers(self, openrouter, monkeypatch):
        monkeypatch.setattr(backends.time, "sleep", lambda s: None)
        openrouter({"/chat/completions": [(429, {"error": {"message": "slow down"}}),
                                          (503, {"error": {"message": "Service temporarily overloaded"}}),
                                          completion("{}")]})
        assert OpenRouterBackend("m", "k").complete("S", MESSAGES) == "{}"

    def test_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(SetupError, match="openrouter.ai/keys"):
            OpenRouterBackend("m", "").complete("S", MESSAGES)

    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
        assert OpenRouterBackend().api_key == "sk-or-env"

    def test_error_inside_200(self, openrouter):
        openrouter({"/chat/completions": (200, {"error": {"message": "provider exploded"}})})
        with pytest.raises(BackendError, match="provider exploded"):
            OpenRouterBackend("m", "k").complete("S", MESSAGES)

    def test_cut_off(self, openrouter):
        openrouter({"/chat/completions": completion('{"na', finish="length")})
        with pytest.raises(BackendError, match="cut off"):
            OpenRouterBackend("m", "k").complete("S", MESSAGES)

    def test_content_parts(self, openrouter):
        openrouter({"/chat/completions": (200, {"choices": [{"message": {"content": [
            {"type": "text", "text": '{"a":'}, {"type": "text", "text": " 1}"}]}}]})})
        assert OpenRouterBackend("m", "k").complete("S", MESSAGES) == '{"a": 1}'

    def test_check(self, openrouter):
        openrouter({"/key": (200, {"data": {"label": "x", "limit_remaining": 4.5}}),
                    "/models/qwen/qwen3.8-27b:free/endpoints": (200, {"data": {}})})
        assert OpenRouterBackend("qwen/qwen3.8-27b:free", "k").check() == \
            "Key works · $4.50 credit left · qwen/qwen3.8-27b:free is available"
        with pytest.raises(SetupError, match="doesn't offer"):
            OpenRouterBackend("nope/model", "k").check()


def test_https_finds_other_distros_certificates(monkeypatch, tmp_path):
    """The AppImage's OpenSSL looks in Ubuntu's location; Fedora and openSUSE keep them elsewhere."""
    bundle = tmp_path / "ca-bundle.crt"
    bundle.write_text("")
    monkeypatch.setattr(backends.ssl, "get_default_verify_paths",
                        lambda: types.SimpleNamespace(cafile=None, capath=None))
    monkeypatch.setattr(backends, "CA_BUNDLES", ("/nonexistent/ca.crt", str(bundle)))
    seen = []
    monkeypatch.setattr(backends.ssl, "create_default_context", lambda cafile=None: seen.append(cafile))
    backends._ssl_context.cache_clear()
    try:
        backends._ssl_context()
    finally:
        backends._ssl_context.cache_clear()
    assert seen == [str(bundle)]


@pytest.fixture
def bare(monkeypatch, tmp_path):
    """No Claude CLI, no keys in the environment, no Anthropic profile."""
    monkeypatch.setattr(backends.runtime, "find_claude", lambda: None)
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR",
                "OPENROUTER_API_KEY", "OLLAMA_HOST"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return {"backend": "auto", "ollama_url": dead_url()}


class TestAuto:
    def test_prefers_claude_cli(self, bare, monkeypatch):
        monkeypatch.setattr(backends.runtime, "find_claude", lambda: "/usr/bin/claude")
        assert backends.resolve_auto({**bare, "openrouter_api_key": "k"}) == "claude-cli"

    def test_anthropic_key(self, bare):
        assert backends.resolve_auto({**bare, "anthropic_api_key": "sk-ant", "openrouter_api_key": "k"}) \
            == "anthropic"

    def test_ollama_with_models(self, bare, mock):
        srv = mock({"/api/tags": TAGS})
        cfg = {**bare, "ollama_url": srv.url, "openrouter_api_key": "k"}
        assert backends.resolve_auto(cfg) == "ollama"
        assert isinstance(backends.from_config(cfg), OllamaBackend)

    def test_ollama_without_models_is_skipped(self, bare, mock):
        srv = mock({"/api/tags": (200, {"models": []})})
        assert backends.resolve_auto({**bare, "ollama_url": srv.url, "openrouter_api_key": "k"}) == "openrouter"

    def test_nothing_set_up(self, bare):
        with pytest.raises(SetupError, match="Ollama"):
            backends.from_config(bare)

    def test_explicit_choices(self, bare):
        assert isinstance(backends.from_config({**bare, "backend": "openrouter"}), OpenRouterBackend)
        ollama = backends.from_config({**bare, "backend": "ollama", "ollama_model": "m", "ollama_context": 8192})
        assert (ollama.model, ollama.context) == ("m", 8192)


class FakeBackend:
    def __init__(self, replies, repair_attempts=None):
        self.replies, self.calls = list(replies), 0
        if repair_attempts is not None:
            self.repair_attempts = repair_attempts

    def complete(self, system, messages):
        self.calls += 1
        return self.replies.pop(0)


GOOD = json.dumps({"name": "C", "engine": "native", "ui": {"type": "label", "text": "{now|time:%H:%M}"}})


class TestRepairAttempts:
    def test_default_is_one_repair(self):
        backend = FakeBackend(["nope", "still nope", GOOD])
        with pytest.raises(generator.SpecError):
            generator.generate(backend, "a clock")
        assert backend.calls == 2

    def test_backend_can_ask_for_more(self):
        backend = FakeBackend(["nope", "still nope", GOOD], repair_attempts=2)
        assert generator.generate(backend, "a clock")["name"] == "C"
        assert backend.calls == 3
