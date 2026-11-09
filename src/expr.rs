//! Strategy signal DSL: `sma(close, 50) > sma(close, 200)`.
//!
//! There is no operator that reads a later bar, so a signal at bar t can only
//! depend on bars <= t. Agents must not edit this file; ask for new functions
//! in a result's lesson instead.

use anyhow::{Result, anyhow, bail};

use crate::data::Bars;

#[derive(Debug, Clone)]
pub enum Node {
    Num(f64),
    Str(String),
    Var(String),
    Call(String, Vec<Node>),
    Bin(String, Box<Node>, Box<Node>),
    Not(Box<Node>),
    Neg(Box<Node>),
    /// A resolved `ref("<id>")`: another strategy's final 0..1 signal.
    Signal(Box<Node>),
}

#[derive(Debug, Clone, PartialEq)]
enum Tok {
    Num(f64),
    Str(String),
    Ident(String),
    Op(String),
    LParen,
    RParen,
    Comma,
}

fn tokenize(s: &str) -> Result<Vec<Tok>> {
    let cs: Vec<char> = s.chars().collect();
    let (mut i, mut out) = (0, vec![]);
    while i < cs.len() {
        let c = cs[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }
        if c.is_ascii_digit() || c == '.' {
            let st = i;
            while i < cs.len() && (cs[i].is_ascii_digit() || cs[i] == '.') {
                i += 1;
            }
            let t: String = cs[st..i].iter().collect();
            out.push(Tok::Num(t.parse().map_err(|_| anyhow!("bad number '{t}'"))?));
            continue;
        }
        if c.is_ascii_alphabetic() || c == '_' {
            let st = i;
            while i < cs.len() && (cs[i].is_ascii_alphanumeric() || cs[i] == '_') {
                i += 1;
            }
            out.push(Tok::Ident(cs[st..i].iter().collect()));
            continue;
        }
        if c == '"' {
            let st = i + 1;
            i += 1;
            while i < cs.len() && cs[i] != '"' {
                i += 1;
            }
            if i >= cs.len() {
                bail!("unterminated string");
            }
            out.push(Tok::Str(cs[st..i].iter().collect()));
            i += 1;
            continue;
        }
        match c {
            '(' => out.push(Tok::LParen),
            ')' => out.push(Tok::RParen),
            ',' => out.push(Tok::Comma),
            '<' | '>' | '=' | '!' => {
                if cs.get(i + 1) == Some(&'=') {
                    out.push(Tok::Op(format!("{c}=")));
                    i += 2;
                    continue;
                }
                if c == '=' || c == '!' {
                    bail!("unexpected '{c}' (use == or !=, and `not` for negation)");
                }
                out.push(Tok::Op(c.to_string()));
            }
            '+' | '-' | '*' | '/' => out.push(Tok::Op(c.to_string())),
            _ => bail!("unexpected character '{c}'"),
        }
        i += 1;
    }
    Ok(out)
}

struct Parser {
    t: Vec<Tok>,
    i: usize,
}

