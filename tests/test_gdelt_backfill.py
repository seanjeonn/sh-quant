"""#112 GDELT backfill. Synthetic GKG fixtures only; no network."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import gdelt_backfill as g  # noqa: E402
import research_set as rs  # noqa: E402

BASE = 'http://data.gdeltproject.org/gdeltv2/'


def row(ts, orgs, tone='1.5,3,1.5,4.5,20,1,300', translation='', url='https://example.invalid/a'):
    c = [''] * 27
    c[0], c[1], c[3], c[4], c[13], c[15], c[25] = ts + '-0', ts, 'example.invalid', url, orgs, tone, translation
    return '\t'.join(c)


def gkg(*rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('x.gkg.csv', '\n'.join(rows) + '\n')
    return buf.getvalue()


class Fake:
    """Serves synthetic master lists and archives; counts archive downloads."""

    def __init__(self, archives):
        self.archives = archives; self.calls = []
        lines = [f'{len(b)} {hashlib.md5(b).hexdigest()} {BASE}{n}' for n, b in archives.items()]
        lines.append(f'10 {"0" * 32} {BASE}20240101000000.export.CSV.zip')  # ignored kind
        eng = [l for l in lines if 'translation' not in l]; tr = [l for l in lines if 'translation' in l]
        self.lists = {g.LISTS[0]: '\n'.join(eng).encode(), g.LISTS[1]: '\n'.join(tr).encode()}

    def __call__(self, url):
        if url in self.lists: return io.BytesIO(self.lists[url])
        name = url.rsplit('/', 1)[1]; self.calls.append(name)
        return io.BytesIO(self.archives[name])


ALIASES = {'schema_version': 1, 'instruments': [
    {'market': 'US', 'ticker': 'AAPL', 'coverage': 'orgs', 'aliases': ['apple inc']},
    {'market': 'KR', 'ticker': '005930', 'coverage': 'orgs', 'aliases': ['samsung electronics']},
    {'market': 'KR', 'ticker': '009540', 'coverage': 'orgs',
     'aliases': [{'name': 'hyundai heavy industries', 'until': '2024-01-02'}]},
    {'market': 'US', 'ticker': 'SPY', 'coverage': 'none'}]}


class Backfill(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.base.chmod(0o700)
        self.out = self.base / 'out'
        self.aliases = self.base / 'aliases.json'; self.aliases.write_text(json.dumps(ALIASES))
        self.archives = {
            '20240101000000.gkg.csv.zip': gkg(
                row('20240101000000', 'apple inc;spdr s&p 500'),
                row('20240101000000', 'apple incorporated'),  # not an exact alias
                row('20240101000000', 'apple inc', tone='bad'),
                'too\tfew\tcolumns'),
            '20240101000000.translation.gkg.csv.zip': gkg(
                row('20240101000000', 'samsung electronics;apple inc', translation='srclc:kor;eng:GT-KOR 1.0')),
            '20240102000000.gkg.csv.zip': gkg(row('20240102000000', 'hyundai heavy industries')),  # past until
            '20240201000000.gkg.csv.zip': gkg(row('20240201000000', 'apple inc')),  # outside range
        }
        self.fake = Fake(self.archives)

    def run_once(self, **kw):
        return g.run(self.out, self.aliases, max_files=kw.pop('max_files', 10), max_minutes=5, opener=self.fake, **kw)

    def matches(self):
        return [json.loads(l) for p in sorted((self.out / 'matches').rglob('*.jsonl')) for l in p.read_text().splitlines()]

    def test_plan_run_match_resume(self):
        self.assertEqual(g.plan('2024-01-01', '2024-02-01', self.out, opener=self.fake), 3)
        self.assertEqual(self.run_once(max_files=1), 1)
        self.assertEqual(self.run_once(), 2)
        self.assertEqual(self.run_once(), 0)  # resume: nothing downloaded again
        self.assertEqual(sorted(self.fake.calls), sorted(n for n in self.archives if not n.startswith('202402')))
        rows = self.matches()
        self.assertEqual([(r['inst'], r['lang']) for r in rows],
                         [(['US:AAPL'], 'eng'), (['KR:005930', 'US:AAPL'], 'kor')])
        self.assertEqual(g.scan([row('20240101000000', 'hyundai heavy industries')], g.alias_index(self.aliases.read_bytes()))[0][0]['inst'],
                         ['KR:009540'])
        self.assertEqual(rows[0]['tone'], [1.5, 3, 1.5, 4.5, 20, 1, 300])
        st = g.status(self.out)
        self.assertEqual((st['done'], st['pending'], st['matched_articles'], st['bad_rows']), (3, 0, 2, 2))
        self.assertEqual(list((self.out / 'tmp').iterdir()), [])  # zips deleted
        self.assertNotIn('example.invalid', json.dumps(st))

    def test_md5_mismatch_is_recorded_and_blocks_after_retry_limit(self):
        g.plan('2024-01-01', '2024-01-02', self.out, opener=self.fake)
        self.fake.archives['20240101000000.gkg.csv.zip'] = b'corrupted'
        for _ in range(g.MAX_FAILURES - 1):
            self.run_once()
        with self.assertRaises(rs.Blocked): self.run_once()
        failed = [json.loads(l) for l in (self.out / 'failed.jsonl').read_text().splitlines()]
        self.assertEqual({f['code'] for f in failed}, {'md5_mismatch'})
        with self.assertRaises(rs.Blocked): self.run_once()  # stays blocked, no silent skip

    def test_declared_missing_is_not_done_and_resume_preserves_ledgers(self):
        g.plan('2024-01-01', '2024-02-01', self.out, opener=self.fake)
        missing, failed = '20240101000000.gkg.csv.zip', self.out / 'failed.jsonl'
        for _ in range(g.MAX_FAILURES):
            g.append(failed, {'name': missing, 'code': 'HTTPError'})
        original_failures = failed.read_bytes()
        original_plan = (self.out / 'plan.json').read_bytes()
        with self.assertRaisesRegex(rs.Blocked, 'retry_limit'):
            self.run_once()
        g.declare_missing(self.out, [missing])
        self.assertEqual(self.run_once(), 2)
        self.assertEqual(self.run_once(), 0)
        st = g.status(self.out)
        self.assertEqual((st['planned'], st['done'], st['pending'], st['missing'], st['failing_files']), (3, 2, 0, 1, 0))
        self.assertEqual(st['missing_bytes'], len(self.archives[missing]))
        self.assertNotIn(missing, self.fake.calls)
        self.assertEqual(failed.read_bytes(), original_failures)
        self.assertEqual((self.out / 'plan.json').read_bytes(), original_plan)

    def test_missing_declaration_cannot_extend_to_other_failures(self):
        g.plan('2024-01-01', '2024-02-01', self.out, opener=self.fake)
        first, second, bad = list(self.archives)[:3]
        failed = self.out / 'failed.jsonl'
        with self.assertRaisesRegex(rs.Blocked, 'invalid_missing'):
            g.declare_missing(self.out, [first])
        for _ in range(g.MAX_FAILURES):
            g.append(failed, {'name': first, 'code': 'HTTPError'})
            g.append(failed, {'name': bad, 'code': 'md5_mismatch'})
        with self.assertRaisesRegex(rs.Blocked, 'invalid_missing'):
            g.declare_missing(self.out, [bad])
        g.declare_missing(self.out, [first])
        g.declare_missing(self.out, [first])  # identical receipt is idempotent
        for _ in range(g.MAX_FAILURES):
            g.append(failed, {'name': second, 'code': 'HTTPError'})
        with self.assertRaises(rs.Blocked):
            g.declare_missing(self.out, [first, second])
        with self.assertRaisesRegex(rs.Blocked, 'retry_limit'):
            self.run_once()
        self.assertEqual(self.fake.calls, [])

    def test_interrupt_after_match_write_does_not_duplicate(self):
        g.plan('2024-01-01', '2024-01-02', self.out, opener=self.fake)
        self.run_once()
        (self.out / 'done.jsonl').unlink(); (self.out / 'done.jsonl').touch(mode=0o600)
        (self.out / 'tmp' / 'stale.part').write_bytes(b'x')
        self.run_once()
        self.assertEqual(len(self.matches()), 2)
        self.assertFalse((self.out / 'tmp' / 'stale.part').exists())

    def test_alias_change_and_unsafe_output_are_blocked(self):
        g.plan('2024-01-01', '2024-01-02', self.out, opener=self.fake)
        self.run_once(max_files=1)
        self.aliases.write_text(json.dumps(dict(ALIASES, schema_version=2)))
        with self.assertRaises(rs.Blocked): self.run_once()
        for bad in ({'market': 'US', 'ticker': 'X', 'coverage': 'none', 'aliases': ['x']},
                    {'market': 'US', 'ticker': 'X', 'coverage': 'orgs', 'aliases': ['Apple Inc']}):
            with self.subTest(bad=bad), self.assertRaises(rs.Blocked):
                g.alias_index(json.dumps({'instruments': [bad]}).encode())
        loose = self.base / 'loose'; loose.mkdir(mode=0o755)
        with self.assertRaises(rs.Blocked): g.plan('2024-01-01', '2024-01-02', loose / 'out', opener=self.fake)

    def test_cli_status_only(self):
        g.plan('2024-01-01', '2024-01-02', self.out, opener=self.fake)
        p = subprocess.run([sys.executable, str(ROOT / 'tools/gdelt_backfill.py'), 'status', '--output', str(self.out)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(json.loads(p.stdout)['planned'], 2)
        p = subprocess.run([sys.executable, str(ROOT / 'tools/gdelt_backfill.py'), 'status', '--output', '/nope'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1); self.assertNotIn('/nope', p.stdout + p.stderr)

    def test_repository_catalog_is_valid(self):
        path = ROOT / 'universes/thematic-v1-news-aliases.json'
        if not path.exists(): self.skipTest('catalog not yet committed')
        catalog = json.loads(path.read_text()); universe = json.loads((ROOT / 'universes/thematic-v1.json').read_text())
        g.alias_index(path.read_bytes())
        self.assertEqual({(i['market'], i['ticker']) for i in catalog['instruments']},
                         {(i['market'], i['ticker']) for i in universe['instruments']})


if __name__ == '__main__':
    unittest.main()
