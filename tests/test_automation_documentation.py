"""Configuration/document contracts, not proof of an active scheduler."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]

class AutomationDocumentation(unittest.TestCase):
    def test_budget_schedule_and_delivery_boundaries(self):
        p=ROOT/'docs/automation.md'
        self.assertTrue(p.is_file(), 'bounded automation operations guide missing')
        text=p.read_text()
        for token in ('14:30','17:00','13:30','1800','120','canary','paused','#33','Discord','receipt','private'):
            self.assertIn(token,text)
        self.assertNotIn('/Users/'+'agent/',text)
        self.assertIn('configured',text)
        self.assertIn('tested',text)
        self.assertIn('scheduled',text)
        self.assertIn('running',text)

    def test_cross_layer_scope_and_publication_evidence_contract(self):
        text=(ROOT/'docs/automation.md').read_text()
        for token in ('supervisor_scope', 'active-scope.json', 'publication_pending',
                      '--mode publication', 'publication.json',
                      'managed_issue_body_sha256', 'PR head/base/files'):
            self.assertIn(token,text)

    def test_no_model_stdout_as_delivery_source(self):
        p=ROOT/'docs/automation.md'
        self.assertTrue(p.is_file(), 'bounded automation operations guide missing')
        text=p.read_text()
        self.assertIn('raw model stdout',text)
        self.assertIn('allowlist',text)
        self.assertIn('읽기 전용',text)

if __name__=='__main__':unittest.main()
