from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class User:
    id: int
    name: str
    email: str


class InputError(ValueError):
    pass


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def mean(nums: list[float]) -> float:
    if not nums:
        raise InputError("mean() requires at least one number")
    return sum(nums) / len(nums)


def safe_div(a: float, b: float) -> float:
    if b == 0:
        raise ZeroDivisionError("b must not be 0")
    return a / b


def parse_user(payload: dict[str, Any]) -> User:
    if "id" not in payload or "name" not in payload or "email" not in payload:
        raise InputError("payload must contain id, name, email")
    if not isinstance(payload["id"], int):
        raise InputError("id must be int")
    if "@" not in str(payload["email"]):
        raise InputError("email must contain @")
    return User(id=payload["id"], name=str(payload["name"]), email=str(payload["email"]))


def read_numbers(path: Path) -> list[float]:
    txt = path.read_text(encoding="utf-8")
    out: list[float] = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(float(line))
    return out


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def maybe_env_threshold() -> float:
    raw = os.getenv("THRESHOLD", "0.75")
    try:
        val = float(raw)
    except ValueError as e:
        raise InputError(f"THRESHOLD must be a float, got {raw!r}") from e
    if not (0.0 <= val <= 1.0):
        raise InputError("THRESHOLD must be in [0, 1]")
    return val


def score_numbers(nums: list[float]) -> dict[str, Any]:
    m = mean(nums)
    s = math.sqrt(mean([(x - m) ** 2 for x in nums]))
    threshold = maybe_env_threshold()
    ok = (m / (m + s + 1e-9)) >= threshold
    return {
        "count": len(nums),
        "mean": m,
        "stdev": s,
        "threshold": threshold,
        "ok": ok,
    }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dummy_project", description="Dummy file for CI/lint/testing.")
    p.add_argument("--numbers-file", type=Path, default=None, help="Path to a file of numbers, one per line.")
    p.add_argument("--user-json", type=str, default=None, help="User payload as JSON string.")
    p.add_argument("--out", type=Path, default=Path("out/report.json"), help="Output report path.")
    return p


def main(argv: list[str]) -> int:
    args = build_argparser().parse_args(argv)

    report: dict[str, Any] = {"status": "ok", "errors": []}

    if args.user_json is not None:
        try:
            payload = json.loads(args.user_json)
            user = parse_user(payload)
            report["user"] = {"id": user.id, "name": user.name, "email": user.email}
        except Exception as e:
            report["status"] = "fail"
            report["errors"].append({"stage": "user", "error": str(e)})

    nums: list[float] = []
    if args.numbers_file is not None:
        try:
            nums = read_numbers(args.numbers_file)
            report["numbers"] = score_numbers(nums)
        except Exception as e:
            report["status"] = "fail"
            report["errors"].append({"stage": "numbers", "error": str(e)})

    report["slug_example"] = slugify("  Hello, World!  ")

    try:
        report["division_example"] = safe_div(10.0, 2.0)
    except Exception as e:
        report["status"] = "fail"
        report["errors"].append({"stage": "division", "error": str(e)})

    write_report(args.out, report)

    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
