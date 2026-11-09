//! Fixed universe + cached daily OHLCV from Yahoo's chart API. Agents must not edit this file.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use chrono::{DateTime, Local, NaiveDate};

pub const START: (i32, u32, u32) = (2015, 1, 1);

pub fn universe(market: &str) -> &'static [&'static str] {
    match market {
        "US" => &["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "BRK-B"],
        // KODEX200 + large caps listed before 2015
        "KR" => &[
            "069500", "005930", "000660", "207940", "005380", "000270", "035420", "051910", "006400",
            "105560", "055550", "035720",
        ],
        _ => &[],
    }
}

fn yahoo_symbol(market: &str, t: &str) -> String {
    if market == "KR" { format!("{t}.KS") } else { t.to_string() }
}

#[derive(Debug, Clone, Default)]
pub struct Bars {
    pub dates: Vec<NaiveDate>,
    pub open: Vec<f64>,
    pub high: Vec<f64>,
    pub low: Vec<f64>,
    pub close: Vec<f64>,
    pub volume: Vec<f64>,
}

impl Bars {
    pub fn len(&self) -> usize {
        self.close.len()
    }

    pub fn col(&self, name: &str) -> Option<&[f64]> {
        Some(match name {
            "open" => &self.open,
            "high" => &self.high,
            "low" => &self.low,
            "close" => &self.close,
            "volume" => &self.volume,
            _ => return None,
        })
    }

    pub fn head(&self, k: usize) -> Bars {
        Bars {
            dates: self.dates[..k].to_vec(),
            open: self.open[..k].to_vec(),
            high: self.high[..k].to_vec(),
            low: self.low[..k].to_vec(),
            close: self.close[..k].to_vec(),
            volume: self.volume[..k].to_vec(),
        }
    }

    #[cfg(test)]
    pub fn from_close(close: Vec<f64>) -> Bars {
        let d0 = NaiveDate::from_ymd_opt(2020, 1, 1).unwrap();
        Bars {
            dates: (0..close.len() as u64).map(|i| d0 + chrono::Days::new(i)).collect(),
            open: close.clone(),
            high: close.clone(),
            low: close.clone(),
            volume: vec![1.0; close.len()],
            close,
        }
    }

    fn push(&mut self, d: NaiveDate, o: f64, h: f64, l: f64, c: f64, v: f64) {
        self.dates.push(d);
        self.open.push(o);
        self.high.push(h);
        self.low.push(l);
        self.close.push(c);
        self.volume.push(v);
    }

    fn to_csv(&self) -> String {
        let mut s = String::from("date,open,high,low,close,volume\n");
        for i in 0..self.len() {
            s += &format!(
                "{},{},{},{},{},{}\n",
                self.dates[i], self.open[i], self.high[i], self.low[i], self.close[i], self.volume[i]
            );
        }
        s
    }

    fn from_csv(text: &str) -> Result<Bars> {
        let mut b = Bars::default();
        for line in text.lines().skip(1) {
            let f: Vec<&str> = line.split(',').collect();
            if f.len() != 6 {
                bail!("bad cache line: {line}");
            }
            let n = |i: usize| f[i].parse::<f64>().with_context(|| format!("bad number in: {line}"));
            b.push(f[0].parse()?, n(1)?, n(2)?, n(3)?, n(4)?, n(5)?);
        }
        Ok(b)
    }
}

/// Daily bars, split/dividend adjusted like yfinance's auto_adjust (OHLC scaled by adjclose/close).
fn fetch(symbol: &str) -> Result<Bars> {
    let (y, m, d) = START;
    let p1 = NaiveDate::from_ymd_opt(y, m, d).unwrap().and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp();
    let p2 = chrono::Utc::now().timestamp();
    let url = format!(
        "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit"
    );
    let v: serde_json::Value = reqwest::blocking::Client::new()
        .get(url)
        .header("User-Agent", "Mozilla/5.0")
        .send()?
        .error_for_status()?
        .json()?;
    let r = &v["chart"]["result"][0];
    let off = r["meta"]["gmtoffset"].as_i64().unwrap_or(0);
    let ts = r["timestamp"].as_array().context("no timestamps in response")?;
    let q = &r["indicators"]["quote"][0];
    let adj = &r["indicators"]["adjclose"][0]["adjclose"];
    let mut b = Bars::default();
    for (i, t) in ts.iter().enumerate() {
        let get = |k: &str| q[k][i].as_f64();
        let (Some(o), Some(h), Some(l), Some(c), Some(vol), Some(a), Some(t)) =
            (get("open"), get("high"), get("low"), get("close"), get("volume"), adj[i].as_f64(), t.as_i64())
        else {
            continue;
        };
        if c <= 0.0 {
            continue;
        }
        let k = a / c;
        let date = DateTime::from_timestamp(t + off, 0).context("bad timestamp")?.date_naive();
        if b.dates.last() == Some(&date) {
            continue; // Yahoo occasionally repeats the live bar
        }
        b.push(date, o * k, h * k, l * k, a, vol);
    }
    if b.len() == 0 {
        bail!("empty history");
    }
    Ok(b)
}

fn cache_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("data").join("cache")
}

fn fresh_today(p: &Path) -> bool {
    fs::metadata(p)
        .and_then(|m| m.modified())
        .map(|t| DateTime::<Local>::from(t).date_naive() == Local::now().date_naive())
        .unwrap_or(false)
}

/// (ticker, bars) for a market. Cache refreshed once per day; a stale cache beats no data.
pub fn load(market: &str) -> Result<Vec<(String, Bars)>> {
    let dir = cache_dir();
    fs::create_dir_all(&dir)?;
    let mut out = vec![];
    for t in universe(market) {
        let f = dir.join(format!("{market}_{t}.yahoo.csv"));
        let bars = if fresh_today(&f) {
            Bars::from_csv(&fs::read_to_string(&f)?)?
        } else {
            match fetch(&yahoo_symbol(market, t)) {
                Ok(b) => {
                    fs::write(&f, b.to_csv())?;
                    b
                }
                Err(e) if f.exists() => {
                    eprintln!("[data] {market}:{t} refresh failed, using stale cache: {e:#}");
                    Bars::from_csv(&fs::read_to_string(&f)?)?
                }
                Err(e) => {
                    eprintln!("[data] skip {market}:{t}: {e:#}");
                    continue;
                }
            }
        };
        out.push((t.to_string(), bars));
    }
    Ok(out)
}
