"""Offline publication-policy contracts, not proof of data/research success."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TossPublicationContracts(unittest.TestCase):
    def test_private_artifact_policy_is_explicit(self):
        doc = (ROOT / 'docs/toss-data.md').read_text()
        for token in ('private', 'nextBefore', 'adjusted', 'exposed', '#26', 'redistribution', '600', '30'):
            self.assertIn(token, doc)
        self.assertNotIn('/Users/', doc)

    def test_research_contract_allows_private_numeric_evidence(self):
        doc = (ROOT / 'docs/daily-research-set.md').read_text()
        self.assertIn('## 제한된 데이터의 비공개 증거', doc)
        self.assertIn('원본 수치', doc)
        self.assertIn('SHA-256', doc)
        self.assertIn('공개', doc)

if __name__ == '__main__':
    unittest.main()
