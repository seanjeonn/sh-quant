mod backtest;
mod data;
mod expr;
mod news;

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::Deserialize;
use serde_json::{Value, json};

const USAGE: &str = "usage:
  sh-quant run strategies/<id>.toml             backtest + record
  sh-quant lesson <id> \"<one line>\"             attach a lesson to a result
  sh-quant fail strategies/<id>.toml \"<why>\"    record a failed attempt
  sh-quant news                                 collect today's headlines";

#[derive(Deserialize)]
struct Strategy {
    name: String,
    hypothesis: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    parents: Vec<String>,
    #[serde(default = "agent")]
    source: String,
    signal: String,
}

fn agent() -> String {
    "agent".into()
}

fn root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
}

fn results_dir() -> PathBuf {
    root().join("results")
}

fn read_strategy(path: &Path) -> Result<Strategy> {
    let text = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let s: Strategy = toml::from_str(&text).with_context(|| format!("parse {}", path.display()))?;
    if s.name.trim().is_empty() || s.hypothesis.trim().is_empty() {
        bail!("name and hypothesis are required");
    }
    Ok(s)
}

fn compile(s: &Strategy) -> Result<expr::Node> {
    expr::compile(&s.signal, &|id| {
        Ok(read_strategy(&root().join("strategies").join(format!("{id}.toml")))
            .with_context(|| format!("ref(\"{id}\")"))?
            .signal)
    })
    .context("signal")
}

fn id_of(path: &Path) -> Result<String> {
    Ok(path.file_stem().and_then(|s| s.to_str()).context("bad strategy path")?.to_string())
}

fn base_entry(id: &str, s: Option<&Strategy>) -> Value {
    let date = if id.len() >= 10 && id[..4].bytes().all(|c| c.is_ascii_digit()) {
        id[..10].to_string()
    } else {
        chrono::Local::now().date_naive().to_string()
    };
    json!({
        "id": id,
        "date": date,
        "name": s.map_or(id, |s| &s.name),
        "hypothesis": s.map_or("", |s| &s.hypothesis),
        "tags": s.map_or(vec![], |s| s.tags.clone()),
        "parents": s.map_or(vec![], |s| s.parents.clone()),
        "source": s.map_or("agent", |s| &s.source),
        "lesson": null,
    })
}

fn load_index() -> Result<Vec<Value>> {
    let p = results_dir().join("index.json");
    if !p.exists() {
        return Ok(vec![]);
    }
    Ok(serde_json::from_str(&fs::read_to_string(p)?)?)
}

fn save(entry: Value, detail: Option<Value>) -> Result<()> {
    let dir = results_dir();
    fs::create_dir_all(&dir)?;
    let id = entry["id"].as_str().context("entry without id")?.to_string();
    let mut idx: Vec<Value> = load_index()?.into_iter().filter(|e| e["id"] != id.as_str()).collect();
    idx.push(entry);
    idx.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
    fs::write(dir.join("index.json"), serde_json::to_string_pretty(&idx)?)?;
    if let Some(d) = detail {
        fs::write(dir.join(format!("{id}.json")), serde_json::to_string(&d)?)?;
    }
    Ok(())
}

fn cmd_run(path: &Path) -> Result<()> {
    let id = id_of(path)?;
    let s = read_strategy(path)?;
    let sig = compile(&s)?;
    let mut entry = base_entry(&id, Some(&s));
    let (mut markets, mut curves) = (json!({}), json!({}));
    for m in ["US", "KR"] {
        let data = data::load(m)?;
        if data.is_empty() {
            bail!("no data for {m}");
        }
        let r = backtest::run_market(&sig, &data, m).with_context(|| format!("market {m}"))?;
        markets[m] = serde_json::to_value(&r.metrics)?;
        curves[m] = serde_json::to_value(&r.curve)?;
    }
    if let Some(old) = load_index()?.into_iter().find(|e| e["id"] == id.as_str()) {
        entry["lesson"] = old["lesson"].clone();
    }
    entry["status"] = json!("ok");
    entry["markets"] = markets.clone();
    save(entry, Some(json!({ "id": id, "curves": curves })))?;
    println!("{}", serde_json::to_string_pretty(&markets)?);
    Ok(())
}

fn cmd_fail(path: &Path, why: &str) -> Result<()> {
    let id = id_of(path)?;
    let s = read_strategy(path).ok();
    let mut entry = base_entry(&id, s.as_ref());
    entry["status"] = json!("failed");
    entry["error"] = json!(why);
    entry["markets"] = json!({});
    save(entry, None)
}

fn cmd_lesson(id: &str, text: &str) -> Result<()> {
    let mut e = load_index()?
        .into_iter()
        .find(|e| e["id"] == id)
        .with_context(|| format!("no result with id {id}"))?;
    e["lesson"] = json!(text);
    save(e, None)
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let a: Vec<&str> = a.iter().map(String::as_str).collect();
    let r = match a.as_slice() {
        ["run", p] => cmd_run(Path::new(p)),
        ["fail", p, why] => cmd_fail(Path::new(p), why),
        ["lesson", id, text] => cmd_lesson(id, text),
        ["news"] => news::collect(),
        _ => {
            eprintln!("{USAGE}");
            std::process::exit(2);
        }
    };
    if let Err(e) = r {
        eprintln!("error: {e:#}");
        std::process::exit(1);
    }
}
