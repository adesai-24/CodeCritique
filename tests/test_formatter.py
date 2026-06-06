"""Tests for the agentic code formatter (LLM call is mocked)."""

from unittest.mock import MagicMock

from critique.formatter import (
    CodeFormatter,
    _match_trailing_newline,
    _strip_code_fences,
)
from critique.languages import CPP, PYTHON


class TestHelpers:
    def test_strip_fenced_response(self):
        text = "```cpp\nint main() { return 0; }\n```"
        assert _strip_code_fences(text) == "int main() { return 0; }"

    def test_strip_leaves_unfenced_text(self):
        text = "int main() { return 0; }"
        assert _strip_code_fences(text) == text

    def test_match_trailing_newline_adds_when_original_had_one(self):
        assert _match_trailing_newline("a\n", "b") == "b\n"

    def test_match_trailing_newline_removes_when_original_had_none(self):
        assert _match_trailing_newline("a", "b\n") == "b"


class TestFormatSource:
    def test_builds_language_aware_prompt(self):
        llm = MagicMock()
        llm.complete.return_value = "formatted"
        CodeFormatter(llm).format_source("x=1", PYTHON)
        user = llm.complete.call_args[0][1]
        assert "Python" in user
        assert "```python" in user

    def test_cpp_prompt_uses_cpp_fence(self):
        llm = MagicMock()
        llm.complete.return_value = "formatted"
        CodeFormatter(llm).format_source("int x;", CPP)
        user = llm.complete.call_args[0][1]
        assert "C/C++" in user
        assert "```cpp" in user

    def test_strips_fences_from_model_output(self):
        llm = MagicMock()
        llm.complete.return_value = "```python\nx = 1\n```"
        out = CodeFormatter(llm).format_source("x=1\n", PYTHON)
        assert out == "x = 1\n"


class TestFormatFile:
    def test_unsupported_file_reports_error(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello", encoding="utf-8")
        result = CodeFormatter(MagicMock()).format_file(str(f))
        assert not result.ok
        assert "unsupported" in result.error

    def test_detects_change(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x=1\n", encoding="utf-8")
        llm = MagicMock()
        llm.complete.return_value = "x = 1\n"
        result = CodeFormatter(llm).format_file(str(f))
        assert result.ok
        assert result.changed
        assert result.formatted == "x = 1\n"
        # Pure function: it must not modify the file on disk itself.
        assert f.read_text(encoding="utf-8") == "x=1\n"

    def test_no_change_when_already_formatted(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("x = 1\n", encoding="utf-8")
        llm = MagicMock()
        llm.complete.return_value = "x = 1\n"
        result = CodeFormatter(llm).format_file(str(f))
        assert result.ok
        assert not result.changed

    def test_large_file_skipped(self, tmp_path):
        from critique import formatter as fmt
        f = tmp_path / "big.py"
        f.write_text("x = 1\n" * (fmt.MAX_FORMAT_CHARS // 6 + 100), encoding="utf-8")
        result = CodeFormatter(MagicMock()).format_file(str(f))
        assert not result.ok
        assert "too large" in result.error

    def test_empty_file_is_noop(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("", encoding="utf-8")
        llm = MagicMock()
        result = CodeFormatter(llm).format_file(str(f))
        assert result.ok
        assert not result.changed
        llm.complete.assert_not_called()
