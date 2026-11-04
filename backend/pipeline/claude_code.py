"""Run Claude through the local Claude Code CLI (`claude -p`), using the user's Claude subscription login.

Same interface as pipeline.claude_client.Claude (stream_text / complete / json / text_of), so every
pipeline step works with either provider. Each call is a fresh, tool-less (except web search),
non-persistent headless session in an empty working directory.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

from pipeline import procs
from pipeline.claude_client import ClaudeError

# Long system prompts go into the prompt body instead, to stay under Windows' command-line limit.
MAX_SYSTEM_ARG = 12000
TIMEOUT_S = 20 * 60


def find_cli() -> str | None:
    return shutil.which("claude")


def auth_status() -> dict[str, Any]:
    """{'installed': bool, 'logged_in': bool, 'method': str | None, 'error': str | None}"""
    cli = find_cli()
    if not cli:
        return {"installed": False, "logged_in": False, "method": None,
                "error": "Claude Code is not installed or not on PATH."}
    try:
        proc = subprocess.run([cli, "auth", "status"], capture_output=True, timeout=30, env=_env())
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
        return {"installed": True, "logged_in": bool(data.get("loggedIn")), "method": data.get("authMethod"),
                "error": None if data.get("loggedIn") else "Claude Code is not logged in. Run: claude auth login"}
    except (subprocess.SubprocessError, ValueError) as e:
        return {"installed": True, "logged_in": False, "method": None, "error": f"Could not check Claude Code login: {e}"}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # An API key in the environment would make Claude Code bill the API instead of the subscription.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system or [] if isinstance(b, dict))


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b["text"])
        elif getattr(b, "type", None) == "text":
            parts.append(b.text)
    return "\n".join(parts)


def _prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten a conversation into one prompt (headless mode takes a single user turn)."""
    if len(messages) == 1:
        return _content_text(messages[0]["content"])
    lines = ["Earlier in this conversation:"]
    for m in messages[:-1]:
        who = "Channel owner" if m["role"] == "user" else "You"
        lines.append(f"\n[{who}]\n{_content_text(m['content'])}")
    lines.append("\n---\nNow respond to this latest message:\n")
    lines.append(_content_text(messages[-1]["content"]))
    return "\n".join(lines)


class ClaudeCode:
    def __init__(self, cfg: dict[str, Any], workdir: Path):
        self.cli = find_cli()
        if not self.cli:
            raise ClaudeError("Claude Code (the `claude` command) was not found. Install it, or switch the "
                              "Claude provider to 'api' on the Settings page.")
        self.model = cfg.get("code_model") or "opus"
        self.fallback_model = cfg.get("code_fallback_model") or "sonnet"
        self.effort = cfg.get("effort", "high")
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)

    # -- internals -----------------------------------------------------------

    def _args(self, system: Any, fmt: str, tools: list[dict[str, Any]] | None, effort: str | None,
              schema: dict[str, Any] | None = None) -> tuple[list[str], str]:
        sys_text = _system_text(system)
        prefix = ""
        args = [self.cli, "-p", "--output-format", fmt, "--model", self.model,
                "--effort", effort or self.effort, "--no-session-persistence", "--setting-sources", ""]
        if self.fallback_model and self.fallback_model != self.model:
            args += ["--fallback-model", self.fallback_model]
        if fmt == "stream-json":
            args += ["--verbose", "--include-partial-messages"]
        if tools and any(t.get("name") in ("web_search", "web_fetch") for t in tools):
            args += ["--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch"]
        else:
            args += ["--tools", ""]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema)]
        if len(sys_text) <= MAX_SYSTEM_ARG:
            args += ["--system-prompt", sys_text]
        else:
            args += ["--system-prompt", "Follow the instructions at the start of the user's message exactly."]
            prefix = f"<instructions>\n{sys_text}\n</instructions>\n\n"
        return args, prefix

    def _popen(self, args: list[str], prompt: str) -> subprocess.Popen:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=self.workdir, env=_env())
        # Write the prompt on a thread so a large prompt can't deadlock against stdout.
        def feed() -> None:
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass
        threading.Thread(target=feed, daemon=True).start()
        return proc

    @staticmethod
    def _raise_for(result: dict[str, Any] | None, stderr: str, code: int | None) -> None:
        if result and not result.get("is_error") and result.get("subtype") == "success":
            return
        msg = (result or {}).get("result") or stderr.strip() or f"claude exited with code {code}"
        low = msg.lower()
        if "limit" in low and ("usage" in low or "reset" in low or "reached" in low):
            raise ClaudeError(f"Claude Pro usage limit reached: {msg}")
        if "login" in low or "authenticat" in low or "/login" in low:
            raise ClaudeError(f"Claude Code is not logged in ({msg}). Run `claude auth login` in a terminal.")
        if (result or {}).get("subtype") == "error_max_structured_output_retries":
            raise ClaudeError("Claude could not produce output in the required format. Try again.")
        raise ClaudeError(f"Claude Code error: {msg}")

    # -- public API (mirrors pipeline.claude_client.Claude) ------------------

    def stream_text(self, system: Any, messages: list[dict[str, Any]], max_tokens: int = 64000,
                    tools: list[dict[str, Any]] | None = None) -> Iterator[str]:
        args, prefix = self._args(system, "stream-json", tools, None)
        proc = self._popen(args, prefix + _prompt(messages))
        result: dict[str, Any] | None = None
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                try:
                    ev = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if ev.get("type") == "stream_event":
                    e = ev["event"]
                    if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                        yield e["delta"]["text"]
                elif ev.get("type") == "result":
                    result = ev
            proc.wait(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        self._raise_for(result, stderr, proc.returncode)

    def _run_json(self, system: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                  effort: str | None, schema: dict[str, Any] | None) -> dict[str, Any]:
        args, prefix = self._args(system, "json", tools, effort, schema)
        procs.check()
        proc = self._popen(args, prefix + _prompt(messages))
        try:
            with procs.track(proc):
                out, err = proc.communicate(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            procs.kill(proc)
            raise ClaudeError("Claude Code took too long to respond.")
        procs.check()
        try:
            result = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            result = None
        self._raise_for(result, err.decode("utf-8", "replace"), proc.returncode)
        return result  # type: ignore[return-value]

    def complete(self, system: Any, messages: list[dict[str, Any]], max_tokens: int = 64000,
                 tools: list[dict[str, Any]] | None = None, effort: str | None = None) -> Any:
        result = self._run_json(system, messages, tools, effort, None)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=result.get("result", ""))],
                               stop_reason="end_turn")

    def json(self, system: Any, messages: list[dict[str, Any]], schema: dict[str, Any],
             max_tokens: int = 32000, effort: str | None = None) -> dict[str, Any]:
        result = self._run_json(system, messages, None, effort, schema)
        data = result.get("structured_output")
        if data is None:
            try:
                data = json.loads(result.get("result", ""))
            except ValueError as e:
                raise ClaudeError(f"Claude returned invalid JSON: {e}") from e
        return data

    @staticmethod
    def text_of(msg: Any) -> str:
        return "".join(b.text for b in msg.content if b.type == "text")
