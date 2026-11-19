#!/usr/bin/env python3
"""GDELT GKG 2.1 historical news backfill (#112).

plan:   freeze the GKG file list (English + translation) for [start, end) from
        GDELT's master file lists into <output>/plan.json.
run:    resumable, bounded download. Per file: download, verify md5, stream the
        rows, keep only articles whose V1Organizations match a preregistered
        alias, write them to matches/<YYYYMM>/<name>.jsonl, delete the zip and
        append to done.jsonl. Failures go to failed.jsonl; 3 per file block.
status: counts only (no URLs or tone values).

Output stays private (outside Git, 700/600). GDELT data is free to use and
redistribute with a citation and link to https://www.gdeltproject.org/.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_set as rs
from research_set import Blocked, digest, encode, immutable, load, read, require

LISTS = ('https://data.gdeltproject.org/gdeltv2/masterfilelist.txt',
         'https://data.gdeltproject.org/gdeltv2/masterfilelist-translation.txt')
GKG = re.compile(r'https?://data\.gdeltproject\.org/gdeltv2/((\d{14})\.(?:translation\.)?gkg\.csv\.zip)')
# GKG 2.1 columns (27, tab-separated). Verified against live files 2026-11-19.
DATE, SOURCE, URL, ORGS, TONE, TRANSLATION, COLUMNS = 1, 3, 4, 13, 15, 25, 27
MAX_FAILURES = 3


def fetch(url):
    request = urllib.request.Request(url.replace('http://', 'https://', 1), headers={'User-Agent': 'research-client'})
    return urllib.request.urlopen(request, timeout=300)


def private_dir(path):
    rs.safe_path(path, private=True, directory=True, missing=True)
    try:
        path.mkdir(mode=0o700); rs.fsync_dir(path.parent)
    except FileExistsError:  # concurrent workers creating the same month
        pass
    return path


def replace_file(path, raw):
    """Atomic overwrite: a rerun after a crash rewrites identical content."""
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path); rs.fsync_dir(path.parent)


def append(path, event):
    rs.safe_path(path, private=True, missing=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'ab') as f:
        f.write(encode(event)); f.flush(); os.fsync(f.fileno())


def events(path):
    return [rs.decode_json(line) for line in read(path).splitlines() if line] if path.exists() else []


def plan(start, end, output, *, opener=fetch):
    output = Path(output)
    require(dt.date.fromisoformat(start) < dt.date.fromisoformat(end), 'invalid_range')
    lo, hi = start.replace('-', ''), end.replace('-', '')
    files, lists = {}, {}
    for url in LISTS:
        raw = opener(url).read(); lists[url.rsplit('/', 1)[1]] = digest(raw)
        for line in raw.decode().splitlines():
            parts = line.split()
            match = GKG.fullmatch(parts[2]) if len(parts) == 3 else None
            if match and lo <= match.group(2)[:8] < hi:
                require(match.group(1) not in files, 'duplicate_file')
                files[match.group(1)] = dict(name=match.group(1), size=int(parts[0]), md5=parts[1], url=parts[2])
    require(files, 'empty_plan')
    private_dir(output)
    immutable(output / 'plan.json', encode(dict(schema_version=1, start=start, end=end, lists_sha256=lists,
                                                 files=sorted(files.values(), key=lambda f: f['name']))))
    return len(files)


def alias_index(raw):
    # The catalog is a committed public file, not private output.
    data = rs.decode_json(raw); index = {}
    for item in data['instruments']:
        key = item['market'] + ':' + item['ticker']
        require(item['coverage'] in ('orgs', 'none'), 'invalid_coverage')
        require(bool(item.get('aliases')) == (item['coverage'] == 'orgs'), 'invalid_aliases')
        for alias in item.get('aliases', []):
            # "name", or {"name", "until"} when the name later means another entity.
            name, until = (alias, None) if isinstance(alias, str) else (alias['name'], alias['until'])
            require(isinstance(name, str) and name == name.strip().lower() and name and ';' not in name, 'invalid_alias')
            if until is not None: dt.date.fromisoformat(until)
            index.setdefault(name, []).append((key, until and until.replace('-', '')))
    return index


def scan(text_lines, index):
    """Matched article records plus count of malformed rows."""
    out, bad = [], 0
    for line in text_lines:
        c = line.rstrip('\n').split('\t')
        if len(c) != COLUMNS:
            bad += 1; continue
        day = c[DATE][:8]
        hits = sorted({k for org in c[ORGS].split(';') for k, until in index.get(org, ()) if not until or day < until})
        if not hits: continue
        try:
            tone = [float(x) for x in c[TONE].split(',')]
            require(len(tone) == 7 and re.fullmatch(r'\d{14}', c[DATE]), 'bad_row')
        except (ValueError, Blocked):
            bad += 1; continue
        lang = c[TRANSLATION].split(';')[0].removeprefix('srclc:') or 'eng'
        out.append(dict(t=c[DATE], src=c[SOURCE], url=c[URL], tone=tone, lang=lang, inst=hits))
    return out, bad


def process(entry, output, index, opener):
    tmp = output / 'tmp' / (entry['name'] + '.part')
    md5 = hashlib.md5()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f, opener(entry['url']) as response:
        while chunk := response.read(1 << 20):
            md5.update(chunk); f.write(chunk)
    try:
        require(md5.hexdigest() == entry['md5'] and tmp.stat().st_size == entry['size'], 'md5_mismatch')
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist(); require(len(names) == 1, 'unexpected_archive')
            with z.open(names[0]) as raw:
                rows, bad = scan(io.TextIOWrapper(raw, encoding='utf-8', errors='replace'), index)
    finally:
        tmp.unlink()
    month = private_dir(output / 'matches' / entry['name'][:6])
    replace_file(month / (entry['name'] + '.jsonl'), b''.join(encode(r) for r in rows))
    return dict(name=entry['name'], bytes=entry['size'], matched=len(rows), bad_rows=bad)


def run(output, aliases, *, max_files, max_minutes, workers=4, opener=fetch):
    output = Path(output); deadline = time.monotonic() + max_minutes * 60
    files = load(output / 'plan.json')['files']
    raw = Path(aliases).read_bytes(); index = alias_index(raw); alias_sha = digest(raw)
    done_events = events(output / 'done.jsonl')
    require(all(e['aliases_sha256'] == alias_sha for e in done_events), 'aliases_changed')
    done = {e['name'] for e in done_events}
    failures = {}
    for e in events(output / 'failed.jsonl'):
        failures[e['name']] = failures.get(e['name'], 0) + 1
    require(max(failures.values(), default=0) < MAX_FAILURES, 'retry_limit')
    tmp = private_dir(output / 'tmp')
    for leftover in tmp.glob('*.part'): leftover.unlink()  # our own interrupted downloads
    private_dir(output / 'matches')
    pending = [f for f in files if f['name'] not in done][:max_files]
    finished = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for entry in pending:
            futures.append((entry, pool.submit(lambda e=entry: None if time.monotonic() > deadline
                                               else process(e, output, index, opener))))
        for entry, future in futures:
            try:
                result = future.result()
            except Exception as error:  # recorded, never skipped silently
                code = str(error) if type(error) is Blocked else type(error).__name__
                append(output / 'failed.jsonl', dict(name=entry['name'], code=code))
                failures[entry['name']] = failures.get(entry['name'], 0) + 1
                continue
            if result is None: continue
            append(output / 'done.jsonl', dict(result, aliases_sha256=alias_sha))
            finished += 1
    require(max(failures.values(), default=0) < MAX_FAILURES, 'retry_limit')
    return finished


def status(output):
    output = Path(output)
    files = load(output / 'plan.json')['files']; done = events(output / 'done.jsonl')
    failed = events(output / 'failed.jsonl'); names = {e['name'] for e in done}
    return dict(planned=len(files), done=len(names), pending=len(files) - len(names),
                failed_attempts=len(failed), failing_files=len({e['name'] for e in failed} - names),
                bytes_done=sum(e['bytes'] for e in done), bytes_planned=sum(f['size'] for f in files),
                matched_articles=sum(e['matched'] for e in done), bad_rows=sum(e['bad_rows'] for e in done))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('plan'); a.add_argument('--start', required=True); a.add_argument('--end', required=True)
    b = sub.add_parser('run'); b.add_argument('--aliases', required=True)
    b.add_argument('--max-files', type=int, required=True); b.add_argument('--max-minutes', type=float, required=True)
    b.add_argument('--workers', type=int, default=4, choices=range(1, 5))
    sub.add_parser('status')
    for s in (a, b, sub.choices['status']): s.add_argument('--output', required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'plan': value = dict(planned=plan(args.start, args.end, args.output))
        elif args.command == 'run':
            value = dict(finished=run(args.output, args.aliases, max_files=args.max_files,
                                      max_minutes=args.max_minutes, workers=args.workers))
            value.update(status(args.output))
        else: value = status(args.output)
        print(json.dumps(value, sort_keys=True)); return 0
    except (Exception, KeyboardInterrupt) as e:
        print(json.dumps({'state': 'blocked', 'code': str(e) if type(e) is Blocked else None}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
