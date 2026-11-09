//! Collect today's headlines per ticker into data/news/<YYYY-MM-DD>.json.
//!
//! History can't be backfilled reliably, so this runs daily from day one;
//! LLM scoring and news strategies come later.

use std::fs;
use std::path::Path;

use anyhow::Result;
use serde_json::{Map, Value, json};

use crate::data::universe;

fn kr_name(t: &str) -> &'static str {
    match t {
        "069500" => "코스피",
        "005930" => "삼성전자",
        "000660" => "SK하이닉스",
        "207940" => "삼성바이오로직스",
        "005380" => "현대차",
        "000270" => "기아",
        "035420" => "네이버",
        "051910" => "LG화학",
        "006400" => "삼성SDI",
        "105560" => "KB금융",
        "055550" => "신한지주",
        "035720" => "카카오",
        _ => "",
    }
}

fn feed_url(market: &str, t: &str) -> Result<reqwest::Url> {
    Ok(if market == "US" {
        reqwest::Url::parse_with_params(
            "https://feeds.finance.yahoo.com/rss/2.0/headline",
            &[("s", t), ("region", "US"), ("lang", "en-US")],
        )?
    } else {
        reqwest::Url::parse_with_params(
            "https://news.google.com/rss/search",
            &[("q", format!("{} 주가 when:1d", kr_name(t)).as_str()), ("hl", "ko"), ("gl", "KR"), ("ceid", "KR:ko")],
        )?
    })
}

fn headlines(market: &str, t: &str) -> Result<Value> {
    let body = reqwest::blocking::Client::new()
        .get(feed_url(market, t)?)
        .header("User-Agent", "Mozilla/5.0")
        .send()?
        .error_for_status()?
        .bytes()?;
    let ch = rss::Channel::read_from(&body[..])?;
    Ok(ch
        .items()
        .iter()
        .take(20)
        .map(|i| json!({"title": i.title(), "published": i.pub_date(), "link": i.link()}))
        .collect())
}

pub fn collect() -> Result<()> {
    let today = chrono::Local::now().date_naive().to_string();
    let mut out = Map::new();
    for m in ["US", "KR"] {
        for t in universe(m) {
            let v = headlines(m, t).unwrap_or_else(|e| {
                eprintln!("[news] {m}:{t}: {e:#}");
                json!([])
            });
            out.insert(format!("{m}:{t}"), v);
        }
    }
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("data").join("news");
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(format!("{today}.json")), serde_json::to_string_pretty(&out)?)?;
    let counts: Vec<String> = out.iter().map(|(k, v)| format!("{k}={}", v.as_array().map_or(0, Vec::len))).collect();
    println!("{today} {}", counts.join(" "));
    Ok(())
}
