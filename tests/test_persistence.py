import json

from critique.checkers.base import Issue, Severity
from critique.persistence import (
    fallback_synthesis,
    issue_from_dict,
    issue_to_dict,
    list_reports,
    load_report,
    save_report,
)


def _issue(message="unsafe shell"):
    return Issue(
        file_path="app.py",
        line=12,
        column=4,
        message=message,
        code="B602",
        severity=Severity.FATAL,
        reasoning="User input reaches a shell command.",
        code_context=["subprocess.run(cmd, shell=True)\n"],
        suggested_fix="Pass argv as a list and keep shell=False.",
    )


def test_issue_round_trip_preserves_shape():
    issue = _issue()

    restored = issue_from_dict(issue_to_dict(issue))

    assert restored == issue


def test_save_list_and_load_report(tmp_path):
    issue = _issue()
    synth = fallback_synthesis([issue])

    saved = save_report(synth, [issue], reports_dir=tmp_path)
    reports = list_reports(reports_dir=tmp_path)

    assert saved["id"].startswith("rev_")
    assert len(reports) == 1
    assert reports[0]["id"] == saved["id"]
    assert reports[0]["synth_output"]["fix_first"] == 0
    assert reports[0]["issues"][0]["message"] == issue.message

    loaded = load_report(saved["id"], reports_dir=tmp_path)
    assert loaded["id"] == saved["id"]


def test_save_report_prunes_oldest_reports(tmp_path):
    for i in range(51):
        path = tmp_path / f"20200101T0000{i:02d}Z_rev_old{i:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "id": f"rev_old{i:02d}",
                    "timestamp": f"20200101T0000{i:02d}Z",
                    "synth_output": {},
                    "issues": [],
                }
            ),
            encoding="utf-8",
        )

    save_report(fallback_synthesis([]), [], reports_dir=tmp_path)

    reports = list_reports(reports_dir=tmp_path)
    assert len(reports) == 50
    assert "rev_old00" not in {report["id"] for report in reports}
