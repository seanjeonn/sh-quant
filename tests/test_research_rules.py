"""Offline documentation/template contracts, NOT a research-set validator."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ResearchRulesContracts(unittest.TestCase):
    def test_plan_template_has_baseline_and_multiple_variants(self):
        plan = json.loads((ROOT / "hermes/templates/plan.json").read_text())
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["timezone"], "Asia/Seoul")
        self.assertGreaterEqual(len(plan["variants"]), 2)
        ids = [plan["baseline"]["run_id"], *(v["run_id"] for v in plan["variants"])]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsNone(plan["engine_commit"])
        self.assertIsNone(plan["data_manifest_sha256"])

    def test_search_budget_is_bounded_and_counts_repairs(self):
        plan = json.loads((ROOT / "hermes/templates/plan.json").read_text())
        budget = plan["budget"]
        self.assertGreaterEqual(budget["max_attempts"], 1 + len(plan["variants"]))
        self.assertGreater(budget["max_wall_minutes"], 0)
        self.assertLessEqual(budget["max_repairs"], budget["max_attempts"])

    def test_templates_disclose_exposed_oos_and_is_only_selection(self):
        plan = json.loads((ROOT / "hermes/templates/plan.json").read_text())
        selection = json.loads((ROOT / "hermes/templates/selection.json").read_text())
        self.assertEqual(plan["selection"]["split"], "IS")
        self.assertEqual(selection["selection_split"], "IS")
        self.assertEqual(plan["holdout_status"], "exposed")
        self.assertEqual(selection["holdout_status"], "exposed")
        self.assertIs(selection["oos_used_for_selection"], False)
        self.assertIsNone(selection["selected_run_id"])
        self.assertEqual(selection["successful_variant_ids"], [])

    def test_report_template_does_not_claim_real_completion(self):
        report = (ROOT / "hermes/templates/report.md").read_text()
        self.assertIn("TODO", report)
        self.assertIn("blocked", report)
        self.assertIn("null", report)
        self.assertIn("최소 2개", report)
        self.assertIn("미관측 holdout이 아님", report)
        self.assertNotIn("- [x]", report)

    def test_old_single_file_daily_rules_are_removed(self):
        files = ["AGENTS.md", "README.md", "hermes/SKILL.md"]
        for name in files:
            text = (ROOT / name).read_text()
            with self.subTest(file=name):
                self.assertNotIn("하루 전략 1개.", text)
                self.assertNotIn("하루 1개.", text)
                self.assertNotIn("`src/` Rust 엔진. 에이전트 수정 금지.", text)
        self.assertNotIn("daily agent must only add", (ROOT / "AGENTS.md").read_text())

    def test_markdown_relative_links_resolve(self):
        files = ["README.md", "AGENTS.md", "docs/github-workflow.md", "docs/daily-research-set.md"]
        for name in files:
            source = ROOT / name
            for target in re.findall(r"\]\(([^)]+)\)", source.read_text()):
                if re.match(r"[a-z]+://|#", target):
                    continue
                with self.subTest(source=name, target=target):
                    self.assertTrue((source.parent / target.split("#")[0]).is_file())
        for name in ["plan.json", "selection.json", "report.md"]:
            self.assertTrue((ROOT / "hermes/templates" / name).is_file())

    def test_skill_frontmatter_and_required_sections(self):
        text = (ROOT / "hermes/SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        frontmatter, body = text[4:].split("\n---\n", 1)
        fields = dict(re.findall(r"^(name|description|version|author|platforms): (.+)$", frontmatter, re.M))
        self.assertEqual(fields["name"], "daily-backtest")
        self.assertLessEqual(len(fields["description"]), 60)
        self.assertTrue(fields["description"].endswith("."))
        self.assertEqual(fields["version"], "0.2.0")
        for section in ["When to Use", "Prerequisites", "Procedure", "Pitfalls", "Verification"]:
            self.assertIn("## " + section, body)
        self.assertNotRegex(text, r"/Users/|/home/[^<]")

    def test_engine_comments_limit_research_not_approved_engineering(self):
        for name in ["src/backtest.rs", "src/data.rs"]:
            with self.subTest(file=name):
                header = "\n".join((ROOT / name).read_text().splitlines()[:4]).lower()
                self.assertIn("research-mode", header)
                self.assertIn("engineering", header)
                self.assertNotIn("agents must not edit this file.", header.replace("research-mode agents must not edit this file.", ""))


if __name__ == "__main__":
    unittest.main()
