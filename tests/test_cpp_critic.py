"""Tests for C/C++ support in the AI critic: chunking + end-to-end review."""

from unittest.mock import MagicMock

from critique.checkers.ai_critic import (
    AICriticChecker,
    _extract_cpp_chunks,
    _find_cpp_blocks,
)


SAMPLE = """\
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

int main(void) {
    return add(1, 2);
}
"""


class TestCppChunking:
    def test_finds_top_level_blocks(self):
        blocks = _find_cpp_blocks(SAMPLE)
        # add() and main() are the two top-level brace blocks.
        assert len(blocks) == 2

    def test_extracts_function_chunks_with_line_offsets(self):
        chunks = _extract_cpp_chunks(SAMPLE, "sample.cpp")
        offsets = [offset for _, offset in chunks]
        # Preamble (the #include) plus two functions, sorted by line.
        assert offsets == sorted(offsets)
        joined = "\n".join(text for text, _ in chunks)
        assert "int add(int a, int b)" in joined
        assert "int main(void)" in joined

    def test_function_chunk_starts_at_signature(self):
        chunks = _extract_cpp_chunks(SAMPLE, "sample.cpp")
        add_chunk = next(t for t, _ in chunks if "int add" in t)
        assert add_chunk.lstrip().startswith("int add(int a, int b)")

    def test_braces_in_strings_and_comments_are_ignored(self):
        src = (
            'const char *s = "this { has } braces";\n'
            "// a comment with { unmatched brace\n"
            "int f(void) {\n"
            "    return 0;\n"
            "}\n"
        )
        blocks = _find_cpp_blocks(src)
        assert len(blocks) == 1  # only f()

    def test_no_blocks_falls_back_to_whole_file(self):
        src = "int x = 1;\nint y = 2;\n"
        chunks = _extract_cpp_chunks(src, "globals.c")
        assert len(chunks) == 1
        assert chunks[0] == (src, 1)


class TestAICriticCpp:
    def test_reviews_cpp_file(self, tmp_path):
        f = tmp_path / "prog.cpp"
        f.write_text(SAMPLE, encoding="utf-8")

        llm = MagicMock()
        llm.supports_prefix_cache = False
        llm.complete_json.return_value = {
            "findings": [
                {"line": 1, "title": "C finding", "severity": "WARNING", "explanation": "x"}
            ]
        }

        issues = AICriticChecker(llm).run([str(f)])

        assert issues, "expected at least one finding for the C++ file"
        assert all(i.code == "AI" for i in issues)
        # The prompt must describe the snippet as C/C++ and fence it accordingly.
        sent_user = llm.complete_json.call_args_list[0].kwargs["user"]
        assert "C/C++" in sent_user
        assert "```cpp" in sent_user

    def test_header_files_are_reviewed(self, tmp_path):
        f = tmp_path / "lib.h"
        f.write_text("int square(int n) {\n    return n * n;\n}\n", encoding="utf-8")
        llm = MagicMock()
        llm.supports_prefix_cache = False
        llm.complete_json.return_value = {"findings": []}

        AICriticChecker(llm).run([str(f)])

        assert llm.complete_json.called
