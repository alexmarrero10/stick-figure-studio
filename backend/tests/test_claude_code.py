
import pytest

from pipeline import claude_code
from pipeline.claude_client import ClaudeError
from pipeline.script import sources_from_text


@pytest.fixture
def cc(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "find_cli", lambda: "claude")
    return claude_code.ClaudeCode({"code_model": "opus", "effort": "high"}, tmp_path / "work")


def test_prompt_flattening_keeps_history_and_latest():
    msgs = [
        {"role": "user", "content": "first ask"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second ask"},
    ]
    p = claude_code._prompt(msgs)
    assert p.index("first ask") < p.index("first answer") < p.index("second ask")
    assert p.rstrip().endswith("second ask")
    assert claude_code._prompt([{"role": "user", "content": "only"}]) == "only"


def test_args_disable_tools_and_settings(cc):
    args, prefix = cc._args("short system", "json", None, "medium", {"type": "object"})
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--effort") + 1] == "medium"
    assert "--json-schema" in args and "--no-session-persistence" in args
    assert args[args.index("--system-prompt") + 1] == "short system"
    assert prefix == ""


def test_args_web_search_and_long_system(cc):
    long_system = [{"type": "text", "text": "x" * 20000, "cache_control": {"type": "ephemeral"}}]
    args, prefix = cc._args(long_system, "stream-json", [{"type": "web_search_20260209", "name": "web_search"}], None)
    assert args[args.index("--tools") + 1] == "WebSearch,WebFetch"
    assert "--include-partial-messages" in args
    assert prefix.startswith("<instructions>") and len(prefix) > 20000


def test_env_strips_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "ANTHROPIC_API_KEY" not in claude_code._env()


def test_usage_limit_message_is_friendly():
    with pytest.raises(ClaudeError, match="usage limit"):
        claude_code.ClaudeCode._raise_for({"is_error": True, "result": "Claude usage limit reached. Resets at 5pm"}, "", 1)


def test_sources_parsed_from_markdown():
    text = "## Sources\n- [History.com: Heists](https://history.com/heists)\n- https://example.org/page."
    found = sources_from_text(text)
    assert found["https://history.com/heists"] == "History.com: Heists"
    assert "https://example.org/page" in found


def test_to_ascii_cleans_typography_and_accents():
    from pipeline.script import clean_script, to_ascii
    s = to_ascii("“It’s gone” — José said… It cost £5 at 40° in København.")
    assert s == '"It\'s gone", Jose said... It cost  pounds 5 at 40 degrees  in Kobenhavn.'.replace("  ", " ")
    assert s.isascii()
    assert to_ascii("He waited - then ran.") == "He waited, then ran."
    assert to_ascii("a well-known man") == "a well-known man"
    text = clean_script("Naïve façade.\n\n\n\nThe end —.")
    assert text == "Naive facade.\n\nThe end." and text.isascii()


def test_usage_is_recorded_only_when_asked(cc):
    result = {"usage": {"input_tokens": 120, "cache_creation_input_tokens": 3000, "cache_read_input_tokens": 9000,
                        "output_tokens": 800, "server_tool_use": {"web_search_requests": 4}},
              "num_turns": 6, "total_cost_usd": 0.42}
    cc._record(result, 12.345)  # off by default: nothing kept
    assert cc.usage_log is None
    cc.usage_log = []
    cc._record(result, 12.345)
    assert cc.usage_log == [{"seconds": 12.35, "input_tokens": 120, "cache_write_tokens": 3000, "cache_read_tokens": 9000,
                             "output_tokens": 800, "web_searches": 4, "turns": 6, "cost_usd": 0.42}]
