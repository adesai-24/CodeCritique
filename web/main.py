"""
CodeCritique Web — Phase 9
FastAPI backend serving the web demo. Accepts pasted code,
runs static analyzers + optional AI, streams results via SSE.
"""

import json
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ── path bootstrap ──────────────────────────────────────────────────────────
_repo_src = str(Path(__file__).parent.parent / "src")
if _repo_src not in sys.path:
    sys.path.insert(0, _repo_src)

# Ensure venv tool binaries (ruff, bandit, mypy) are on PATH
_scripts = os.path.join(sys.prefix, "Scripts" if os.name == "nt" else "bin")
if _scripts not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _scripts + os.pathsep + os.environ.get("PATH", "")

from critique.checkers.lint import RuffChecker
from critique.checkers.security import BanditChecker
from critique.checkers.types import MypyChecker
from critique.checkers.base import Issue, Severity

# ── FastAPI app ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/day"])
app = FastAPI(title="CodeCritique", description="AI-powered code review demo")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Models ──────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    code: str
    filename: str = "main.py"
    language: str = "python"


# ── Helpers ─────────────────────────────────────────────────────────────────
def _issue_to_dict(issue: Issue, source_lines: list[str]) -> dict:
    start = max(0, issue.line - 4)
    end = min(len(source_lines), issue.line + 3)
    ctx = source_lines[start:end]

    try:
        filename = Path(issue.file_path).name
    except Exception:
        filename = issue.file_path

    return {
        "severity": issue.severity.value,
        "message": issue.message,
        "code": issue.code,
        "line": issue.line,
        "column": issue.column or 0,
        "file": filename,
        "reasoning": issue.reasoning,
        "suggested_fix": issue.suggested_fix,
        "code_context": ctx,
        "context_start_line": start + 1,
    }


async def _anthropic_synthesis(issues: list[Issue], code: str, api_key: str) -> dict:
    """Call Anthropic Claude for an AI synthesis of findings."""
    import anthropic as _anthropic

    client = _anthropic.Anthropic(api_key=api_key)
    numbered = "\n".join(
        f"{i}. [{iss.severity.value}] Line {iss.line}: {iss.message} ({iss.code})"
        for i, iss in enumerate(issues)
    )
    prompt = (
        "You are a senior software engineer reviewing code.\n\n"
        f"Automated findings ({len(issues)} total):\n{numbered or 'None'}\n\n"
        f"Code snippet:\n```python\n{code[:3000]}\n```\n\n"
        "Return a JSON object with exactly these keys:\n"
        '  "summary": string (2-3 sentence overall assessment)\n'
        '  "fix_first": number (0-based index of the most critical issue; -1 if none)\n'
        '  "critical": array of 0-based indices (FATAL issues)\n'
        '  "warnings": array of 0-based indices (WARNING issues)\n'
        '  "suggestions": array of 0-based indices (INFO/style issues)\n'
        '  "whats_good": array of strings (positive observations)\n\n'
        "Return only the JSON, no markdown fences."
    )

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ),
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _ollama_synthesis(issues: list[Issue]) -> Optional[dict]:
    """Try to synthesize using local Ollama. Returns None if unavailable."""
    try:
        from critique.ai.client import LLMClient
        from critique.ai.synthesizer import AISynthesizer
        llm = LLMClient()
        if not llm.is_available():
            return None
        return AISynthesizer(llm).synthesize(issues)
    except Exception:
        return None


# ── Routes ──────────────────────────────────────────────────────────────────
@app.get("/")
async def serve_index():
    return FileResponse(str(_static / "index.html"))


@app.get("/api/health")
async def health():
    ollama_ok = False
    try:
        from critique.ai.client import LLMClient
        ollama_ok = LLMClient().is_available()
    except Exception:
        pass
    return {
        "status": "ok",
        "ai": {
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
            "ollama": ollama_ok,
        },
    }


@app.post("/api/review")
@limiter.limit("10/hour")
async def review_code(request: Request, body: ReviewRequest):
    """Stream code review results as Server-Sent Events."""

    async def generate():
        source_lines = body.code.splitlines(keepends=True)

        # ── Write code to a temp file ────────────────────────────────────
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="codecritique_",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(body.code)
            tmp_path = tmp.name

        try:
            yield {"event": "status", "data": json.dumps({"message": "Starting analysis…"})}
            await asyncio.sleep(0)

            all_issues: list[Issue] = []

            # ── Static checkers ──────────────────────────────────────────
            checkers = [
                ("Lint (Ruff)", RuffChecker()),
                ("Security (Bandit)", BanditChecker()),
                ("Types (Mypy)", MypyChecker()),
            ]

            for name, checker in checkers:
                yield {"event": "status", "data": json.dumps({"message": f"Running {name}…"})}
                await asyncio.sleep(0)
                try:
                    loop = asyncio.get_event_loop()
                    raw = await loop.run_in_executor(None, checker.run, [tmp_path])
                    patched = [
                        iss._replace(file_path=body.filename) for iss in raw
                    ]
                    all_issues.extend(patched)
                    yield {
                        "event": "checker_done",
                        "data": json.dumps({"checker": name, "count": len(raw)}),
                    }
                except Exception as exc:
                    yield {
                        "event": "checker_error",
                        "data": json.dumps({"checker": name, "error": str(exc)}),
                    }
                await asyncio.sleep(0)

            # ── AI synthesis ─────────────────────────────────────────────
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            synthesis = None

            if anthropic_key:
                yield {"event": "status", "data": json.dumps({"message": "Running AI synthesis (Anthropic)…"})}
                await asyncio.sleep(0)
                try:
                    synthesis = await _anthropic_synthesis(all_issues, body.code, anthropic_key)
                    yield {"event": "synthesis", "data": json.dumps(synthesis)}
                except Exception as exc:
                    yield {"event": "ai_error", "data": json.dumps({"error": str(exc)})}
            else:
                yield {"event": "status", "data": json.dumps({"message": "Checking for local AI (Ollama)…"})}
                await asyncio.sleep(0)
                loop = asyncio.get_event_loop()
                synthesis = await loop.run_in_executor(None, _ollama_synthesis, all_issues)
                if synthesis:
                    yield {"event": "synthesis", "data": json.dumps(synthesis)}
                else:
                    yield {"event": "status", "data": json.dumps({"message": "No AI available — static analysis only"})}

            # ── Send issues list ─────────────────────────────────────────
            issues_data = [_issue_to_dict(i, source_lines) for i in all_issues]
            yield {"event": "issues", "data": json.dumps(issues_data)}

            # ── Final summary ────────────────────────────────────────────
            fatal = sum(1 for i in all_issues if i.severity == Severity.FATAL)
            warnings = sum(1 for i in all_issues if i.severity == Severity.WARNING)
            info = sum(1 for i in all_issues if i.severity == Severity.INFO)
            yield {
                "event": "complete",
                "data": json.dumps({
                    "total": len(all_issues),
                    "fatal": fatal,
                    "warnings": warnings,
                    "info": info,
                    "passed": fatal == 0,
                    "has_ai": synthesis is not None,
                }),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return EventSourceResponse(generate())
