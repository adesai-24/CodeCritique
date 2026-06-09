"""
AICriticChecker — semantic code review via local LLM.

Optimizations
-------------
1. AST-based cache key: we hash ast.dump() rather than raw source text, so
   changes that only affect comments or whitespace don't invalidate cached
   results.  The actual request still sends the original source so the model
   sees docstrings and inline context.  A SyntaxError falls back to hashing
   the raw text.

2. Function/class chunking: instead of sending an entire file as one prompt,
   we extract top-level functions and classes and review each independently.
   This keeps prompts small (faster inference, fewer tokens), improves cache
   granularity (editing one function doesn't invalidate results for others),
   and serialises within a file so Ollama's prefix KV-cache stays hot across
   consecutive chunks that share the same CRITIC_SYSTEM prefix.

3. Files with no top-level definitions fall back to whole-file review (e.g.
   scripts, __init__.py with only imports).
"""

import ast
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from typing import List, Optional, Tuple

from critique.checkers.base import BaseChecker, Issue, Severity
from critique.ai.client import LLMClient
from critique.ai.prompts import CRITIC_SYSTEM
from critique.ai.schemas import CRITIC_SCHEMA
from critique.languages import CPP, PYTHON, Language, detect_language, is_supported

MAX_FILE_CHARS = 30_000
MAX_CHUNK_CHARS = 8_000   # keep individual chunks well within context window
_DEFAULT_AI_CRITIC_WORKERS = 2
# Concurrency for reviewing chunks *within* a file. Only used for stateless
# backends (cloud/vLLM); Ollama reviews chunks serially to keep its prefix KV
# cache hot across consecutive same-system-prompt requests.
_DEFAULT_AI_CHUNK_WORKERS = 4


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _ast_cache_key(chunk: str, system: str) -> Optional[str]:
    """Derive a cache key from the AST structure of a code chunk.

    Two chunks that differ only in comments or whitespace produce the same
    key, so the LLM result is reused without a new inference call.  Returns
    None on SyntaxError so the caller falls back to the default payload hash.

    We include a short hash of the system prompt so that cache entries from
    different prompt versions don't collide.
    """
    try:
        tree = ast.parse(chunk)
        ast_digest = sha256(ast.dump(tree).encode("utf-8")).hexdigest()
        sys_prefix = sha256(system.encode("utf-8")).hexdigest()[:8]
        return f"ast:{sys_prefix}:{ast_digest}"
    except SyntaxError:
        return None


def _extract_chunks(
    source: str, file_path: str, language: Language = PYTHON
) -> List[Tuple[str, int]]:
    """Dispatch to the right per-language chunker.

    Each language has its own notion of a "reviewable unit" (a Python def/class
    vs. a C/C++ brace-balanced block), so chunking is delegated.  Anything we
    can't chunk falls back to whole-file review.
    """
    if language.key == CPP.key:
        return _extract_cpp_chunks(source, file_path)
    return _extract_python_chunks(source, file_path)


