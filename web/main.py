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
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
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

from critique.checkers.lint import RuffChecker  # noqa: E402
from critique.checkers.security import BanditChecker  # noqa: E402
from critique.checkers.types import MypyChecker  # noqa: E402
from critique.checkers.base import Issue, Severity  # noqa: E402
from critique.persistence import fallback_synthesis  # noqa: E402

# ── FastAPI app ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/day"])
app = FastAPI(title="CodeCritique", description="AI-powered code review demo")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Models ──────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    code: str
    filename: str = "main.py"
    language: str = "python"


class GitHubFileRequest(BaseModel):
    url: str


# ── Helpers ─────────────────────────────────────────────────────────────────
MAX_REMOTE_BYTES = 200_000
REPO_URL = "https://github.com/adesai-24/CodeCritique"


def _github_raw_url(url: str) -> tuple[str, str]:
    """Return a raw download URL and filename for a supported GitHub file URL."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise ValueError("Use an https:// GitHub URL.")

    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host == "raw.githubusercontent.com" and len(path_parts) >= 4:
        return url, path_parts[-1]

    if host == "gist.githubusercontent.com" and "/raw/" in parsed.path:
        return url, path_parts[-1] if path_parts else "gist.py"

    if host == "github.com" and len(path_parts) >= 5 and path_parts[2] == "blob":
        owner, repo, _, branch = path_parts[:4]
        file_path = "/".join(path_parts[4:])
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
        return raw_url, path_parts[-1]

    raise ValueError("Paste a GitHub file URL, raw GitHub URL, or raw Gist URL.")


def fetch_github_file(url: str) -> dict:
    raw_url, filename = _github_raw_url(url)
    response = requests.get(raw_url, timeout=15)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if content_type and "text" not in content_type and "json" not in content_type:
        raise ValueError("That URL did not return a text file.")

    if len(response.content) > MAX_REMOTE_BYTES:
        raise ValueError("That file is too large for the demo. Keep it under 200 KB.")

    code = response.content.decode(response.encoding or "utf-8", errors="replace")
    return {
        "code": code,
        "filename": filename or "main.py",
        "language": "python",
        "source_url": raw_url,
    }


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
            model="claude-opus-4-7",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ),
    )
    block = response.content[0]
    if not hasattr(block, "text"):
        raise ValueError(f"Unexpected response block type: {type(block).__name__}")
    raw = block.text.strip()
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


@app.post("/api/github-file")
@limiter.limit("20/hour")
async def github_file(request: Request, body: GitHubFileRequest):
    """Fetch a single GitHub-hosted source file for the paste-mode reviewer."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fetch_github_file, body.url)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=status_code, detail="GitHub file could not be fetched.") from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="GitHub request failed.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

            async def run_checker(idx, name, checker):
                events = [
                    {"event": "status", "data": json.dumps({"message": f"Running {name}…"})}
                ]
                patched = []
                try:
                    loop = asyncio.get_event_loop()
                    raw = await loop.run_in_executor(None, checker.run, [tmp_path])
                    patched = [
                        iss._replace(file_path=body.filename) for iss in raw
                    ]
                    events.append({
                        "event": "checker_done",
                        "data": json.dumps({"checker": name, "count": len(raw)}),
                    })
                except Exception as exc:
                    events.append({
                        "event": "checker_error",
                        "data": json.dumps({"checker": name, "error": str(exc)}),
                    })
                return idx, patched, events

            checker_tasks = [
                asyncio.create_task(run_checker(idx, name, checker))
                for idx, (name, checker) in enumerate(checkers)
            ]
            checker_results = [[] for _ in checkers]
            for task in asyncio.as_completed(checker_tasks):
                idx, patched, events = await task
                checker_results[idx] = patched
                for event in events:
                    yield event
                await asyncio.sleep(0)

            for checker_issues in checker_results:
                all_issues.extend(checker_issues)

            # ── AI synthesis ─────────────────────────────────────────────
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            synthesis = None
            ai_used = False

            if not all_issues:
                synthesis = fallback_synthesis(all_issues)
                yield {"event": "synthesis", "data": json.dumps(synthesis)}
            elif anthropic_key:
                yield {"event": "status", "data": json.dumps({"message": "Running AI synthesis (Anthropic)…"})}
                await asyncio.sleep(0)
                try:
                    synthesis = await _anthropic_synthesis(all_issues, body.code, anthropic_key)
                    ai_used = True
                    yield {"event": "synthesis", "data": json.dumps(synthesis)}
                except Exception as exc:
                    yield {"event": "ai_error", "data": json.dumps({"error": str(exc)})}
            else:
                yield {"event": "status", "data": json.dumps({"message": "Checking for local AI (Ollama)…"})}
                await asyncio.sleep(0)
                loop = asyncio.get_event_loop()
                synthesis = await loop.run_in_executor(None, _ollama_synthesis, all_issues)
                if synthesis:
                    ai_used = True
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
                    "has_ai": ai_used,
                }),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return EventSourceResponse(generate())
