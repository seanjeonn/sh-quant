"""SQLite 스키마와 저장 함수. 모든 시각은 UTC 'YYYY-MM-DD HH:MM:SS' 문자열."""
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

log = logging.getLogger("kingfish.db")
FMT = "%Y-%m-%d %H:%M:%S"
UTC = timezone.utc
KST = timezone(timedelta(hours=9))
SESSIONS = ("dayMarket", "preMarket", "regularMarket", "afterMarket")

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles_1m (
  symbol TEXT NOT NULL, ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS candles_5m (
  symbol TEXT NOT NULL, ts TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, n_bars INTEGER,
  complete INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (symbol, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS market_sessions (
  date TEXT, session TEXT, start_ts TEXT, end_ts TEXT, PRIMARY KEY (date, session));
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY, job TEXT, symbol TEXT, started TEXT, finished TEXT,
  ok INTEGER, rows INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(SCHEMA)
    if "complete" not in [r[1] for r in con.execute("PRAGMA table_info(candles_5m)")]:
        con.execute("ALTER TABLE candles_5m ADD COLUMN complete INTEGER NOT NULL DEFAULT 0")
    with con:  # 토큰은 connect_token() 파일로 옮겨졌다. 예전 버전이 남긴 토큰 제거
        con.execute("DELETE FROM kv WHERE k IN ('access_token','token_expires_at')")
    return con


def connect_token(path):
    """토큰 전용 DB(kv만, 0600). 시장 데이터 DB를 복사·공유해도 토큰이 따라가지 않도록 분리한다."""
    os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    os.chmod(path, 0o600)  # 이미 있던 파일도
    con = sqlite3.connect(path)
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return con


def now_utc():
    return datetime.now(UTC).strftime(FMT)


def epoch(ts):
    return datetime.strptime(ts, FMT).replace(tzinfo=UTC).timestamp()


def fmt(epoch_s):
    return datetime.fromtimestamp(epoch_s, UTC).strftime(FMT)


def to_api(ts):
    """UTC 문자열 → API `before` 형식(KST ISO 8601)."""
    return datetime.strptime(ts, FMT).replace(tzinfo=UTC).astimezone(KST).isoformat()


def to_utc(iso):
    """API ISO 8601(+09:00) → UTC 문자열. 오프셋이 없으면 KST로 간주."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(UTC).strftime(FMT)


def bucket_end(ts):
    """1m 봉 종료 시각 → 그 봉이 속한 5m 버킷의 종료 시각. 09:31..09:35 → 09:35."""
    return fmt((int(epoch(ts)) + 299) // 300 * 300)


def normalize(symbol, c):
    """API 캔들 1건 → (symbol, ts, o, h, l, c, v). 불량 봉은 None."""
    try:
        ts = to_utc(c["timestamp"])
        o, h, l, cl, v = (float(c[k]) for k in ("openPrice", "highPrice", "lowPrice", "closePrice", "volume"))
    except (KeyError, ValueError, TypeError) as e:
        log.warning("reject bar %s %r: %s", symbol, c, e)
        return None
    if not (o > 0 and cl > 0 and l > 0 and h >= l and v >= 0):
        log.warning("reject bar %s %s: o=%s h=%s l=%s c=%s v=%s", symbol, ts, o, h, l, cl, v)
        return None
    return (symbol.upper(), ts, o, h, l, cl, v)


def upsert_1m(con, rows):
    """rows: normalize() 결과 리스트. 반환 (건수, ts_min, ts_max)."""
    if not rows:
        return 0, None, None
    now = now_utc()
    with con:
        con.executemany(
            "INSERT INTO candles_1m(symbol,ts,open,high,low,close,volume,fetched_at) VALUES(?,?,?,?,?,?,?,?)"
            " ON CONFLICT(symbol,ts) DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low,"
            " close=excluded.close, volume=excluded.volume, fetched_at=excluded.fetched_at",
            [r + (now,) for r in rows])
    ts = [r[1] for r in rows]
    return len(rows), min(ts), max(ts)


def rollup_5m(con, symbol, ts_min, ts_max, now=None):
    """[ts_min, ts_max] 1m 봉이 걸친 5m 버킷들을 1m에서 처음부터 재계산(증분 아님 → 반복해도 오차 누적 없음).
    complete=1: 버킷 종료 + 65초 <= now, 즉 닫힌 뒤 최소 한 번 더 재조회된 버킷."""
    lo, hi = bucket_end(ts_min), bucket_end(ts_max)
    done = fmt(epoch(now or now_utc()) - 65)
    rows = con.execute(
        "SELECT ts,open,high,low,close,volume FROM candles_1m"
        " WHERE symbol=? AND ts > datetime(?,'-5 minutes') AND ts <= ? ORDER BY ts",
        (symbol, lo, hi)).fetchall()
    out = {}
    for ts, o, h, l, c, v in rows:
        a = out.get(bucket_end(ts))
        if a is None:
            out[bucket_end(ts)] = [o, h, l, c, v, 1]
        else:
            a[1], a[2], a[3], a[4], a[5] = max(a[1], h), min(a[2], l), c, a[4] + v, a[5] + 1
    with con:
        con.executemany("INSERT OR REPLACE INTO candles_5m(symbol,ts,open,high,low,close,volume,n_bars,complete)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        [(symbol, b, *a, int(b <= done)) for b, a in out.items()])
    return len(out)


def save_sessions(con, cal):
    """market-calendar/US result → market_sessions. 해당 3일은 지우고 다시 넣음."""
    rows, dates = [], []
    for day in (cal.get("previousBusinessDay"), cal.get("today"), cal.get("nextBusinessDay")):
        if not day:
            continue
        dates.append(day["date"])
        for s in SESSIONS:
            if day.get(s):
                rows.append((day["date"], s, to_utc(day[s]["startTime"]), to_utc(day[s]["endTime"])))
    with con:
        con.executemany("DELETE FROM market_sessions WHERE date=?", [(d,) for d in dates])
        con.executemany("INSERT INTO market_sessions VALUES(?,?,?,?)", rows)
    return len(rows)


def in_session(con, now):
    """(세션 중 여부, 다음 세션 시작 UTC 또는 None). 캘린더가 비어 있으면 (True, None)."""
    if not con.execute("SELECT 1 FROM market_sessions LIMIT 1").fetchone():
        return True, None
    active = con.execute("SELECT 1 FROM market_sessions WHERE start_ts<=? AND ?<end_ts LIMIT 1", (now, now)).fetchone()
    nxt = con.execute("SELECT MIN(start_ts) FROM market_sessions WHERE start_ts>?", (now,)).fetchone()[0]
    return bool(active), nxt


def regular_gaps(con, symbol, since, until):
    """끝난 정규장 세션별 1m 결손 [(start_ts, end_ts, missing)]. 정규장은 매 분 체결이 있어 빈 분 = 누락."""
    out = []
    for st, en in con.execute("SELECT start_ts,end_ts FROM market_sessions WHERE session='regularMarket'"
                              " AND end_ts<=? AND end_ts>? ORDER BY start_ts", (until, since)).fetchall():
        have = con.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol=? AND ts>? AND ts<=?", (symbol, st, en)).fetchone()[0]
        out.append((st, en, max(0, int(epoch(en) - epoch(st)) // 60 - have)))
    return out


def coverage_gaps(con, symbol, since, until, overlap_min):
    """세션 시간 중 수집 이력이 덮지 못한 구간 [(start, end)].
    데이터의 빈 분이 아니라 '우리가 조회하지 않은 시간'을 본다(장외 세션은 체결 없는 분이 정상이라).
    성공한 poll 1회 = 직전 overlap_min분, cover 기록 = [started, finished]."""
    cov = [(epoch(f) - overlap_min * 60, epoch(f)) for (f,) in con.execute(
        "SELECT finished FROM sync_log WHERE symbol=? AND job='poll' AND ok=1 AND finished>?", (symbol, since))]
    cov += [(epoch(s), epoch(f)) for s, f in con.execute(
        "SELECT started,finished FROM sync_log WHERE symbol=? AND job='cover' AND ok=1 AND finished>?", (symbol, since))]
    cov.sort()
    gaps = []
    for st, en in con.execute("SELECT start_ts,end_ts FROM market_sessions WHERE end_ts>? AND start_ts<?"
                              " ORDER BY start_ts", (since, until)).fetchall():
        a, b = max(epoch(st), epoch(since)), min(epoch(en), epoch(until))
        for cs, ce in cov:
            if ce <= a:
                continue
            if cs >= b:
                break
            if cs > a:
                gaps.append((a, cs))
            a = ce
            if a >= b:
                break
        if a < b:
            gaps.append((a, b))
    return [(fmt(a), fmt(b)) for a, b in gaps if b - a >= 60]


def covered(con, symbol, start, end):
    """[start, end]를 한 번에 덮는 cover 기록이 있나."""
    return con.execute("SELECT 1 FROM sync_log WHERE symbol=? AND job='cover' AND ok=1 AND started<=? AND finished>=? LIMIT 1",
                       (symbol, start, end)).fetchone() is not None


def kv_get(con, k):
    r = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r[0] if r else None


def kv_set(con, k, v):
    with con:
        con.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (k, v))


def log_sync(con, job, symbol, started, ok, rows=0, error=None, finished=None):
    with con:
        con.execute("INSERT INTO sync_log(job,symbol,started,finished,ok,rows,error) VALUES(?,?,?,?,?,?,?)",
                    (job, symbol, started, finished or now_utc(), int(ok), rows, error))
