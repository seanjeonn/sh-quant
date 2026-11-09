"""Collect today's headlines per ticker into data/news/<YYYY-MM-DD>.json.

History can't be backfilled reliably, so this runs daily from day one;
LLM scoring and news strategies come later (P3).
"""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import quote

import feedparser

from engine.data import UNIVERSE

KR_NAMES = {"069500": "코스피", "005930": "삼성전자", "000660": "SK하이닉스", "207940": "삼성바이오로직스",
            "005380": "현대차", "000270": "기아", "035420": "네이버", "051910": "LG화학",
            "006400": "삼성SDI", "105560": "KB금융", "055550": "신한지주", "035720": "카카오"}
OUT = Path(__file__).resolve().parent / "data" / "news"


def feed_url(market: str, t: str) -> str:
    if market == "US":
        return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={t}&region=US&lang=en-US"
    return f"https://news.google.com/rss/search?q={quote(KR_NAMES[t] + ' 주가')}+when:1d&hl=ko&gl=KR&ceid=KR:ko"


def main() -> None:
    today = dt.date.today().isoformat()
    out = {}
    for market, tickers in UNIVERSE.items():
        for t in tickers:
            f = feedparser.parse(feed_url(market, t))
            out[f"{market}:{t}"] = [{"title": e.get("title", ""), "published": e.get("published", ""),
                                     "link": e.get("link", "")} for e in f.entries[:20]]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{today}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(today, {k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
