"""Contracts for the integration-step backlog checkmark tool (#78)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import backlog_sync  # noqa: E402

BACKLOG = """# Strategy backlog

- [x] Old [s](research/2026-01-01_old_trend/publication.json), 완료·defer.
- [ ] MACD(12,26,9) 시그널선 상향 돌파
- [ ] MACD 히스토그램 변형
- [ ] 변동성 타기팅
"""


def make(root, sid, **pub):
    d = root / "research" / sid; d.mkdir(parents=True)
    (d / "publication.json").write_text(json.dumps(dict(set_id=sid, status="completed", conclusion="reject", **pub)))
    return d


class BacklogSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "backlog.md").write_text(BACKLOG)
        make(self.root, "2026-01-01_old_trend")
        d = make(self.root, "2026-01-02_macd_x", tracking_issue="https://github.com/seanjeonn/sh-quant/issues/90")
        (d / "research-addendum.md").write_text("x")

    def test_pending_lists_unlinked_published_sets_only(self):
        self.assertEqual(backlog_sync.pending(self.root), [{"set_id": "2026-01-02_macd_x", "conclusion": "reject"}])

    def test_mark_rewrites_exactly_one_line_then_is_not_pending(self):
        line = backlog_sync.mark(self.root, "2026-01-02_macd_x", "MACD(12,26,9)")
        self.assertEqual(line, "- [x] MACD(12,26,9) 시그널선 상향 돌파 — [2026-01-02 세트](research/2026-01-02_macd_x/publication.json), "
                               "완료·reject; [정성 기록](research/2026-01-02_macd_x/research-addendum.md), #90.\n")
        text = (self.root / "backlog.md").read_text()
        self.assertEqual(text, BACKLOG.replace("- [ ] MACD(12,26,9) 시그널선 상향 돌파\n", line))
        self.assertEqual(backlog_sync.pending(self.root), [])
        with self.assertRaisesRegex(SystemExit, "already linked"):
            backlog_sync.mark(self.root, "2026-01-02_macd_x", "변동성")

    def test_mark_refuses_ambiguous_missing_or_incomplete(self):
        for sid, item, msg in [("2026-01-02_macd_x", "MACD", "matched 2"),
                               ("2026-01-02_macd_x", "없는 항목", "matched 0"),
                               ("2026-01-03_missing", "변동성", "no completed"),
                               ("../evil", "변동성", "invalid set id")]:
            with self.subTest(item=item, sid=sid), self.assertRaisesRegex(SystemExit, msg):
                backlog_sync.mark(self.root, sid, item)
        self.assertEqual((self.root / "backlog.md").read_text(), BACKLOG)


if __name__ == "__main__":
    unittest.main()
