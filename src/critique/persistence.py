import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from critique.checkers.base import Issue, Severity

REPORTS_DIR = Path.home() / ".codecritique" / "reports"
MAX_REPORTS = 50


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _new_report_id() -> str:
    return f"rev_{secrets.token_hex(3)}"


def issue_to_dict(issue: Issue) -> Dict[str, Any]:
    return {
        "file_path": issue.file_path,
        "line": issue.line,
        "column": issue.column,
        "message": issue.message,
        "code": issue.code,
        "severity": issue.severity.value,
        "reasoning": issue.reasoning,
        "code_context": issue.code_context,
        "suggested_fix": issue.suggested_fix,
    }


def issue_from_dict(data: Dict[str, Any]) -> Issue:
    severity = data.get("severity", Severity.INFO.value)
    try:
        parsed_severity = Severity(severity)
    except ValueError:
        parsed_severity = Severity.INFO

    return Issue(
        file_path=data.get("file_path", ""),
        line=int(data.get("line", 0) or 0),
        column=int(data.get("column", 0) or 0),
        message=data.get("message", ""),
        code=data.get("code", ""),
        severity=parsed_severity,
        reasoning=data.get("reasoning"),
        code_context=data.get("code_context"),
        suggested_fix=data.get("suggested_fix"),
    )


def fallback_synthesis(issues: List[Issue]) -> Dict[str, Any]:
    if not issues:
        return {
            "summary": "No issues found. The code looks clean.",
            "fix_first": -1,
            "critical": [],
            "warnings": [],
            "suggestions": [],
            "whats_good": ["All automated checks passed."],
        }

    return {
        "summary": f"Found {len(issues)} issue(s). Review the prioritized findings.",
        "fix_first": next(
            (i for i, issue in enumerate(issues) if issue.severity == Severity.FATAL),
            0,
        ),
        "critical": [
            i for i, issue in enumerate(issues) if issue.severity == Severity.FATAL
        ],
        "warnings": [
            i for i, issue in enumerate(issues) if issue.severity == Severity.WARNING
        ],
        "suggestions": [
            i for i, issue in enumerate(issues) if issue.severity == Severity.INFO
        ],
        "whats_good": [],
    }


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def save_report(
    synth_output: Dict[str, Any],
    issues: List[Issue],
    reports_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    reports_dir = reports_dir or REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = _new_report_id()
    timestamp = _now_stamp()
    payload = {
        "id": report_id,
        "timestamp": timestamp,
        "synth_output": synth_output,
        "issues": [issue_to_dict(issue) for issue in issues],
    }

    path = reports_dir / f"{timestamp}_{report_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    prune_reports(reports_dir=reports_dir)
    payload["path"] = str(path)
    return payload


def list_reports(reports_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    reports_dir = reports_dir or REPORTS_DIR
    if not reports_dir.exists():
        return []

    reports: List[Dict[str, Any]] = []
    for path in reports_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["path"] = str(path)
        reports.append(data)

    return sorted(
        reports,
        key=lambda item: str(item.get("timestamp", "")),
        reverse=True,
    )


def prune_reports(
    limit: int = MAX_REPORTS,
    reports_dir: Optional[Path] = None,
) -> None:
    reports_dir = reports_dir or REPORTS_DIR
    reports = list_reports(reports_dir=reports_dir)
    for report in reports[limit:]:
        path = report.get("path")
        if path:
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass


def load_report(
    report_id: Optional[str] = None,
    reports_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    reports = list_reports(reports_dir=reports_dir)
    if not reports:
        raise FileNotFoundError("No saved CodeCritique reports found.")

    if report_id is None:
        return reports[0]

    for report in reports:
        if report.get("id") == report_id:
            return report

    raise FileNotFoundError(f"No saved CodeCritique report found for id {report_id!r}.")
