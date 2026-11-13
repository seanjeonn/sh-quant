mod backtest;
mod data;
mod expr;
mod frozen;
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
  sh-quant news                                 collect today's headlines

Private offline mode (no network or fallback):
  sh-quant run strategies/<id>.toml --data-manifest ABS --output-dir ABS
  sh-quant fail strategies/<id>.toml \"<why>\" --output-dir ABS
  sh-quant lesson <id> \"<one line>\" --output-dir ABS

Frozen schema v2: complete adjusted Toss data, Asia/Seoul timezone, all
24 fixed-universe symbols; manifest and CSV SHA256 verified before/after run.
Input/output must be absolute, outside every git checkout, without symlinks.
Private dirs/files are enforced as 700/600. Metrics/curves stay in private
index.json/<id>.json; stdout contains status only. Private IDs cannot be reused.
lesson requires an existing private index entry. Writes are locked, fsynced,
and atomically renamed (index is the commit point). Crash orphans are not reused.
A crashed writer may leave .writer.lock: inspect it and remove manually only
after confirming no writer is alive. Private errors suppress provider content.";

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
    Ok(path
        .file_stem()
        .and_then(|s| s.to_str())
        .context("bad strategy path")?
        .to_string())
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

fn cmd_frozen_run(path: &Path, manifest: &Path, output: &Path) -> Result<()> {
    // Validate destinations before touching data; lock spans computation and commit.
    frozen::private_path(manifest)?;
    let mut store = frozen::Store::open(output)?;
    let id = id_of(path)?;
    store.ensure_new(&id)?;
    let s = read_strategy(path)?;
    let sig = compile(&s)?;
    let input = frozen::Frozen::load(manifest)?;
    input.verify()?;
    let (mut markets, mut curves) = (json!({}), json!({}));
    for m in ["US", "KR"] {
        let r = backtest::run_market(&sig, &input.market(m), m)?;
        markets[m] = serde_json::to_value(&r.metrics)?;
        curves[m] = serde_json::to_value(&r.curve)?;
    }
    input.verify()?;
    let mut entry = base_entry(&id, Some(&s));
    entry["status"] = json!("ok");
    entry["markets"] = markets;
    entry["data_provider"] = json!("toss");
    store.insert(entry, Some(json!({"id":id,"curves":curves})))?;
    println!("private result saved");
    Ok(())
}
fn cmd_private_fail(path: &Path, why: &str, output: &Path) -> Result<()> {
    let mut store = frozen::Store::open(output)?;
    let id = id_of(path)?;
    store.ensure_new(&id)?;
    let s = read_strategy(path).ok();
    let mut entry = base_entry(&id, s.as_ref());
    entry["status"] = json!("failed");
    entry["error"] = json!(why);
    entry["markets"] = json!({});
    store.insert(entry, None)?;
    println!("private failure saved");
    Ok(())
}
fn cmd_private_lesson(id: &str, text: &str, output: &Path) -> Result<()> {
    frozen::private_path(output)?;
    anyhow::ensure!(
        output.is_dir() && output.join("index.json").is_file(),
        "no existing private output"
    );
    frozen::Store::open(output)?.lesson(id, text)?;
    println!("private lesson saved");
    Ok(())
}

fn validate_cli(a: &[&str]) -> Result<()> {
    let positional = |s: &str| !s.starts_with("--");
    let valid = match a {
        ["run", p] => positional(p),
        ["fail" | "lesson", p, text] => positional(p) && !["--data-manifest", "--output-dir"].contains(text),
        ["news"] => true,
        ["run", p, "--data-manifest", m, "--output-dir", o] => {
            positional(p) && Path::new(m).is_absolute() && Path::new(o).is_absolute()
        }
        ["fail" | "lesson", p, text, "--output-dir", o] => {
            positional(p) && !["--data-manifest", "--output-dir"].contains(text) && Path::new(o).is_absolute()
        }
        _ => false,
    };
    anyhow::ensure!(valid, "{USAGE}");
    Ok(())
}

fn dispatch(a: &[&str]) -> Result<()> {
    validate_cli(a)?;
    match a {
        ["run", p, "--data-manifest", manifest, "--output-dir", output] => {
            cmd_frozen_run(Path::new(p), Path::new(manifest), Path::new(output))
        }
        ["fail", p, why, "--output-dir", output] => cmd_private_fail(Path::new(p), why, Path::new(output)),
        ["lesson", id, text, "--output-dir", output] => cmd_private_lesson(id, text, Path::new(output)),
        ["run", p] => cmd_run(Path::new(p)),
        ["fail", p, why] => cmd_fail(Path::new(p), why),
        ["lesson", id, text] => cmd_lesson(id, text),
        ["news"] => news::collect(),
        _ => bail!("{USAGE}"),
    }
}

