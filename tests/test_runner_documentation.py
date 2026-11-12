"""Documentation contracts only, never proof of unattended research success."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]

class RunnerDocumentation(unittest.TestCase):
    def test_runner_recovery_and_publication_contract(self):
        p = ROOT / 'docs/research-runner.md'
        self.assertTrue(p.is_file(), 'runner operations contract missing')
        text = p.read_text()
        for token in ('checkpoint', 'SIGKILL', 'exposed', '#30', '#21', 'private', 'synthetic', 'completed', 'blocked'):
            self.assertIn(token, text)
        self.assertNotIn('/Users/' + 'agent/', text)

    def test_scheduler_is_not_claimed_enabled_by_runner(self):
        p = ROOT / 'docs/research-runner.md'
        self.assertTrue(p.is_file(), 'runner operations contract missing')
        text = p.read_text()
        self.assertIn('예약 등록과 실제 운영은 별도 검증', text)
        self.assertIn('--max-turns', text)
        self.assertIn('--run-budget', text)

if __name__ == '__main__':
    unittest.main()