impl Parser {
    fn peek(&self) -> Option<&Tok> {
        self.t.get(self.i)
    }
    fn kw(&mut self, k: &str) -> bool {
        let hit = matches!(self.peek(), Some(Tok::Ident(s)) if s == k);
        self.i += hit as usize;
        hit
    }
    fn op(&mut self, ops: &[&str]) -> Option<String> {
        match self.peek() {
            Some(Tok::Op(o)) if ops.contains(&o.as_str()) => {
                let o = o.clone();
                self.i += 1;
                Some(o)
            }
            _ => None,
        }
    }
    fn bin(op: impl Into<String>, l: Node, r: Node) -> Node {
        Node::Bin(op.into(), Box::new(l), Box::new(r))
    }
    fn or(&mut self) -> Result<Node> {
        let mut l = self.and()?;
        while self.kw("or") {
            l = Self::bin("or", l, self.and()?);
        }
        Ok(l)
    }
    fn and(&mut self) -> Result<Node> {
        let mut l = self.not()?;
        while self.kw("and") {
            l = Self::bin("and", l, self.not()?);
        }
        Ok(l)
    }
    fn not(&mut self) -> Result<Node> {
        if self.kw("not") {
            return Ok(Node::Not(Box::new(self.not()?)));
        }
        let l = self.add()?;
        match self.op(&["<", ">", "<=", ">=", "==", "!="]) {
            Some(o) => Ok(Self::bin(o, l, self.add()?)),
            None => Ok(l),
        }
    }
    fn add(&mut self) -> Result<Node> {
        let mut l = self.mul()?;
        while let Some(o) = self.op(&["+", "-"]) {
            l = Self::bin(o, l, self.mul()?);
        }
        Ok(l)
    }
    fn mul(&mut self) -> Result<Node> {
        let mut l = self.unary()?;
        while let Some(o) = self.op(&["*", "/"]) {
            l = Self::bin(o, l, self.unary()?);
        }
        Ok(l)
    }
    fn unary(&mut self) -> Result<Node> {
        if self.op(&["-"]).is_some() {
            return Ok(Node::Neg(Box::new(self.unary()?)));
        }
        self.atom()
    }
    fn close(&mut self) -> Result<()> {
        if self.peek() != Some(&Tok::RParen) {
            bail!("expected ')'");
        }
        self.i += 1;
        Ok(())
    }
    fn atom(&mut self) -> Result<Node> {
        let t = self.peek().cloned();
        self.i += 1;
        match t {
            Some(Tok::Num(x)) => Ok(Node::Num(x)),
            Some(Tok::Str(s)) => Ok(Node::Str(s)),
            Some(Tok::LParen) => {
                let e = self.or()?;
                self.close()?;
                Ok(e)
            }
            Some(Tok::Ident(name)) if self.peek() == Some(&Tok::LParen) => {
                self.i += 1;
                let mut args = vec![];
                if self.peek() != Some(&Tok::RParen) {
                    loop {
                        args.push(self.or()?);
                        if self.peek() != Some(&Tok::Comma) {
                            break;
                        }
                        self.i += 1;
                    }
                }
                self.close()?;
                Ok(Node::Call(name, args))
            }
            Some(Tok::Ident(name)) => Ok(Node::Var(name)),
            Some(t) => bail!("unexpected {t:?}"),
            None => bail!("unexpected end of expression"),
        }
    }
}

pub fn parse(src: &str) -> Result<Node> {
    let mut p = Parser { t: tokenize(src)?, i: 0 };
    let n = p.or()?;
    if p.i < p.t.len() {
        bail!("unexpected {:?} after a complete expression", p.t[p.i]);
    }
    Ok(n)
}

/// Parse and inline every `ref("<id>")` using `load(id) -> signal source`.
pub fn compile(src: &str, load: &dyn Fn(&str) -> Result<String>) -> Result<Node> {
    resolve(parse(src)?, load, 0)
}

fn resolve(n: Node, load: &dyn Fn(&str) -> Result<String>, depth: usize) -> Result<Node> {
    let r = |n: Box<Node>| resolve(*n, load, depth).map(Box::new);
    Ok(match n {
        Node::Call(f, args) if f == "ref" => {
            if depth >= 8 {
                bail!("ref() nested too deep (cycle?)");
            }
            let [Node::Str(id)] = args.as_slice() else {
                bail!("ref() takes one string id, e.g. ref(\"2026-11-09_sma_cross\")");
            };
            Node::Signal(Box::new(resolve(parse(&load(id)?)?, load, depth + 1)?))
        }
        Node::Call(f, args) => Node::Call(
            f,
            args.into_iter().map(|a| resolve(a, load, depth)).collect::<Result<_>>()?,
        ),
        Node::Bin(o, a, b) => Node::Bin(o, r(a)?, r(b)?),
        Node::Not(a) => Node::Not(r(a)?),
        Node::Neg(a) => Node::Neg(r(a)?),
        other => other,
    })
}

fn truthy(x: f64) -> bool {
    x > 0.0 // NaN is false
}

fn b2f(b: bool) -> f64 {
    b as u8 as f64
}

/// NaN -> 0, then clip to 0..1. This is the position the engine trades.
pub fn finalize(v: &[f64]) -> Vec<f64> {
    v.iter().map(|&x| if x.is_nan() { 0.0 } else { x.clamp(0.0, 1.0) }).collect()
}

