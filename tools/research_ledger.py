#!/usr/bin/env python3
"""Read-only cross-set research ledger (#72).

Aggregates public, qualitative metadata of research/*/ sets into deterministic
JSON on stdout. Never emits numeric performance (#28): only counts, labels and
candidate ids. Anything not derivable from committed files is "unknown"/null.

Sources per set (read-only):
- schema2 sets: publication.json (conclusion, attempt_count) and the IS ranking
  sentence of research-addendum.md (candidate ids + preregistered parameters);
  plan.json/selection.json there are hash-only descriptors.
- legacy sets (no publication.json): status.json, selection.json, attempts.jsonl.
- backlog.md: whether a checked `- [x]` line links the set.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ponytail: keyword map on set_id tokens; extend when a new family appears.
FAMILIES = (
    ("ema", "trend"), ("sma", "trend"), ("macd", "trend"), ("donchian", "trend"),
    ("rsi", "mean_reversion"), ("bollinger", "mean_reversion"),
    ("momentum", "momentum"),
)
RANKING = re.compile(
    r"(?:ordering|ranking) was ((?:(?:, )?(?:then )?(?:baseline|v\d{3}) \([^)]*\))+)")
CANDIDATE = re.compile(r"(baseline|v\d{3}) \(([^)]*)\)")


def family(set_id):
    tokens = set_id.split("_")[1:]
    for key, fam in FAMILIES:
        if any(t.startswith(key) for t in tokens):
            return fam
    return "unknown"


def load(path):
    return json.loads(path.read_text()) if path.is_file() else None


def values(text):
    """'2.5' -> (2.5,), '30/70' -> (30.0, 70.0); unparsable -> None."""
    try:
        return tuple(float(x) for x in text.split("/"))
    except ValueError:
        return None


def grid_position(selected, candidates):
    """candidates: {id: tuple|None}. Edge if selected is min/max on any axis."""
    if selected is None or selected not in candidates:
        return "unknown"
    if selected == "baseline":
        return "baseline"
    vals = list(candidates.values())
    sel = candidates[selected]
    if sel is None or any(v is None or len(v) != len(sel) for v in vals):
        return "unknown"
    for axis in range(len(sel)):
        column = [v[axis] for v in vals]
        if sel[axis] in (min(column), max(column)):
            return "edge"
    return "interior"


def schema2_candidates(set_dir):
    addendum = set_dir / "research-addendum.md"
    m = RANKING.search(addendum.read_text()) if addendum.is_file() else None
    if not m:
        return None, {}
    ranked = CANDIDATE.findall(m.group(1))
    return ranked[0][0], {cid: values(v) for cid, v in ranked}


def legacy_candidates(set_dir):
    sel = load(set_dir / "selection.json") or {}
    short = lambda run_id: run_id.split("__", 1)[1] if "__" in run_id else run_id
    params = {}
    attempts = set_dir / "attempts.jsonl"
    if attempts.is_file():
        for line in attempts.read_text().splitlines():
            event = json.loads(line)
            if event.get("event") == "start":
                p = event.get("parameters") or {}
                params[short(event["run_id"])] = tuple(float(p[k]) for k in sorted(p)) or None
    ids = [short(r) for r in sel.get("all_attempt_ids", [])]
    selected = sel.get("selected_run_id")
    return (short(selected) if selected else None), {i: params.get(i) for i in ids}


def ledger(root):
    root = Path(root)
    backlog = (root / "backlog.md").read_text() if (root / "backlog.md").is_file() else ""
    checked = [l for l in backlog.splitlines() if l.lstrip().startswith("- [x]")]
    sets = []
    for set_dir in sorted(p for p in (root / "research").iterdir() if p.is_dir()):
        set_id = set_dir.name
        pub = load(set_dir / "publication.json")
        if pub is not None:
            source, conclusion, attempts = "schema2", pub.get("conclusion"), pub.get("attempt_count")
            selected, candidates = schema2_candidates(set_dir)
        else:
            status = load(set_dir / "status.json") or {}
            source, conclusion, attempts = "legacy", status.get("conclusion"), status.get("strategy_attempts")
            selected, candidates = legacy_candidates(set_dir)
        sets.append({
            "set_id": set_id,
            "source": source,
            "hypothesis_family": family(set_id),
            "conclusion": conclusion or "unknown",
            "candidate_count": len(candidates) or None,
            "selected_candidate": selected or "unknown",
            "grid_position": grid_position(selected, candidates),
            "attempts": attempts if isinstance(attempts, int) else None,
            "backlog_checked": any(f"research/{set_id}/" in l for l in checked),
        })

    def counts(key, rows):
        out = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))

    known = [s for s in sets if s["grid_position"] != "unknown"]
    edge = sum(s["grid_position"] == "edge" for s in known)
    families = sorted({s["hypothesis_family"] for s in sets})
    return {
        "sets": sets,
        "aggregates": {
            "set_count": len(sets),
            "conclusion_counts": counts("conclusion", sets),
            "grid_position_counts": counts("grid_position", sets),
            "edge_selection_ratio": round(edge / len(known), 4) if known else None,
            "family_conclusion_counts": {
                f: counts("conclusion", [s for s in sets if s["hypothesis_family"] == f])
                for f in families},
            "cumulative_attempts": sum(s["attempts"] or 0 for s in sets),
            "sets_with_unknown_attempts": sum(s["attempts"] is None for s in sets),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    json.dump(ledger(args.root), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