def _extract_python_chunks(source: str, file_path: str) -> List[Tuple[str, int]]:
    """
    Split a Python source file into reviewable chunks.

    Returns a list of (chunk_source, base_line_offset) tuples where
    base_line_offset is the 1-based line number of the chunk's first line
    within the original file.

    Strategy:
    - Parse the AST; collect top-level FunctionDef / AsyncFunctionDef / ClassDef.
    - Each definition becomes its own chunk (capped at MAX_CHUNK_CHARS).
    - Everything else (module-level statements, imports) is collected into a
      "module-level" chunk.
    - If parsing fails or there are no definitions, the whole file is one chunk.
    """
    try:
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
    except SyntaxError:
        return [(source, 1)]

    # Collect top-level definitions with their line ranges.
    def_nodes = [
        node for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    if not def_nodes:
        return [(source, 1)]

    chunks: List[Tuple[str, int]] = []

    # Build a set of lines covered by top-level definitions.
    covered: set = set()
    for node in def_nodes:
        start = node.lineno - 1   # 0-based
        end = getattr(node, "end_lineno", node.lineno)  # 1-based, inclusive
        covered.update(range(start, end))

    # Module-level lines (not inside any top-level def/class).
    module_lines = [i for i in range(len(lines)) if i not in covered]
    if module_lines:
        module_text = "".join(lines[i] for i in module_lines)
        if module_text.strip():
            chunks.append((module_text, module_lines[0] + 1))

    # One chunk per top-level definition.
    for node in def_nodes:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        chunk_text = "".join(lines[start:end])
        if len(chunk_text) > MAX_CHUNK_CHARS:
            chunk_text = chunk_text[:MAX_CHUNK_CHARS]
        if chunk_text.strip():
            chunks.append((chunk_text, node.lineno))

    return chunks if chunks else [(source, 1)]


def _find_cpp_blocks(source: str) -> List[Tuple[int, int]]:
    """Locate top-level brace-balanced blocks in C/C++ source.

    Returns a list of ``(start_idx, end_idx)`` character ranges (end inclusive)
    for each construct that opens a brace at depth 0 — functions, classes,
    structs, namespaces, etc.  The scan is a small state machine that ignores
    braces inside comments, string/char literals, and preprocessor directives so
    they don't throw off the depth count.

    We don't need a full C parser here: chunking is an optimisation, and any
    construct we miss simply falls back to whole-file review.
    """
    n = len(source)
    blocks: List[Tuple[int, int]] = []
    i = 0
    depth = 0
    construct_start = 0
    block_open = 0
    in_line_comment = in_block_comment = in_string = in_char = in_preproc = False
    escape = False

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_preproc:
            # Preprocessor directives run to end-of-line, with backslash-newline
            # continuation. They never contribute braces to the depth count.
            if c == "\\" and nxt == "\n":
                i += 2
                continue
            if c == "\n":
                in_preproc = False
                if depth == 0:
                    construct_start = i + 1
            i += 1
            continue
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if in_char:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == "'":
                in_char = False
            i += 1
            continue

        # Not inside any comment / literal below this point.
        if c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if c == "#" and depth == 0:
            in_preproc = True
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "'":
            in_char = True
            i += 1
            continue
        if c == "{":
            if depth == 0:
                block_open = construct_start
            depth += 1
            i += 1
            continue
        if c == "}":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    blocks.append((block_open, i))
                    construct_start = i + 1
            i += 1
            continue
        if c == ";" and depth == 0:
            construct_start = i + 1
            i += 1
            continue
        # While scanning preamble at depth 0, keep construct_start pinned to the
        # first non-whitespace character so a block's chunk starts at its
        # signature rather than the blank lines above it.
        if depth == 0 and i == construct_start and c in " \t\r\n":
            construct_start = i + 1
        i += 1

    return blocks


def _extract_cpp_chunks(source: str, file_path: str) -> List[Tuple[str, int]]:
    """Split C/C++ source into reviewable chunks.

    One chunk per top-level brace block (function/struct/class/namespace), plus
    a single "preamble" chunk for everything outside those blocks (includes,
    macros, prototypes, globals).  Mirrors the Python chunker's shape so the
    reporting/cache machinery treats both languages identically.  Falls back to
    whole-file review when no blocks are detected.
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return [(source, 1)]

    # Precompute the starting character offset of each line for idx -> line.
    line_starts: List[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line)

    def line_of(idx: int) -> int:
        # Largest line index whose start offset is <= idx (0-based line).
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= idx:
                lo = mid
            else:
                hi = mid - 1
        return lo

    blocks = _find_cpp_blocks(source)
    if not blocks:
        return [(source, 1)]

    chunks: List[Tuple[str, int]] = []
    covered: set = set()

    for start_idx, end_idx in blocks:
        start_line = line_of(start_idx)
        end_line = line_of(end_idx)
        covered.update(range(start_line, end_line + 1))
        chunk_text = "".join(lines[start_line:end_line + 1])
        if len(chunk_text) > MAX_CHUNK_CHARS:
            chunk_text = chunk_text[:MAX_CHUNK_CHARS]
        if chunk_text.strip():
            chunks.append((chunk_text, start_line + 1))

    # Everything not inside a top-level block becomes one preamble chunk.
    preamble_lines = [i for i in range(len(lines)) if i not in covered]
    if preamble_lines:
        preamble_text = "".join(lines[i] for i in preamble_lines)
        if preamble_text.strip():
            chunks.append((preamble_text, preamble_lines[0] + 1))

    # Keep chunks in source order so reported findings read top-to-bottom.
    chunks.sort(key=lambda c: c[1])
    return chunks if chunks else [(source, 1)]


class AICriticChecker(BaseChecker):
    """
    Semantic code review checker backed by a local LLM.

    Slots into the existing checker pipeline as a peer of Ruff/Bandit/Mypy.
    Catches logic bugs, off-by-one errors, incorrect comparisons, and other
    correctness issues that require understanding intent rather than syntax.

    Safety properties:
      - Skips files larger than MAX_FILE_CHARS to stay within context budget.
      - Wraps each file/chunk in try/except so one failure never aborts the run.
      - Maps findings → Issue with code="AI" so the report can distinguish
        AI findings from static-tool findings.
    """

    name = "AI Critic"
    description = "Semantic review via local LLM — catches logic bugs linters miss"

    def __init__(self, llm: LLMClient, profile=None, project_context=None, custom_instructions=None):
        self.llm = llm
        self.profile = profile
        # Bake the active review mode + project context into the system prompt
        # once. Because this string feeds the AST cache key, different modes
        # cache independently and switching modes never serves a stale review.
        if profile is not None:
            from critique.profiles import apply_profile_to_system
            self._system = apply_profile_to_system(
                CRITIC_SYSTEM, profile, project_context, custom_instructions
            )
        else:
            self._system = CRITIC_SYSTEM

    def _review_chunk(
        self, chunk: str, line_offset: int, file_path: str, language: Language = PYTHON
    ) -> List[Issue]:
        """Review a single chunk (function/class/module block) and return issues."""
        try:
            result = self.llm.complete_json(
                system=self._system,
                user=(
                    f"Review this {language.name} code (from {file_path}, starting at "
                    f"line {line_offset}) for logic bugs and correctness issues:\n\n"
                    f"```{language.fence}\n{chunk}\n```"
                ),
                schema=CRITIC_SCHEMA,
                cache_key_override=_ast_cache_key(chunk, self._system),
            )
            issues: List[Issue] = []
            for finding in result.get("findings", []):
                try:
                    severity = Severity[finding.get("severity", "WARNING")]
                except KeyError:
                    severity = Severity.WARNING

                # Line numbers in the response are relative to the chunk;
                # translate them back to file-absolute lines.
                relative_line = finding.get("line", 1)
                absolute_line = line_offset + relative_line - 1

                issues.append(
                    Issue(
                        file_path=file_path,
                        line=absolute_line,
                        column=0,
                        message=finding.get("title", "AI finding"),
                        code="AI",
                        severity=severity,
                        reasoning=finding.get("explanation"),
                    )
                )
            return issues
        except Exception:
            return []

    def _review_file(self, file_path: str) -> List[Issue]:
        language = detect_language(file_path)
        if language is None:
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return []

        if len(source) > MAX_FILE_CHARS:
            return []

        chunks = _extract_chunks(source, file_path, language)

        # Stateless backends (cloud/vLLM) gain nothing from serial review and a
        # lot from concurrency, so fan the chunks out. Ollama stays serial to
        # keep its shared-prefix KV cache warm between consecutive chunks.
        prefix_cache = getattr(self.llm, "supports_prefix_cache", False)
        if len(chunks) > 1 and not prefix_cache:
            return self._review_chunks_concurrent(chunks, file_path, language)

        all_issues: List[Issue] = []
        for chunk_text, line_offset in chunks:
            all_issues.extend(
                self._review_chunk(chunk_text, line_offset, file_path, language)
            )
        return all_issues

    def _review_chunks_concurrent(
        self, chunks: List[Tuple[str, int]], file_path: str, language: Language = PYTHON
    ) -> List[Issue]:
        workers = max(
            1,
            min(len(chunks), _env_int("CODECRITIQUE_AI_CHUNK_WORKERS", _DEFAULT_AI_CHUNK_WORKERS)),
        )
        results: List[List[Issue]] = [[] for _ in chunks]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(self._review_chunk, text, offset, file_path, language): i
                for i, (text, offset) in enumerate(chunks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = []
        all_issues: List[Issue] = []
        for chunk_issues in results:
            all_issues.extend(chunk_issues)
        return all_issues

    def run(self, files: List[str]) -> List[Issue]:
        source_files = [f for f in files if is_supported(f)]
        if not source_files:
            return []

        max_workers = max(
            1,
            min(
                len(source_files),
                _env_int("CODECRITIQUE_AI_CRITIC_WORKERS", _DEFAULT_AI_CRITIC_WORKERS),
            ),
        )
        results: List[List[Issue]] = [[] for _ in source_files]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self._review_file, file_path): i
                for i, file_path in enumerate(source_files)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = []

        issues: List[Issue] = []
        for file_issues in results:
            issues.extend(file_issues)
        return issues