pub fn eval(n: &Node, b: &Bars) -> Result<Vec<f64>> {
    let len = b.len();
    Ok(match n {
        Node::Num(x) => vec![*x; len],
        Node::Str(s) => bail!("unexpected string \"{s}\" (strings are only for ref)"),
        Node::Var(v) => b
            .col(v)
            .ok_or_else(|| anyhow!("unknown series '{v}' (use open, high, low, close, volume)"))?
            .to_vec(),
        Node::Neg(a) => eval(a, b)?.into_iter().map(|x| -x).collect(),
        Node::Not(a) => eval(a, b)?.into_iter().map(|x| b2f(!truthy(x))).collect(),
        Node::Signal(a) => finalize(&eval(a, b)?),
        Node::Bin(op, l, r) => {
            let (l, r) = (eval(l, b)?, eval(r, b)?);
            let f: fn(f64, f64) -> f64 = match op.as_str() {
                "+" => |a, b| a + b,
                "-" => |a, b| a - b,
                "*" => |a, b| a * b,
                "/" => |a, b| a / b,
                "<" => |a, b| b2f(a < b),
                ">" => |a, b| b2f(a > b),
                "<=" => |a, b| b2f(a <= b),
                ">=" => |a, b| b2f(a >= b),
                "==" => |a, b| b2f(a == b),
                "!=" => |a, b| b2f(a != b),
                "and" => |a, b| b2f(truthy(a) && truthy(b)),
                "or" => |a, b| b2f(truthy(a) || truthy(b)),
                _ => unreachable!("parser only emits known ops"),
            };
            l.iter().zip(&r).map(|(&a, &b)| f(a, b)).collect()
        }
        Node::Call(f, args) => call(f, args, b)?,
    })
}

fn call(f: &str, args: &[Node], b: &Bars) -> Result<Vec<f64>> {
    let want = match f {
        "sma" | "ema" | "std" | "rsi" | "max" | "min" | "lag" | "pct" | "latch" | "hold" => 2,
        "clip" => 3,
        _ => bail!(
            "unknown function '{f}' (available: sma ema std rsi max min lag pct latch hold clip ref)"
        ),
    };
    if args.len() != want {
        bail!("{f}() takes {want} arguments, got {}", args.len());
    }
    let s = |i: usize| eval(&args[i], b);
    let win = || -> Result<usize> {
        match args[1] {
            Node::Num(x) if x >= 1.0 && x.fract() == 0.0 => Ok(x as usize),
            _ => bail!("{f}(): 2nd argument must be a whole number >= 1"),
        }
    };
    Ok(match f {
        "sma" => rolling(&s(0)?, win()?, |w| w.iter().sum::<f64>() / w.len() as f64),
        "std" => {
            let n = win()?;
            if n < 2 {
                bail!("std(): window must be >= 2");
            }
            rolling(&s(0)?, n, |w| {
                let m = w.iter().sum::<f64>() / w.len() as f64;
                (w.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (w.len() - 1) as f64).sqrt()
            })
        }
        "max" => rolling(&s(0)?, win()?, |w| w.iter().copied().fold(f64::MIN, f64::max)),
        "min" => rolling(&s(0)?, win()?, |w| w.iter().copied().fold(f64::MAX, f64::min)),
        "ema" => ema(&s(0)?, win()?),
        "rsi" => rsi(&s(0)?, win()?),
        "lag" => lag(&s(0)?, win()?),
        "pct" => {
            let x = s(0)?;
            let l = lag(&x, win()?);
            x.iter().zip(&l).map(|(a, b)| a / b - 1.0).collect()
        }
        "latch" => {
            let (en, ex) = (s(0)?, s(1)?);
            let mut on = false;
            en.iter()
                .zip(&ex)
                .map(|(&e, &x)| {
                    if !on && truthy(e) {
                        on = true;
                    } else if on && truthy(x) {
                        on = false;
                    }
                    b2f(on)
                })
                .collect()
        }
        "hold" => {
            let n = win()?;
            let mut left = 0;
            s(0)?
                .iter()
                .map(|&c| {
                    if truthy(c) {
                        left = n;
                    }
                    if left > 0 {
                        left -= 1;
                        1.0
                    } else {
                        0.0
                    }
                })
                .collect()
        }
        "clip" => {
            let (x, lo, hi) = (s(0)?, s(1)?, s(2)?);
            (0..x.len())
                .map(|i| if x[i].is_nan() { f64::NAN } else { x[i].max(lo[i]).min(hi[i]) })
                .collect()
        }
        _ => unreachable!(),
    })
}

// ponytail: O(len * window) rolling; switch to sliding sums / monotonic deque if sweeps get slow.
fn rolling(x: &[f64], n: usize, f: impl Fn(&[f64]) -> f64) -> Vec<f64> {
    (0..x.len())
        .map(|t| {
            if t + 1 < n {
                return f64::NAN;
            }
            let w = &x[t + 1 - n..=t];
            if w.iter().any(|v| v.is_nan()) { f64::NAN } else { f(w) }
        })
        .collect()
}

