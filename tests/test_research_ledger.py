"""Contracts for the read-only cross-set research ledger (#72)."""
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import research_ledger  # noqa: E402

FORBIDDEN = re.compile(r"sharpe|cagr|mdd|drawdown|return|excess|pnl|profit|volatility", re.I)


def run(root):
    buf = io.StringIO()
    with redirect_stdout(buf):
        research_ledger.main(["--root", str(root)])
    return buf.getvalue()


def walk(node, key=None):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, key)


class ResearchLedger(unittest.TestCase):
    def test_current_main_sets_deterministic(self):
        out = run(ROOT)
        self.assertEqual(out, run(ROOT))
        data = json.loads(out)
        by_id = {s["set_id"]: s for s in data["sets"]}
        ema = by_id.get("2026-11-10_ema_cross")
        if ema:  # legacy report-based set handled explicitly, not guessed
            self.assertEqual((ema["source"], ema["selected_candidate"]), ("legacy", "v002"))
        for s in data["sets"]:
            self.assertIn(s["grid_position"], {"edge", "interior", "baseline", "unknown"})
            self.assertNotEqual(s["hypothesis_family"], "unknown", s["set_id"])
        agg = data["aggregates"]
        self.assertEqual(sum(agg["conclusion_counts"].values()), agg["set_count"])

    def test_no_numeric_performance_in_output(self):
        for k, v in walk(json.loads(run(ROOT))):
            self.assertIsNone(FORBIDDEN.search(k), k)
            if isinstance(v, str):
                self.assertIsNone(FORBIDDEN.search(v), v)
            if isinstance(v, float):
                self.assertEqual(k, "edge_selection_ratio")

    def test_unknowns_and_grid_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "research" / "2026-01-01_mystery").mkdir(parents=True)
            d = root / "research" / "2026-01-02_rsi_x"
            d.mkdir()
            (d / "publication.json").write_text(json.dumps({"conclusion": "defer", "attempt_count": 3}))
            (d / "research-addendum.md").write_text(
                "IS ordering was v001 (25/75), baseline (30/70), then v002 (27/73).")
            (root / "backlog.md").write_text("- [x] x [s](research/2026-01-02_rsi_x/publication.json)\n")
            data = json.loads(run(root))
        mystery, rsi = data["sets"]
        self.assertEqual((mystery["conclusion"], mystery["grid_position"], mystery["attempts"],
                          mystery["hypothesis_family"], mystery["backlog_checked"]),
                         ("unknown", "unknown", None, "unknown", False))
        self.assertEqual((rsi["selected_candidate"], rsi["grid_position"], rsi["candidate_count"],
                          rsi["hypothesis_family"], rsi["backlog_checked"]),
                         ("v001", "edge", 3, "mean_reversion", True))
        self.assertEqual(data["aggregates"]["cumulative_attempts"], 3)
        self.assertEqual(data["aggregates"]["sets_with_unknown_attempts"], 1)
        self.assertEqual(research_ledger.grid_position("v002", {"baseline": (1.0,), "v001": (3.0,), "v002": (2.0,)}),
                         "interior")


if __name__ == "__main__":
    unittest.main()
