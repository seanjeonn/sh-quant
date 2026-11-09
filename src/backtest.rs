//! Fixed backtest rules. Agents must not edit this file.
//!
//! - signal at close t is the position held over bar t+1
//! - one-way cost per unit of turnover
//! - equal weight across the market universe; benchmark = equal-weight buy & hold
//! - in-sample <= IS_END, out-of-sample >= IS_END

use std::collections::BTreeMap;

use anyhow::{Result, bail};
use chrono::{Datelike, Days, NaiveDate};
use rayon::prelude::*;
use serde::Serialize;

use crate::data::Bars;
use crate::expr::{Node, eval, finalize};

pub fn cost(market: &str) -> f64 {
    if market == "KR" { 0.0025 } else { 0.0005 }
}

fn is_end() -> NaiveDate {
    NaiveDate::from_ymd_opt(2022, 12, 31).unwrap()
}

/// Final 0..1 signal, after checking that cutting history never changes past values.
pub fn signal_checked(sig: &Node, b: &Bars) -> Result<Vec<f64>> {
    let full = finalize(&eval(sig, b)?);
    for c in [0.5, 0.8] {
        let k = (b.len() as f64 * c) as usize;
        let part = finalize(&eval(sig, &b.head(k))?);
        if full[..k].iter().zip(&part).any(|(a, b)| (a - b).abs() > 1e-9) {
            bail!("signal at t uses data after t (cut {c})");
        }
    }
    Ok(full)
}

pub fn asset_returns(close: &[f64], pos: &[f64], cost: f64) -> Vec<f64> {
    let mut prev = 0.0;
    (0..close.len())
        .map(|t| {
            let (p, r) = if t == 0 { (0.0, 0.0) } else { (pos[t - 1], close[t] / close[t - 1] - 1.0) };
            let turnover = (p - prev).abs();
            prev = p;
            p * r - turnover * cost
        })
        .collect()
}

#[derive(Serialize, Debug, Default)]
pub struct Metrics {
    pub cagr: f64,
    pub sharpe: f64,
    pub mdd: f64,
    pub total: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub win_rate: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exposure: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub excess_cagr: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bh_cagr: Option<f64>,
}

fn round4(x: f64) -> f64 {
    (x * 1e4).round() / 1e4
}

fn finite(x: f64, what: &str) -> Result<f64> {
    if !x.is_finite() {
        bail!("{what} is not finite ({x})");
    }
    Ok(round4(x))
}

pub fn metrics(r: &[f64], expo: Option<&[f64]>) -> Result<Metrics> {
    if r.len() < 2 {
        bail!("not enough data for metrics ({} bars)", r.len());
    }
    let n = r.len() as f64;
    let mut eq = 1.0;
    let (mut peak, mut mdd) = (1.0_f64, 0.0_f64);
    for x in r {
        eq *= 1.0 + x;
        peak = peak.max(eq);
        mdd = mdd.min(eq / peak - 1.0);
    }
    let mean = r.iter().sum::<f64>() / n;
    let sd = (r.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / (n - 1.0)).sqrt();
    let mut m = Metrics {
        cagr: finite(eq.powf(252.0 / n) - 1.0, "cagr")?,
        sharpe: finite(if sd > 0.0 { mean / sd * 252f64.sqrt() } else { 0.0 }, "sharpe")?,
        mdd: finite(mdd, "mdd")?,
        total: finite(eq - 1.0, "total")?,
        ..Default::default()
    };
    if let Some(e) = expo {
        let active: Vec<f64> = r.iter().zip(e).filter(|(_, e)| **e > 0.0).map(|(r, _)| *r).collect();
        let win = if active.is_empty() {
            0.0
        } else {
            active.iter().filter(|x| **x > 0.0).count() as f64 / active.len() as f64
        };
        m.win_rate = Some(finite(win, "win_rate")?);
        m.exposure = Some(finite(e.iter().sum::<f64>() / n, "exposure")?);
    }
    Ok(m)
}

#[derive(Serialize, Debug)]
pub struct Split {
    pub is: Metrics,
    pub oos: Metrics,
}

#[derive(Serialize, Debug)]
pub struct Curve {
    pub dates: Vec<String>,
    pub strategy: Vec<f64>,
    pub buy_hold: Vec<f64>,
}

pub struct MarketResult {
    pub metrics: Split,
    pub curve: Curve,
}

/// Sunday that ends the week of `d` (pandas resample("W") label).
fn week_end(d: NaiveDate) -> NaiveDate {
    d + Days::new(6 - d.weekday().num_days_from_monday() as u64)
}