/// EMA with alpha = 2/(n+1), seeded at the first value, NaN during the first n-1 bars.
fn ema(x: &[f64], n: usize) -> Vec<f64> {
    let a = 2.0 / (n as f64 + 1.0);
    let (mut e, mut cnt) = (f64::NAN, 0);
    x.iter()
        .map(|&v| {
            if v.is_nan() {
                return f64::NAN;
            }
            e = if e.is_nan() { v } else { a * v + (1.0 - a) * e };
            cnt += 1;
            if cnt >= n { e } else { f64::NAN }
        })
        .collect()
}

/// Wilder RSI, seeded with the simple average of the first n changes.
fn rsi(x: &[f64], n: usize) -> Vec<f64> {
    let nf = n as f64;
    let mut out = vec![f64::NAN; x.len()];
    let (mut g, mut l, mut cnt) = (0.0, 0.0, 0);
    for t in 1..x.len() {
        let d = x[t] - x[t - 1];
        if d.is_nan() {
            continue;
        }
        let (up, dn) = (d.max(0.0), (-d).max(0.0));
        cnt += 1;
        if cnt <= n {
            g += up / nf;
            l += dn / nf;
        } else {
            g = (g * (nf - 1.0) + up) / nf;
            l = (l * (nf - 1.0) + dn) / nf;
        }
        if cnt >= n {
            out[t] = if l == 0.0 { 100.0 } else { 100.0 - 100.0 / (1.0 + g / l) };
        }
    }
    out
}

fn lag(x: &[f64], k: usize) -> Vec<f64> {
    (0..x.len()).map(|t| if t >= k { x[t - k] } else { f64::NAN }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bars(close: &[f64]) -> Bars {
        Bars::from_close(close.to_vec())
    }
    fn run(src: &str, close: &[f64]) -> Result<Vec<f64>> {
        eval(&compile(src, &|_| bail!("no refs"))?, &bars(close))
    }

    #[test]
    fn precedence_and_logic() {
        assert_eq!(run("1 + 2 * 3 > 6 and not 0", &[1.0]).unwrap(), vec![1.0]);
        assert_eq!(run("-(1 - 3) == 2 or 0", &[1.0]).unwrap(), vec![1.0]);
    }

    #[test]
    fn sma_latch_hold() {
        let c = [1.0, 2.0, 3.0, 4.0, 5.0];
        let s = run("sma(close, 2)", &c).unwrap();
        assert!(s[0].is_nan());
        assert_eq!(&s[1..], &[1.5, 2.5, 3.5, 4.5]);
        // entry when close == 1 or 5, exit when close == 3
        assert_eq!(
            run("latch(close == 1 or close == 5, close == 3)", &c).unwrap(),
            vec![1.0, 1.0, 0.0, 0.0, 1.0]
        );
        let c = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0];
        assert_eq!(run("hold(close, 2)", &c).unwrap(), vec![1.0, 1.0, 0.0, 0.0, 0.0, 1.0]);
    }

    #[test]
    fn rejects_bad_input() {
        for bad in [
            "lag(close, 0)",
            "lag(close, -1)",
            "sma(close, 2.5)",
            "nope(close)",
            "sma(close)",
            "foo > 1",
            "close = 1",
            "(close",
            "close close",
        ] {
            assert!(run(bad, &[1.0, 2.0]).is_err(), "should reject: {bad}");
        }
    }

    #[test]
    fn ref_inlines_and_detects_cycles() {
        let n = compile("ref(\"a\")", &|_| Ok("close > 1".into())).unwrap();
        assert_eq!(eval(&n, &bars(&[1.0, 2.0])).unwrap(), vec![0.0, 1.0]);
        assert!(compile("ref(\"a\")", &|_| Ok("ref(\"a\")".into())).is_err());
    }

    #[test]
    fn no_function_reads_future_bars() {
        // deterministic pseudo-random walk
        let mut x = 100.0;
        let close: Vec<f64> = (0..400u64)
            .map(|i| {
                x *= 1.0 + ((i * 7919 % 101) as f64 - 50.0) / 2500.0;
                x
            })
            .collect();
        let src = "latch(rsi(close, 14) < 30, rsi(close, 14) > 70) + hold(pct(close, 5) > 0, 3) \
                   + clip(ema(close, 10) - sma(close, 20), 0, 1) + std(close, 20) + max(high, 55) \
                   - min(low, 20) + lag(close, 3)";
        let full = run(src, &close).unwrap();
        for k in [50, 200, 399] {
            let part = run(src, &close[..k]).unwrap();
            for t in 0..k {
                assert!(
                    (full[t].is_nan() && part[t].is_nan()) || (full[t] - part[t]).abs() < 1e-9,
                    "bar {t} changed when history was cut at {k}"
                );
            }
        }
    }
}
