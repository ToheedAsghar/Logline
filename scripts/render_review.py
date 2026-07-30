#!/usr/bin/env python3
"""Aggregate local review findings into one ranked list.

Reads   .review/findings-*.json   (one per pass)
Writes  .review/report.md
Prints  a ranked summary to the terminal

Usage:
    python3 scripts/render_review.py                 # all findings
    python3 scripts/render_review.py --important      # only blockers
    python3 scripts/render_review.py --min-confidence 0.85
    python3 scripts/render_review.py --quiet          # write report, print nothing

Exit code is 1 if any `important` finding survived filtering, so this can be
wired into a pre-push hook if you ever want it to be.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REVIEW_DIR = Path(".review")
PROXIMITY = 15  # two passes describing one bug rarely cite the same line
SEVERITY_RANK = {"important": 0, "pre-existing": 1, "nit": 2}
MARKER = {"important": "🔴", "nit": "🟡", "pre-existing": "🟣"}

# ANSI, disabled automatically when piped
C = {
    "red": "\033[31m", "yellow": "\033[33m", "magenta": "\033[35m",
    "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m",
}
COLOR = {"important": "red", "nit": "yellow", "pre-existing": "magenta"}


def paint(text: str, color: str, enabled: bool) -> str:
    return f"{C[color]}{text}{C['reset']}" if enabled else text


def load() -> tuple[list[dict], int, list[str]]:
    findings: list[dict] = []
    suppressed = 0
    problems: list[str] = []

    files = sorted(REVIEW_DIR.glob("findings-*.json"))
    if not files:
        problems.append(
            f"No findings files in {REVIEW_DIR}/. Did the passes run? "
            "Each pass writes .review/findings-<pass>.json"
        )

    for path in files:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            # A pass that emitted prose instead of JSON is a prompt bug worth seeing.
            problems.append(f"{path.name}: could not parse ({exc})")
            continue
        pass_name = data.get("pass") or path.stem.replace("findings-", "")
        suppressed += int(data.get("suppressed") or 0)
        for f in data.get("findings", []):
            f["pass"] = pass_name
            findings.append(f)
    return findings, suppressed, problems


def usable(f: dict, floor: float) -> bool:
    return (
        f.get("severity") in SEVERITY_RANK
        and bool(f.get("path"))
        and bool(f.get("title"))
        and float(f.get("confidence", 1.0)) >= floor
    )


def dedupe(findings: list[dict]) -> list[dict]:
    """Merge findings that sit within PROXIMITY lines of each other in the same
    file. Independent agreement between passes is real evidence, so corroborated
    findings get a small confidence bump and are labelled."""
    by_path: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_path[f["path"]].append(f)

    out: list[dict] = []
    for items in by_path.values():
        items.sort(key=lambda f: int(f.get("line") or 0))
        groups: list[list[dict]] = []
        for f in items:
            line = int(f.get("line") or 0)
            if groups and line - int(groups[-1][-1].get("line") or 0) <= PROXIMITY:
                groups[-1].append(f)
            else:
                groups.append([f])

        for group in groups:
            group.sort(key=lambda f: -float(f.get("confidence", 0)))
            winner = dict(group[0])
            others = sorted({f["pass"] for f in group[1:] if f["pass"] != winner["pass"]})
            if others:
                winner["corroborated_by"] = others
                winner["confidence"] = round(min(1.0, float(winner.get("confidence", 0.8)) + 0.05), 2)
            out.append(winner)

    out.sort(key=lambda f: (SEVERITY_RANK[f["severity"]], -float(f.get("confidence", 0))))
    return out


def tally(findings: list[dict]) -> str:
    counts = defaultdict(int)
    for f in findings:
        counts[f["severity"]] += 1
    parts = [
        f"{counts['important']} important",
        f"{counts['nit']} nit",
        f"{counts['pre-existing']} pre-existing",
    ]
    return " · ".join(parts)


def print_terminal(findings: list[dict], suppressed: int, problems: list[str]) -> None:
    color = sys.stdout.isatty()

    for p in problems:
        print(paint(f"! {p}", "yellow", color), file=sys.stderr)

    if not findings:
        print(paint("No findings.", "bold", color))
        return

    print()
    print(paint(tally(findings), "bold", color))
    print()

    for i, f in enumerate(findings, 1):
        loc = f"{f['path']}:{f.get('line', '?')}"
        head = f"{i}. {MARKER[f['severity']]} {loc}"
        print(f"{paint(head, COLOR[f['severity']], color)} — {f['title']}")
        if f.get("body"):
            print(f"      {f['body']}")
        if f.get("fix"):
            print(f"      {paint('Fix:', 'bold', color)} {f['fix']}")
        meta = [f["pass"]]
        if f.get("corroborated_by"):
            meta.append("also: " + ", ".join(f["corroborated_by"]))
        meta.append(f"conf {f.get('confidence', '?')}")
        print(f"      {paint('[' + ' | '.join(meta) + ']', 'dim', color)}")
        print()

    if suppressed:
        print(paint(f"({suppressed} low-priority items suppressed by the passes)", "dim", color))
    print(paint("Full report: .review/report.md", "dim", color))


def write_report(findings: list[dict], suppressed: int) -> None:
    lines = ["# Local review", "", tally(findings) if findings else "No findings.", ""]

    for group_name, key in (
        ("Fix before committing", "important"),
        ("Worth fixing", "nit"),
        ("Pre-existing, not from this change", "pre-existing"),
    ):
        group = [f for f in findings if f["severity"] == key]
        if not group:
            continue
        lines += [f"## {group_name}", ""]
        for f in group:
            lines.append(f"### `{f['path']}:{f.get('line', '?')}` — {f['title']}")
            lines.append("")
            if f.get("body"):
                lines += [f["body"], ""]
            if f.get("fix"):
                lines += [f"**Fix:** {f['fix']}", ""]
            if f.get("evidence"):
                lines += ["<details><summary>Evidence</summary>", "", f["evidence"], "", "</details>", ""]
            meta = f"`{f['pass']}` pass · confidence {f.get('confidence', '?')}"
            if f.get("corroborated_by"):
                meta += f" · also flagged by {', '.join(f['corroborated_by'])}"
            lines += [f"<sub>{meta}</sub>", ""]

    if suppressed:
        lines.append(f"<sub>{suppressed} low-priority items suppressed.</sub>")

    REVIEW_DIR.mkdir(exist_ok=True)
    (REVIEW_DIR / "report.md").write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-confidence", type=float, default=0.75)
    ap.add_argument("--important", action="store_true", help="only blockers")
    ap.add_argument("--quiet", action="store_true", help="write the report, print nothing")
    ap.add_argument("--json", action="store_true", help="emit merged findings as JSON")
    args = ap.parse_args()

    raw, suppressed, problems = load()
    kept = dedupe([f for f in raw if usable(f, args.min_confidence)])
    suppressed += len(raw) - len(kept)

    if args.important:
        kept = [f for f in kept if f["severity"] == "important"]

    write_report(kept, suppressed)

    if args.json:
        print(json.dumps({"findings": kept, "suppressed": suppressed}, indent=2))
    elif not args.quiet:
        print_terminal(kept, suppressed, problems)

    return 1 if any(f["severity"] == "important" for f in kept) else 0


if __name__ == "__main__":
    raise SystemExit(main())
