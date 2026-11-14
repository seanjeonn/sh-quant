"""Offline policy checks for the prespecified current-classification research cohort."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ThematicCatalogTests(unittest.TestCase):
    def test_broad_prespecified_catalog_is_honest_and_retains_legacy_cohort(self):
        p=ROOT/'universes/thematic-v1.json'
        self.assertTrue(p.exists(),'expanded thematic catalog not implemented')
        v=json.loads(p.read_text());self.assertIs(v['point_in_time'],False)
        self.assertEqual(v['classification_as_of'],'2026-11-13')
        self.assertIn('current',v['selection_policy'])
        entries=v['instruments'];ids={(x['market'],x['ticker']) for x in entries}
        self.assertEqual(len(ids),len(entries));self.assertEqual(len(entries),96)
        for market in ['US','KR']:
            pool=[x for x in entries if x['market']==market]
            self.assertEqual(len(pool),48)
            self.assertGreaterEqual(len({tag for x in pool for tag in x['themes']}),12)
        legacy={'US':'SPY QQQ AAPL MSFT NVDA AMZN GOOGL META JPM XOM JNJ BRK-B'.split(),
                'KR':'069500 005930 000660 207940 005380 000270 035420 051910 006400 105560 055550 035720'.split()}
        self.assertTrue({(m,t) for m,ts in legacy.items() for t in ts}<=ids)
        berkshire=next(x for x in entries if x['ticker']=='BRK-B')
        self.assertEqual(berkshire['source_symbol'],'BRK.B')
        self.assertTrue(v['limitations'])
        self.assertTrue(all(x['themes'] for x in entries))

if __name__=='__main__':unittest.main()