pub fn run_market(sig: &Node, data: &[(String, Bars)], market: &str) -> Result<MarketResult> {
    let c = cost(market);
    // per asset: (date, strategy return, buy&hold return, position held)
    type Row = (NaiveDate, f64, Option<f64>, Option<f64>);
    let per_asset: Vec<Vec<Row>> = data
        .par_iter()
        .map(|(t, b)| -> Result<Vec<Row>> {
            let pos = signal_checked(sig, b).map_err(|e| e.context(format!("ticker {t}")))?;
            let s = asset_returns(&b.close, &pos, c);
            Ok((0..b.len())
                .map(|i| {
                    let (bh, held) =
                        if i == 0 { (None, None) } else { (Some(b.close[i] / b.close[i - 1] - 1.0), Some(pos[i - 1])) };
                    (b.dates[i], s[i], bh, held)
                })
                .collect())
        })
        .collect::<Result<_>>()?;

    // equal-weight mean across assets that have a value on each date
    let mut acc: BTreeMap<NaiveDate, [f64; 6]> = BTreeMap::new();
    for (d, s, bh, held) in per_asset.into_iter().flatten() {
        let a = acc.entry(d).or_default();
        a[0] += s;
        a[1] += 1.0;
        if let Some(x) = bh {
            a[2] += x;
            a[3] += 1.0;
        }
        if let Some(x) = held {
            a[4] += x;
            a[5] += 1.0;
        }
    }
    let avg = |sum: f64, n: f64| if n > 0.0 { sum / n } else { 0.0 };
    let dates: Vec<NaiveDate> = acc.keys().copied().collect();
    let s: Vec<f64> = acc.values().map(|a| a[0] / a[1]).collect();
    let b: Vec<f64> = acc.values().map(|a| avg(a[2], a[3])).collect();
    let e: Vec<f64> = acc.values().map(|a| avg(a[4], a[5])).collect();

    let split = |lo: bool| -> Result<Metrics> {
        let idx: Vec<usize> = (0..dates.len()).filter(|&i| (dates[i] <= is_end()) == lo || dates[i] == is_end()).collect();
        let pick = |v: &[f64]| idx.iter().map(|&i| v[i]).collect::<Vec<f64>>();
        let mut ms = metrics(&pick(&s), Some(&pick(&e)))?;
        let mb = metrics(&pick(&b), None)?;
        ms.excess_cagr = Some(round4(ms.cagr - mb.cagr));
        ms.bh_cagr = Some(mb.cagr);
        Ok(ms)
    };
    let metrics = Split { is: split(true)?, oos: split(false)? };

    let mut weeks: BTreeMap<NaiveDate, (f64, f64)> = BTreeMap::new();
    let (mut es, mut eb) = (1.0, 1.0);
    for i in 0..dates.len() {
        es *= 1.0 + s[i];
        eb *= 1.0 + b[i];
        weeks.insert(week_end(dates[i]), (round4(es), round4(eb)));
    }
    let curve = Curve {
        dates: weeks.keys().map(|d| d.to_string()).collect(),
        strategy: weeks.values().map(|v| v.0).collect(),
        buy_hold: weeks.values().map(|v| v.1).collect(),
    };
    if curve.strategy.iter().chain(&curve.buy_hold).any(|x| !x.is_finite()) {
        bail!("equity curve has non-finite values");
    }
    Ok(MarketResult { metrics, curve })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::expr::compile;

    #[test]
    fn always_long_equals_buy_hold_minus_one_entry_cost() {
        let close: Vec<f64> = (0..50).map(|i| 100.0 + (i as f64 * 0.7).sin() * 5.0).collect();
        let r = asset_returns(&close, &vec![1.0; close.len()], 0.01);
        assert_eq!(r[0], 0.0);
        assert!((r[1] - (close[1] / close[0] - 1.0 - 0.01)).abs() < 1e-12);
        for t in 2..close.len() {
            assert!((r[t] - (close[t] / close[t - 1] - 1.0)).abs() < 1e-12);
        }
    }

    #[test]
    fn position_applies_next_bar() {
        // flat until the signal at bar 1, so only bar 2's return counts
        let close = [100.0, 100.0, 110.0, 110.0];
        let r = asset_returns(&close, &[0.0, 1.0, 1.0, 1.0], 0.0);
        let want = [0.0, 0.0, 0.1, 0.0];
        assert!(r.iter().zip(want).all(|(a, b)| (a - b).abs() < 1e-12), "{r:?}");
    }

    #[test]
    fn checked_signal_passes_for_dsl() {
        let b = Bars::from_close((0..300).map(|i| 100.0 + (i as f64 / 7.0).sin()).collect());
        let sig = compile("sma(close, 20) < close", &|_| bail!("no refs")).unwrap();
        assert_eq!(signal_checked(&sig, &b).unwrap().len(), 300);
    }

    #[test]
    fn week_label_is_sunday() {
        let wed = NaiveDate::from_ymd_opt(2026, 11, 4).unwrap();
        assert_eq!(week_end(wed).to_string(), "2026-11-08");
        let sun = NaiveDate::from_ymd_opt(2026, 11, 8).unwrap();
        assert_eq!(week_end(sun), sun);
    }
}
