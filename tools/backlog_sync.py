#!/usr/bin/env python3
"""Integration-step backlog checkmarks for merged research sets (#78).

Research PRs never edit backlog.md (#73). After a completed set's PR is merged
to main, an integration change checks its backlog line:

  python3 tools/backlog_sync.py pending
  python3 tools/backlog_sync.py mark <set-id> --item "<text unique to one unchecked line>"

`pending` lists published (schema2) sets no checked line links yet. `mark`
rewrites exactly one unchecked line; which line a set answers is a human/agent
choice, so it is named explicitly instead of guessed from prose.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_ledger import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def pending(root):
    return [{"set_id": s["set_id"], "conclusion": s["conclusion"]}
            for s in ledger(root)["sets"] if s["source"] == "schema2" and not s["backlog_checked"]]


def mark(root, set_id, item):
    root = Path(root)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_[a-z0-9][a-z0-9_-]{0,63}", set_id):
        raise SystemExit("invalid set id")
    pub_path = root / "research" / set_id / "publication.json"
    pub = json.loads(pub_path.read_text()) if pub_path.is_file() else {}
    if pub.get("set_id") != set_id or pub.get("status") != "completed" \
            or pub.get("conclusion") not in ("accept", "defer", "reject"):
        raise SystemExit("set has no completed publication.json")
    path = root / "backlog.md"
    lines = path.read_text().splitlines(keepends=True)
    if any(f"research/{set_id}/" in line for line in lines):
        raise SystemExit("set already linked in backlog.md")
    hits = [i for i, line in enumerate(lines) if line.startswith("- [ ] ") and item in line]
    if len(hits) != 1:
        raise SystemExit(f"--item must match exactly one unchecked line (matched {len(hits)})")
    i = hits[0]
    text = lines[i][len("- [ ] "):].rstrip("\n")
    suffix = f" — [{set_id[:10]} 세트](research/{set_id}/publication.json), 완료·{pub['conclusion']}"
    if (root / "research" / set_id / "research-addendum.md").is_file():
        suffix += f"; [정성 기록](research/{set_id}/research-addendum.md)"
    issue = re.fullmatch(r"https://github\.com/seanjeonn/sh-quant/issues/(\d+)", pub.get("tracking_issue") or "")
    if issue:
        suffix += f", #{issue.group(1)}"
    lines[i] = f"- [x] {text}{suffix}.\n"
    path.write_text("".join(lines))
    return lines[i]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(ROOT))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("pending")
    m = sub.add_parser("mark")
    m.add_argument("set_id")
    m.add_argument("--item", required=True)
    a = p.parse_args(argv)
    if a.command == "pending":
        print(json.dumps(pending(a.root), ensure_ascii=False, indent=1))
    else:
        print(mark(a.root, a.set_id, a.item), end="")


if __name__ == "__main__":
    main()
