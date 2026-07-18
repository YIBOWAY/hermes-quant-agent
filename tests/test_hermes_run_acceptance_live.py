"""V2.12-A — six unfakeable acceptance tests against a REAL installed Hermes.

Boots the merged durable-runs code (worktree ``v2-integration``) as a SEPARATE
isolated gateway process (own ``HERMES_HOME``, free loopback port, discord/feishu
disabled, durable flag ON) plus a loopback OpenAI-compatible mock LLM. Drives
the six durable-run semantics over HTTP via ``OfficialHermesHttpAdapter``.

Red lines (enforced by construction):
* No external network — mock LLM + api_server both bind 127.0.0.1.
* Live gateway (launchd ``ai.hermes.gateway`` on :8642) is NEVER touched.
* No provider/paper/live/broker flips.
* Subprocess uses the live venv python with ``cwd=worktree`` so the editable
  install's PathFinder resolves the V2 code from the worktree, not live main.

Known real-Hermes contract divergences vs the fake suite (documented, not faked):
* SSE ``data:`` carries ``seq`` for resume; ``event_id`` is a DB column and is
  NOT on the wire (deferred from V2.11). Assertions use seq-level durability.
* Live status names while running: ``completed``/``cancelled``; after restart the
  store surfaces contract names ``succeeded``/``stopped``.
* Live stop of an in-flight run first returns ``status=stopping``; terminal
  ``stopped`` + ``idempotent_replay`` arrive after the agent is interrupted.
* Approval challenge TTL is hardcoded 300s — expiry is covered by white-box
  ``expires_at`` manipulation (not a 5-minute sleep).

Skip when the integration worktree or live venv python is missing (CI / machines
without the Hermes checkout).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from hqa.hermes_run_adapter import (
    HermesRunError,
    OfficialHermesHttpAdapter,
    UrllibLoopbackHttpTransport,
    evaluate_durable_run_availability,
)

# ---------------------------------------------------------------------------
# Paths — the isolated instance runs the MERGED durable-runs code.
# ---------------------------------------------------------------------------

_LIVE_HERMES = Path(os.environ.get(
    "HQA_HERMES_LIVE",
    str(Path.home() / ".hermes" / "hermes-agent"),
))
_INTEGRATION_WT = Path(os.environ.get(
    "HQA_HERMES_INTEGRATION_WT",
    str(_LIVE_HERMES / ".claude" / "worktrees" / "v2-integration"),
))
_VENV_PYTHON = Path(os.environ.get(
    "HQA_HERMES_VENV_PYTHON",
    str(_LIVE_HERMES / "venv" / "bin" / "python"),
))

_HAVE_HERMES = (
    _INTEGRATION_WT.is_dir()
    and (_INTEGRATION_WT / "gateway" / "run.py").is_file()
    and _VENV_PYTHON.is_file()
)

pytestmark = pytest.mark.skipif(
    not _HAVE_HERMES,
    reason="Hermes integration worktree / venv python not present",
)

_API_KEY = "hqa-v2-acceptance-key-32b-xxxx"  # >=16 chars, non-placeholder
_BODY = {"input": "hello research task", "model": "primary-x"}
_KEY = "acceptance-live-key-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, *, headers: Optional[Dict[str, str]] = None, timeout_s: float = 30.0) -> None:
    """Poll until a GET returns HTTP < 500 (auth 401 counts as 'up')."""
    deadline = time.time() + timeout_s
    last_err: Optional[BaseException] = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers or {}, method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:  # noqa: S310
                if resp.status < 500:
                    return
        except urllib.error.HTTPError as exc:
            # 401/404 mean the server is up and rejecting — that's readiness.
            if exc.code < 500:
                return
            last_err = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
        time.sleep(0.15)
    raise TimeoutError(f"server not ready at {url}: {last_err}")


# ---------------------------------------------------------------------------
# Loopback OpenAI-compatible mock LLM (scriptable per-test).
# ---------------------------------------------------------------------------


class MockLLMServer:
    """Minimal OpenAI chat-completions mock on 127.0.0.1.

    Hermes defaults to ``stream=True`` (conversation_loop.py). A non-stream
    JSON body is read as an empty SSE stream → EmptyStreamError → retries →
    false fallback. This mock ALWAYS speaks SSE when ``stream`` is truthy.

    Modes (set via ``set_mode``):
      * ``text`` — plain assistant message (run.completed).
      * ``tool_once`` — first call returns an ``execute_code`` tool_call
        (triggers approval); subsequent calls return plain text.
      * ``primary_429`` — model==primary-x returns 429; any other model
        returns plain text (forces authorized-chain fallback).
      * ``always_429`` — every call 429 (chain exhaustion → run.failed).
    """

    def __init__(self) -> None:
        self._mode = "text"
        self._calls = 0
        self._lock = threading.Lock()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
            self._calls = 0

    @staticmethod
    def _sse_chunks(chunks: List[dict]) -> bytes:
        parts = [f"data: {json.dumps(c)}\n\n".encode() for c in chunks]
        parts.append(b"data: [DONE]\n\n")
        return b"".join(parts)

    def _text_sse(self, model: str) -> bytes:
        cid = "chatcmpl-text"
        return self._sse_chunks([
            {
                "id": cid, "object": "chat.completion.chunk", "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": f"ok-from-{model or 'mock'}"},
                    "finish_reason": None,
                }],
            },
            {
                "id": cid, "object": "chat.completion.chunk", "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
                },
            },
        ])

    def _tool_sse(self, model: str) -> bytes:
        cid = "chatcmpl-tool"
        args = json.dumps({"code": "print(1)"})
        return self._sse_chunks([
            {
                "id": cid, "object": "chat.completion.chunk", "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_gate_1",
                            "type": "function",
                            "function": {"name": "execute_code", "arguments": ""},
                        }],
                    },
                    "finish_reason": None,
                }],
            },
            {
                "id": cid, "object": "chat.completion.chunk", "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"arguments": args},
                        }],
                    },
                    "finish_reason": None,
                }],
            },
            {
                "id": cid, "object": "chat.completion.chunk", "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "usage": {
                    "prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4,
                },
            },
        ])

    def _text_json(self, model: str) -> dict:
        return {
            "id": "chatcmpl-text",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": f"ok-from-{model or 'mock'}",
                },
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
            },
        }

    def _tool_json(self, model: str) -> dict:
        return {
            "id": "chatcmpl-tool",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_gate_1",
                        "type": "function",
                        "function": {
                            "name": "execute_code",
                            "arguments": json.dumps({"code": "print(1)"}),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {
                "prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4,
            },
        }

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                return

            def _read_json(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0:
                    return {}
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def _send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_sse(self, raw: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/").endswith("/models"):
                    self._send_json(200, {
                        "object": "list",
                        "data": [
                            {"id": "primary-x", "object": "model"},
                            {"id": "fallback-y", "object": "model"},
                        ],
                    })
                    return
                self._send_json(404, {"error": {"message": "not found"}})

            def do_POST(self):  # noqa: N802
                if not self.path.rstrip("/").endswith("/chat/completions"):
                    self._send_json(404, {"error": {"message": "not found"}})
                    return
                body = self._read_json()
                model = str(body.get("model") or "")
                want_stream = bool(body.get("stream"))
                with outer._lock:
                    outer._calls += 1
                    mode = outer._mode
                    n = outer._calls

                err_429 = {
                    "error": {
                        "message": "quota exceeded on primary"
                        if mode == "primary_429" else "quota exceeded",
                        "type": "rate_limit_error",
                        "code": "rate_limit",
                    }
                }
                if mode == "always_429":
                    self._send_json(429, err_429)
                    return
                if mode == "primary_429" and model == "primary-x":
                    self._send_json(429, err_429)
                    return

                use_tool = mode == "tool_once" and n == 1
                if want_stream:
                    raw = (
                        outer._tool_sse(model) if use_tool else outer._text_sse(model)
                    )
                    self._send_sse(raw)
                    return
                payload = (
                    outer._tool_json(model) if use_tool else outer._text_json(model)
                )
                self._send_json(200, payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


# ---------------------------------------------------------------------------
# Isolated Hermes gateway subprocess (durable ON, api_server only).
# ---------------------------------------------------------------------------


class IsolatedHermes:
    """Own HERMES_HOME + free port; runs worktree V2 code; zero live effect."""

    def __init__(self, *, mock_llm: MockLLMServer, tmp_path: Path) -> None:
        self.mock = mock_llm
        self.home = tmp_path / "hermes-home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        self.api_key = _API_KEY
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.db_path = self.home / "durable_runs.db"
        self._proc: Optional[subprocess.Popen] = None
        self._log_path = self.home / "gateway.stdout.log"
        self._write_config()

    def _write_config(self) -> None:
        # Minimal config: only api_server enabled; other platforms default off.
        # model.default set so _auto_detect_local_model is skipped.
        # fallback_providers is the authorized chain (config-only).
        # approvals.timeout raised so approval tests can POST before the
        # agent-thread wait expires (default 60s is tight under load).
        # Explicit enabled:false sets _enabled_explicit so env tokens cannot
        # auto-enable Discord/Telegram/... against the live gateway.
        disabled = {"enabled": False}
        cfg = {
            "model": {
                "provider": "custom",
                "default": "primary-x",
                "base_url": self.mock.base_url,
            },
            "fallback_providers": [
                {
                    "provider": "custom",
                    "model": "fallback-y",
                    "base_url": self.mock.base_url,
                    "api_key": "test",
                }
            ],
            "approvals": {
                "mode": "manual",
                "timeout": 300,
            },
            "platforms": {
                "api_server": {
                    "enabled": True,
                    "extra": {
                        "host": "127.0.0.1",
                        "port": self.port,
                        "key": self.api_key,
                        "durable_runs_enabled": True,
                    },
                },
                "discord": dict(disabled),
                "telegram": dict(disabled),
                "slack": dict(disabled),
                "whatsapp": dict(disabled),
                "signal": dict(disabled),
                "feishu": dict(disabled),
                "wecom": dict(disabled),
                "mattermost": dict(disabled),
                "matrix": dict(disabled),
                "homeassistant": dict(disabled),
                "email": dict(disabled),
                "sms": dict(disabled),
                "dingtalk": dict(disabled),
                "bluebubbles": dict(disabled),
                "qqbot": dict(disabled),
                "webhook": dict(disabled),
            },
        }
        # PyYAML may not be importable from HQA's venv; write YAML by hand.
        (self.home / "config.yaml").write_text(
            _to_yaml(cfg), encoding="utf-8"
        )

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        # Seed a blank .env under the isolated home so find_dotenv(usecwd=True)
        # never walks into the live ~/.hermes/.env when cwd is under HERMES_HOME.
        env_file = self.home / ".env"
        if not env_file.exists():
            env_file.write_text(
                "\n".join([
                    "DISCORD_BOT_TOKEN=",
                    "TELEGRAM_BOT_TOKEN=",
                    "SLACK_BOT_TOKEN=",
                    "SLACK_APP_TOKEN=",
                    "WHATSAPP_TOKEN=",
                    "FEISHU_APP_ID=",
                    "FEISHU_APP_SECRET=",
                    "",
                ]),
                encoding="utf-8",
            )
        env = os.environ.copy()
        # Isolation root — scopes config, durable DB, pid, sessions, logs.
        env["HERMES_HOME"] = str(self.home)
        # Belt-and-suspenders: also set the env knobs the adapter reads.
        env["API_SERVER_HOST"] = "127.0.0.1"
        env["API_SERVER_PORT"] = str(self.port)
        env["API_SERVER_KEY"] = self.api_key
        env["API_SERVER_DURABLE_RUNS"] = "1"
        # Scrub live messaging tokens so env auto-enable cannot fire even if
        # a platform entry is missing from config.yaml.
        for key in (
            "DISCORD_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN",
            "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_USER_TOKEN",
            "WHATSAPP_TOKEN", "SIGNAL_BOT_NUMBER",
            "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
            "MATTERMOST_TOKEN", "MATRIX_ACCESS_TOKEN",
            "DINGTALK_CLIENT_ID", "WECOM_BOT_ID", "HOMEASSISTANT_TOKEN",
        ):
            env.pop(key, None)
        # Keep the process quiet and local.
        env.pop("HTTP_PROXY", None)
        env.pop("HTTPS_PROXY", None)
        env.pop("ALL_PROXY", None)
        env["NO_PROXY"] = "127.0.0.1,localhost"
        # Resolve gateway.* from the integration worktree without cwd walking
        # into ~/.hermes (microsoft_teams find_dotenv usecwd=True).
        existing_pp = env.get("PYTHONPATH", "")
        pp_parts = [str(_INTEGRATION_WT)]
        if existing_pp:
            pp_parts.append(existing_pp)
        env["PYTHONPATH"] = os.pathsep.join(pp_parts)

        log_fh = open(self._log_path, "ab", buffering=0)  # noqa: SIM115
        # cwd=self.home (tmp) so find_dotenv cannot discover live ~/.hermes/.env.
        # PYTHONPATH=_INTEGRATION_WT keeps `python -m gateway.run` importable.
        # python -m gateway.run bypasses run_gateway's multiplexer guards
        # that would sys.exit when the LIVE default gateway is running.
        self._proc = subprocess.Popen(  # noqa: S603
            [str(_VENV_PYTHON), "-m", "gateway.run", "-v"],
            cwd=str(self.home),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group for clean kill
        )
        try:
            _wait_http(
                f"{self.base_url}/v1/capabilities",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout_s=45.0,
            )
        except Exception:
            self.stop()
            tail = ""
            if self._log_path.exists():
                tail = self._log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(
                f"isolated Hermes failed to become ready on :{self.port}\n"
                f"--- gateway log tail ---\n{tail}"
            )

    @staticmethod
    def _port_bindable(port: int, *, timeout_s: float = 5.0) -> bool:
        """True when 127.0.0.1:port can be bound without SO_REUSEADDR.

        Matches Hermes' Darwin bind policy (reuse_address=False). Process exit
        alone is insufficient — macOS TIME_WAIT keeps the tuple busy.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Explicitly no REUSEADDR — same constraint as api_server on Darwin.
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.05)
            finally:
                try:
                    s.close()
                except OSError:
                    pass
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                return
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait(timeout=5)
        # Best-effort: document readiness condition even when we rebind ports.
        self._port_bindable(self.port, timeout_s=2.0)

    def restart(self) -> None:
        """Kill + relaunch with the SAME HERMES_HOME (durable state survives).

        Allocates a fresh loopback port. Durable identity lives in
        HERMES_HOME/durable_runs.db, not the TCP port — same-port restart on
        Darwin races TIME_WAIT because api_server sets reuse_address=False.
        """
        old_port = self.port
        self.stop()
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._write_config()
        # If the allocator handed back the old port (rare), wait until bindable.
        if self.port == old_port and not self._port_bindable(self.port, timeout_s=30.0):
            self.port = _free_port()
            self.base_url = f"http://127.0.0.1:{self.port}"
            self._write_config()
        self.start()

    # -- white-box durable store -----------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"durable DB missing: {self.db_path}")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def wb_runs(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, idempotency_key, request_digest, status, "
                "requested_policy, actual_policy, fallback_reason, usage_json, "
                "created_at, updated_at FROM runs ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def wb_events(self, run_id: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id, run_id, seq, event_type, payload_json, created_at "
                "FROM run_events WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def wb_approvals(self, run_id: Optional[str] = None) -> List[dict]:
        with self._connect() as conn:
            if run_id is None:
                rows = conn.execute(
                    "SELECT challenge_id, run_id, action_digest, expires_at, "
                    "consumed, created_at FROM approval_grants"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT challenge_id, run_id, action_digest, expires_at, "
                    "consumed, created_at FROM approval_grants WHERE run_id=?",
                    (run_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def wb_force_expire_approval(self, challenge_id: str) -> None:
        """White-box: set expires_at in the past so the next consume is stale."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE approval_grants SET expires_at=? WHERE challenge_id=?",
                (time.time() - 10.0, challenge_id),
            )
            conn.commit()


def _to_yaml(obj: Any, indent: int = 0) -> str:
    """Tiny YAML emitter for the nested dicts we write (no PyYAML dep in HQA)."""
    sp = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}\n"
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{sp}{k}:")
                lines.append(_to_yaml(v, indent + 1).rstrip("\n"))
            elif isinstance(v, bool):
                lines.append(f"{sp}{k}: {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{sp}{k}: {v}")
            elif v is None:
                lines.append(f"{sp}{k}: null")
            else:
                # Quote strings that look special.
                s = str(v)
                if any(c in s for c in ":#{}[],&*?|>!%@`") or s == "" or s.strip() != s:
                    s = json.dumps(s)
                lines.append(f"{sp}{k}: {s}")
        return "\n".join(lines) + "\n"
    if isinstance(obj, list):
        if not obj:
            return f"{sp}[]\n"
        lines = []
        for item in obj:
            if isinstance(item, dict):
                # First key inline after '- ', rest indented.
                items = list(item.items())
                if not items:
                    lines.append(f"{sp}- {{}}")
                    continue
                k0, v0 = items[0]
                if isinstance(v0, (dict, list)):
                    lines.append(f"{sp}- {k0}:")
                    lines.append(_to_yaml(v0, indent + 2).rstrip("\n"))
                elif isinstance(v0, bool):
                    lines.append(f"{sp}- {k0}: {'true' if v0 else 'false'}")
                elif isinstance(v0, (int, float)):
                    lines.append(f"{sp}- {k0}: {v0}")
                else:
                    lines.append(f"{sp}- {k0}: {v0}")
                for k, v in items[1:]:
                    sub = _to_yaml({k: v}, indent + 1).rstrip("\n")
                    lines.append(sub)
            else:
                lines.append(f"{sp}- {item}")
        return "\n".join(lines) + "\n"
    return f"{sp}{obj}\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_llm():
    srv = MockLLMServer()
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture()
def hermes(mock_llm, tmp_path):
    inst = IsolatedHermes(mock_llm=mock_llm, tmp_path=tmp_path)
    inst.start()
    try:
        yield inst
    finally:
        inst.stop()


@pytest.fixture()
def adapter(hermes) -> OfficialHermesHttpAdapter:
    return OfficialHermesHttpAdapter(
        transport=UrllibLoopbackHttpTransport(
            base_url=hermes.base_url,
            api_key=hermes.api_key,
            timeout_s=30.0,
        )
    )


def _wait_status(adapter, run_id: str, terminals=None, timeout_s: float = 30.0) -> str:
    terminals = set(terminals or {
        "completed", "failed", "cancelled",  # live names
        "succeeded", "stopped",              # store/contract names (post-restart)
    })
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            snap = adapter.get_status(run_id)
            last = snap.status
            if last in terminals:
                return last
        except HermesRunError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} did not reach {terminals}; last={last}")


def _wait_approval_event(adapter, run_id: str, timeout_s: float = 30.0) -> dict:
    """Poll status until waiting_for_approval, then pull challenge from SSE/store.

    We can't hang on the live SSE (it stays open until terminal). Instead:
    poll GET status for waiting_for_approval, then white-box the grant OR
    do a short SSE read is wrong. The approval.request is durable — but the
    client needs challenge_id+action_digest. Those live in the durable event
    plane AND the approval_grants table. White-box the grant for the digest
    is incomplete (digest is there); challenge_id is the PK. For the event
    payload fields the client must echo, we open SSE with a short timeout
    after the run is known to be waiting — but OfficialHermesHttpAdapter
    get_sse reads to EOF. So: white-box the grant for challenge_id+digest,
    which is exactly what the server issued.
    """
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            snap = adapter.get_status(run_id)
            last = snap.status
            # Upstream names waiting_for_approval as a live status; the store
            # mirrors it as 'running'. Either way the grant row exists once
            # the gate has fired.
            if last in {"waiting_for_approval", "running"}:
                # Grant may already be there.
                return {"status": last}
        except HermesRunError:
            pass
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} never entered approval wait; last={last}")


# ---------------------------------------------------------------------------
# #0 — smoke: durable capabilities grounded
# ---------------------------------------------------------------------------


class TestLiveCapabilities:
    def test_durable_block_grounded(self, adapter) -> None:
        caps = adapter.capabilities()
        assert caps["object"] == "hermes.api_server.capabilities"
        assert isinstance(caps.get("contract_version"), int)
        durable = caps["durable"]
        for cap in (
            "idempotency", "event_replay", "approval_cas",
            "idempotent_stop", "restart_reconcile", "run_evidence",
        ):
            assert durable[cap]["supported"] is True, cap
            assert durable[cap]["grounded"] is True, cap

    def test_durable_availability_gate_opens_when_broker_on(self, adapter) -> None:
        """Plan §V2 line 528: when the six probes are grounded, dispatch may open.

        The isolated instance boots with durable ON, so require_durable_available
        must be a no-raise. The complementary case (live install flag OFF →
        durable_unavailable / dispatch closed) is covered hermetically in
        tests/test_hermes_run_adapter.py::TestPortDurableAvailabilityGate.
        """
        avail = adapter.require_durable_available()
        assert avail.available is True
        assert avail.blockers == ()
        assert avail.contract_version is not None


# ---------------------------------------------------------------------------
# #1 + #2 — idempotency: recover by identity, one run, digest conflict
# ---------------------------------------------------------------------------


class TestLiveIdempotency:
    def test_duplicate_submit_one_run_whitebox(self, adapter, hermes, mock_llm) -> None:
        mock_llm.set_mode("text")
        a = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        b = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert a.run_id == b.run_id
        assert (a.created, b.created) == (True, False)
        # White-box: exactly ONE run persisted (defeats shadow-run projections).
        runs = hermes.wb_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == a.run_id

    def test_same_key_different_digest_conflicts(self, adapter, hermes, mock_llm) -> None:
        mock_llm.set_mode("text")
        first = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        with pytest.raises(HermesRunError) as exc:
            adapter.submit_or_get(
                idempotency_key=_KEY, request_body={"input": "tampered", "model": "primary-x"}
            )
        assert exc.value.code == "idempotency_conflict"
        # Conflict created no second run.
        assert len(hermes.wb_runs()) == 1
        assert hermes.wb_runs()[0]["run_id"] == first.run_id

    def test_recover_by_identity_after_restart(self, adapter, hermes, mock_llm) -> None:
        """Acceptance #1 against real Hermes: after a process restart the SAME
        Idempotency-Key recovers the SAME run_id (client never needed the ack)."""
        mock_llm.set_mode("text")
        first = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        _wait_status(adapter, first.run_id)  # let it finish so restart is clean
        # White-box the persisted identity BEFORE the kill.
        (record,) = hermes.wb_runs()
        persisted_run_id = record["run_id"]
        assert persisted_run_id == first.run_id

        hermes.restart()
        # Fresh adapter against the relaunched process (same port/key/home).
        adapter2 = OfficialHermesHttpAdapter(
            transport=UrllibLoopbackHttpTransport(
                base_url=hermes.base_url, api_key=hermes.api_key, timeout_s=30.0
            )
        )
        recovered = adapter2.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert recovered.created is False
        assert recovered.run_id == persisted_run_id
        # Still exactly one run after recovery.
        assert len(hermes.wb_runs()) == 1


# ---------------------------------------------------------------------------
# #3 — status / events / evidence survive a real process restart
# ---------------------------------------------------------------------------


class TestLiveStateSurvivesRestart:
    def test_status_events_evidence_survive_restart(
        self, adapter, hermes, mock_llm
    ) -> None:
        # Force a real fallback so requested-vs-actual diverges (V2.6b).
        mock_llm.set_mode("primary_429")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        status = _wait_status(adapter, handle.run_id)
        assert status in {"completed", "succeeded"}

        before = adapter.get_status(handle.run_id)
        before_events = [
            (e.seq, e.event_type) for e in adapter.stream_events(handle.run_id)
        ]
        assert before.fallback_reason is not None
        assert "fallback-y" in before.fallback_reason
        assert before.requested_policy is not None
        assert before.requested_policy.get("model") == "primary-x"
        assert before.actual_policy is not None
        assert before.actual_policy.get("model") == "fallback-y"
        assert len(before_events) >= 1

        # White-box: the store holds the same evidence.
        (row,) = hermes.wb_runs()
        assert row["fallback_reason"] and "fallback-y" in row["fallback_reason"]
        actual = json.loads(row["actual_policy"] or "{}")
        assert actual.get("model") == "fallback-y"

        hermes.restart()
        adapter2 = OfficialHermesHttpAdapter(
            transport=UrllibLoopbackHttpTransport(
                base_url=hermes.base_url, api_key=hermes.api_key, timeout_s=30.0
            )
        )
        after = adapter2.get_status(handle.run_id)
        after_events = [
            (e.seq, e.event_type) for e in adapter2.stream_events(handle.run_id)
        ]

        # After restart the store surfaces the contract name 'succeeded'.
        assert after.status in {"succeeded", "completed"}
        assert after.requested_policy == before.requested_policy
        assert after.actual_policy == before.actual_policy
        assert after.fallback_reason == before.fallback_reason
        # Canonical event plane: same (seq, type) sequence, gapless.
        assert after_events == before_events
        seqs = [s for s, _ in after_events]
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


# ---------------------------------------------------------------------------
# #4 — gapless cursor replay; disconnect does not delete
# ---------------------------------------------------------------------------


class TestLiveEventPlane:
    def test_cursor_replay_gapless_and_dup_free(self, adapter, hermes, mock_llm) -> None:
        mock_llm.set_mode("text")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        _wait_status(adapter, handle.run_id)

        full = adapter.stream_events(handle.run_id)
        seqs = [e.seq for e in full]
        assert len(seqs) >= 1
        # Contiguous unique range.
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
        assert len(set(seqs)) == len(seqs)
        # Per-cursor: every window is the strict suffix.
        for i, ev in enumerate(full):
            window = adapter.stream_events(handle.run_id, since_seq=ev.seq)
            assert [e.seq for e in window] == seqs[i + 1:]
            assert all(e.seq > ev.seq for e in window)
        assert adapter.stream_events(handle.run_id, since_seq=seqs[-1]) == []

    def test_disconnect_does_not_delete_canonical_events(
        self, adapter, hermes, mock_llm
    ) -> None:
        mock_llm.set_mode("text")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        _wait_status(adapter, handle.run_id)
        before = [(e.seq, e.event_type) for e in adapter.stream_events(handle.run_id)]
        # "Disconnect" = drop the client; reconnect and re-read from 0.
        after = [(e.seq, e.event_type) for e in adapter.stream_events(handle.run_id)]
        assert after == before
        # White-box confirms the store still holds them.
        assert len(hermes.wb_events(handle.run_id)) == len(before)


# ---------------------------------------------------------------------------
# #5 — authorized fallback only; requested-vs-actual divergence (V2.6b)
# ---------------------------------------------------------------------------


class TestLiveAuthorizedFallback:
    def test_in_chain_fallback_records_reason_and_actual(
        self, adapter, hermes, mock_llm
    ) -> None:
        mock_llm.set_mode("primary_429")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        status = _wait_status(adapter, handle.run_id)
        assert status in {"completed", "succeeded"}
        snap = adapter.get_status(handle.run_id)
        assert snap.requested_policy is not None
        assert snap.requested_policy.get("model") == "primary-x"
        assert snap.actual_policy is not None
        assert snap.actual_policy.get("model") == "fallback-y"
        assert snap.fallback_reason is not None
        assert "fallback-y" in snap.fallback_reason
        # White-box: store agrees (defeats a projection that only answers GET).
        (row,) = hermes.wb_runs()
        assert json.loads(row["actual_policy"] or "{}").get("model") == "fallback-y"
        assert row["fallback_reason"] and "fallback-y" in row["fallback_reason"]

    def test_chain_exhaustion_fails_closed(self, adapter, hermes, mock_llm) -> None:
        """When every provider in the authorized chain fails, the run fails
        closed — no unauthorized target is ever consulted (the chain IS the
        allowlist; there is no implicit default)."""
        mock_llm.set_mode("always_429")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        status = _wait_status(adapter, handle.run_id, timeout_s=60.0)
        assert status == "failed"
        # requested preserved; no success evidence for an unauthorized hop.
        snap = adapter.get_status(handle.run_id)
        assert snap.requested_policy is not None
        assert snap.requested_policy.get("model") == "primary-x"
        # No run.completed success event.
        events = adapter.stream_events(handle.run_id)
        assert not any(e.event_type == "run.completed" for e in events)
        assert any(e.event_type == "run.failed" for e in events)


# ---------------------------------------------------------------------------
# #6 — approval CAS + idempotent stop
# ---------------------------------------------------------------------------


class TestLiveApprovalAndStop:
    def test_approval_single_use_and_digest_mismatch(
        self, adapter, hermes, mock_llm
    ) -> None:
        mock_llm.set_mode("tool_once")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)

        # Wait until the gate has issued a challenge (grant row appears).
        challenge: Optional[dict] = None
        deadline = time.time() + 45.0
        while time.time() < deadline:
            grants = hermes.wb_approvals(handle.run_id)
            if grants:
                challenge = grants[0]
                break
            time.sleep(0.15)
        assert challenge is not None, "no approval grant issued (gate never fired)"
        ch_id = challenge["challenge_id"]
        digest = challenge["action_digest"]
        assert challenge["consumed"] in (0, False, None) or int(challenge["consumed"]) == 0

        # Digest mismatch must NOT consume the grant.
        with pytest.raises(HermesRunError) as exc:
            adapter.respond_approval(
                handle.run_id,
                choice="once",
                challenge_id=ch_id,
                action_digest="forged-digest",
            )
        assert exc.value.code in {
            "approval_challenge_invalid",
            "approval_challenge_required",
        }
        # Grant still consumable (reject-then-valid-retry).
        grants_after = hermes.wb_approvals(handle.run_id)
        assert len(grants_after) == 1
        assert int(grants_after[0]["consumed"] or 0) == 0

        # Valid consume succeeds exactly once.
        ok = adapter.respond_approval(
            handle.run_id, choice="once", challenge_id=ch_id, action_digest=digest
        )
        assert ok.resolved >= 1
        # Replay rejected; grant stays consumed=1.
        with pytest.raises(HermesRunError) as exc2:
            adapter.respond_approval(
                handle.run_id, choice="once", challenge_id=ch_id, action_digest=digest
            )
        assert exc2.value.code == "approval_challenge_invalid"
        grants_final = hermes.wb_approvals(handle.run_id)
        assert int(grants_final[0]["consumed"] or 0) == 1

        # Let the run finish after approval (mock returns text on 2nd LLM call).
        _wait_status(adapter, handle.run_id, timeout_s=45.0)

    def test_expired_grant_rejected_without_consuming(
        self, adapter, hermes, mock_llm
    ) -> None:
        mock_llm.set_mode("tool_once")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge: Optional[dict] = None
        deadline = time.time() + 45.0
        while time.time() < deadline:
            grants = hermes.wb_approvals(handle.run_id)
            if grants:
                challenge = grants[0]
                break
            time.sleep(0.15)
        assert challenge is not None
        ch_id = challenge["challenge_id"]
        digest = challenge["action_digest"]

        # White-box expire (TTL is hardcoded 300s; we don't sleep 5 minutes).
        hermes.wb_force_expire_approval(ch_id)

        with pytest.raises(HermesRunError) as exc:
            adapter.respond_approval(
                handle.run_id, choice="once", challenge_id=ch_id, action_digest=digest
            )
        assert exc.value.code == "approval_challenge_invalid"
        # Expired attempt did not consume (consumed still 0) — fact unchanged.
        grants = hermes.wb_approvals(handle.run_id)
        assert int(grants[0]["consumed"] or 0) == 0

    def test_stop_is_idempotent_across_restart(
        self, adapter, hermes, mock_llm
    ) -> None:
        mock_llm.set_mode("text")
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        # Let it reach a terminal state first, then stop is pure idempotent replay.
        _wait_status(adapter, handle.run_id)

        first = adapter.stop(handle.run_id)
        # After terminal, stop returns stopped + idempotent_replay (V2.8).
        assert first.status in {"stopped", "stopping", "cancelled", "completed", "succeeded"}
        second = adapter.stop(handle.run_id)
        assert second.status == first.status or second.status == "stopped"
        # At least one of the stops must advertise the replay (the post-terminal one).
        assert first.idempotent_replay or second.idempotent_replay

        hermes.restart()
        adapter2 = OfficialHermesHttpAdapter(
            transport=UrllibLoopbackHttpTransport(
                base_url=hermes.base_url, api_key=hermes.api_key, timeout_s=30.0
            )
        )
        third = adapter2.stop(handle.run_id)
        assert third.idempotent_replay is True
        assert third.status == "stopped"
        # White-box: run is terminal stopped/succeeded, never lost.
        (row,) = hermes.wb_runs()
        assert row["status"] in {"stopped", "succeeded", "failed"}
        assert row["run_id"] == handle.run_id