#[cfg(test)]
mod cli_tests {
    use super::*;
    use frozen::tests::{Fixture, uncontended};
    #[test]
    fn private_diagnostics_never_echo_provider_content() {
        let e = anyhow::anyhow!("synthetic sensitive provider payload");
        assert_eq!(
            diagnostic(&["run", "x", "--data-manifest", "/input", "--output-dir", "/out"], &e),
            "error: private operation failed (details suppressed)"
        );
        assert_eq!(
            diagnostic(&["fail", "x", "why", "--output-dir", "/out"], &e),
            "error: private operation failed (details suppressed)"
        );
        assert!(diagnostic(&["run", "x"], &e).contains("synthetic sensitive provider payload"));
    }
    #[test]
    fn cli_rejects_invalid_combinations_before_side_effects() {
        for args in [
            vec![],
            vec!["run"],
            vec!["run", "--data-manifest"],
            vec!["run", "x", "--data-manifest", "/input"],
            vec!["run", "x", "--output-dir", "/out"],
            vec!["run", "x", "--data-manifest", "relative", "--output-dir", "/out"],
            vec!["run", "x", "--data-manifest", "/input", "--output-dir", "relative"],
            vec!["fail", "x", "--output-dir"],
            vec!["lesson", "x", "--output-dir"],
            vec!["news", "--output-dir", "/out"],
            vec![
                "run",
                "x",
                "--data-manifest",
                "/input",
                "--output-dir",
                "/out",
                "--output-dir",
                "/out",
            ],
            vec!["fail", "x", "why", "--data-manifest", "/input", "--output-dir", "/out"],
        ] {
            assert!(validate_cli(&args).is_err(), "accepted {args:?}");
        }
        for args in [
            vec!["run", "x"],
            vec!["fail", "x", "why"],
            vec!["lesson", "x", "text"],
            vec!["news"],
            vec!["run", "x", "--data-manifest", "/input", "--output-dir", "/out"],
            vec!["fail", "x", "why", "--output-dir", "/out"],
            vec!["lesson", "x", "text", "--output-dir", "/out"],
        ] {
            validate_cli(&args).unwrap();
        }
    }
    #[test]
    fn frozen_cli_run_fail_lesson_are_private_and_never_overwrite() {
        let f = Fixture::new();
        f.populate();
        let out = f.0.join("output");
        let strategy = f.0.join("synthetic-run.toml");
        fs::write(&strategy, "name='synthetic'\nhypothesis='synthetic only'\nsignal='1'\n").unwrap();
        let p = strategy.to_str().unwrap();
        let manifest = f.manifest();
        let m = manifest.to_str().unwrap();
        let o = out.to_str().unwrap();
        let public_before = fs::read(results_dir().join("index.json")).ok();
        dispatch(&["run", p, "--data-manifest", m, "--output-dir", o]).unwrap();
        let index: Value = serde_json::from_slice(&fs::read(out.join("index.json")).unwrap()).unwrap();
        assert_eq!(index[0]["status"], "ok");
        assert!(index[0]["markets"]["US"]["is"].is_object());
        assert!(out.join("synthetic-run.json").exists());
        // Each dispatch drops its Store. A parallel fork may still hold the
        // CLOEXEC descriptor until exec; retry only that structured lock error.
        let duplicate = uncontended(|| dispatch(&["run", p, "--data-manifest", m, "--output-dir", o]));
        assert_eq!(duplicate.unwrap_err().to_string(), "result id already exists");
        let duplicate = uncontended(|| dispatch(&["fail", p, "synthetic failure", "--output-dir", o]));
        assert_eq!(duplicate.unwrap_err().to_string(), "result id already exists");
        uncontended(|| dispatch(&["lesson", "synthetic-run", "synthetic lesson", "--output-dir", o]))
            .unwrap();
        let second = f.0.join("synthetic-fail.toml");
        uncontended(|| {
            dispatch(&["fail", second.to_str().unwrap(), "synthetic failure", "--output-dir", o])
        }).unwrap();
        let missing = uncontended(|| dispatch(&["lesson", "missing", "text", "--output-dir", o]));
        assert_eq!(missing.unwrap_err().to_string(), "no private result with id");
        assert_eq!(public_before, fs::read(results_dir().join("index.json")).ok());
        let nonexistent = f.0.join("absent");
        assert!(
            dispatch(&[
                "lesson",
                "missing",
                "text",
                "--output-dir",
                nonexistent.to_str().unwrap()
            ])
            .is_err()
        );
        assert!(!nonexistent.exists());
    }
}

fn diagnostic(a: &[&str], e: &anyhow::Error) -> String {
    if a.iter().any(|s| *s == "--data-manifest" || *s == "--output-dir") {
        "error: private operation failed (details suppressed)".into()
    } else {
        format!("error: {e:#}")
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let a: Vec<&str> = args.iter().map(String::as_str).collect();
    if validate_cli(&a).is_err() {
        eprintln!("{USAGE}");
        std::process::exit(2);
    }
    if let Err(e) = dispatch(&a) {
        eprintln!("{}", diagnostic(&a, &e));
        std::process::exit(1);
    }
}
