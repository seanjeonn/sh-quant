//! Private, offline frozen input and result storage (#26).

use crate::data::Bars;
use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};
fn strict_date(s: &str) -> Result<chrono::NaiveDate> {
    ensure!(
        s.len() == 10
            && s.bytes().enumerate().all(|(i, b)| if i == 4 || i == 7 {
                b == b'-'
            } else {
                b.is_ascii_digit()
            }),
        "invalid date"
    );
    s.parse().context("invalid date")
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
#[derive(Deserialize)]
struct Manifest {
    schema_version: u32,
    provider: String,
    adjusted: bool,
    timezone: String,
    cutoff_exclusive: String,
    prepared_at: String,
    status: String,
    entries: Vec<Entry>,
}
#[derive(Deserialize)]
struct UniverseManifest {
    universe: UniverseRef,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UniverseRef {
    path: String,
    sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Universe {
    schema_version: u32,
    universe_id: String,
    classification_as_of: String,
    point_in_time: bool,
    selection_policy: String,
    limitations: Vec<String>,
    instruments: Vec<Instrument>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Instrument {
    market: String,
    ticker: String,
    source_symbol: String,
    themes: Vec<String>,
}
fn slug(s: &str) -> bool {
    (1..=64).contains(&s.len())
        && s.as_bytes()[0].is_ascii_alphanumeric()
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}
fn identifier(market: &str, s: &str) -> bool {
    let alnum = |b: u8| b.is_ascii_uppercase() || b.is_ascii_digit();
    match market {
        "US" => {
            (1..=24).contains(&s.len())
                && alnum(s.as_bytes()[0])
                && s.bytes().all(|b| alnum(b) || b == b'.' || b == b'-')
        }
        "KR" => s.len() == 6 && s.bytes().all(alnum),
        _ => false,
    }
}
impl Universe {
    fn validate(&self) -> Result<()> {
        ensure!(
            self.schema_version == 1
                && !self.point_in_time
                && slug(&self.universe_id)
                && !self.selection_policy.trim().is_empty()
                && !self.limitations.is_empty()
                && self.limitations.iter().all(|s| !s.trim().is_empty()),
            "invalid universe metadata"
        );
        strict_date(&self.classification_as_of)?;
        ensure!(
            (1..=512).contains(&self.instruments.len()),
            "invalid universe size"
        );
        let mut identities = std::collections::BTreeSet::new();
        let mut sources = std::collections::BTreeSet::new();
        let mut markets = std::collections::BTreeSet::new();
        for i in &self.instruments {
            ensure!(
                identifier(&i.market, &i.ticker) && identifier(&i.market, &i.source_symbol),
                "invalid universe identifier"
            );
            ensure!(
                identities.insert((&i.market, &i.ticker))
                    && sources.insert((&i.market, &i.source_symbol)),
                "duplicate universe identity/source"
            );
            let tags: std::collections::BTreeSet<_> = i.themes.iter().collect();
            ensure!(
                !i.themes.is_empty()
                    && tags.len() == i.themes.len()
                    && i.themes.iter().all(|s| slug(s)),
                "invalid universe themes"
            );
            markets.insert(i.market.as_str());
        }
        ensure!(
            markets.contains("US") && markets.contains("KR"),
            "universe requires both markets"
        );
        Ok(())
    }
}
#[derive(Deserialize)]
struct Entry {
    market: String,
    ticker: String,
    source_symbol: Option<Value>,
    currency: String,
    session: String,
    path: String,
    sha256: String,
    rows: usize,
    first: String,
    last: String,
}
use std::os::unix::fs::{MetadataExt, PermissionsExt};

/// Reject symlinks (including ancestor aliases), traversal and any git worktree.
/// Check every lexical ancestor before chmod or writes; symlink aliases are
/// rejected rather than silently resolved into potentially public locations.
pub fn private_path(path: &Path) -> Result<()> {
    ensure!(path.is_absolute(), "private path must be absolute");
    let mut p = PathBuf::new();
    for c in path.components() {
        ensure!(
            !matches!(c, std::path::Component::ParentDir | std::path::Component::CurDir),
            "path traversal"
        );
        p.push(c);
        if let Ok(m) = fs::symlink_metadata(&p) {
            ensure!(!m.file_type().is_symlink(), "symlink prohibited");
        }
        ensure!(!p.join(".git").exists(), "private path inside git checkout");
    }
    // CARGO_MANIFEST_DIR also protects source archives without .git.
    ensure!(!path.starts_with(crate::root()), "private path inside source checkout");
    Ok(())
}
fn secure(path: &Path, dir: bool) -> Result<()> {
    private_path(path)?;
    let m = fs::symlink_metadata(path)?;
    ensure!(
        if dir { m.is_dir() } else { m.is_file() && m.nlink() == 1 },
        "invalid private file type"
    );
    let mode = if dir { 0o700 } else { 0o600 };
    fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    ensure!(
        fs::metadata(path)?.permissions().mode() & 0o7777 == mode,
        "private permissions"
    );
    Ok(())
}

pub struct Frozen {
    markets: BTreeMap<String, Vec<(String, Bars)>>,
    snapshot: Vec<(PathBuf, Vec<u8>)>,
}
impl Frozen {
    pub fn load(path: &Path) -> Result<Self> {
        private_path(path)?;
        let parent = path.parent().context("manifest parent")?;
        secure(parent, true)?;
        secure(path, false)?;
        let bytes = fs::read(path)?;
        let manifest: Manifest = serde_json::from_slice(&bytes)?;
        let mut snapshot = vec![(path.to_path_buf(), bytes)];
        ensure!(
            matches!(manifest.schema_version, 2 | 3)
                && manifest.provider == "toss"
                && manifest.adjusted
                && manifest.timezone == "Asia/Seoul"
                && manifest.status == "complete",
            "invalid manifest policy"
        );
        chrono::DateTime::parse_from_rfc3339(&manifest.prepared_at).context("invalid prepared_at")?;
        let cutoff = strict_date(&manifest.cutoff_exclusive)?;
        let catalog = if manifest.schema_version == 3 {
            // Parse the extension only for schema3; schema2 keeps ignoring it.
            let extension: UniverseManifest = serde_json::from_slice(&snapshot[0].1)?;
            let reference = extension.universe;
            ensure!(reference.path == "universe.json", "invalid universe path");
            let universe_path = parent.join(reference.path);
            secure(&universe_path, false)?;
            let bytes = fs::read(&universe_path)?;
            ensure!(
                reference.sha256.len() == 64
                    && reference.sha256.bytes().all(|b| b.is_ascii_hexdigit())
                    && digest(&bytes).eq_ignore_ascii_case(&reference.sha256),
                "universe hash mismatch"
            );
            let universe: Universe = serde_json::from_slice(&bytes)?;
            universe.validate()?;
            snapshot.push((universe_path, bytes));
            Some(universe.instruments)
        } else {
            None
        };
        let expected: std::collections::BTreeSet<_> = if let Some(instruments) = &catalog {
            instruments
                .iter()
                .map(|i| (i.market.clone(), i.ticker.clone()))
                .collect()
        } else {
            ["US", "KR"]
                .into_iter()
                .flat_map(|m| {
                    crate::data::universe(m)
                        .iter()
                        .map(move |t| (m.to_string(), t.to_string()))
                })
                .collect()
        };
        let mut seen = std::collections::BTreeSet::new();
        let mut paths = std::collections::BTreeSet::new();
        let mut markets: BTreeMap<String, Vec<(String, Bars)>> = BTreeMap::new();
        for e in manifest.entries {
            if let Some(instruments) = &catalog {
                let descriptor = instruments
                    .iter()
                    .find(|i| i.market == e.market && i.ticker == e.ticker)
                    .context("entry outside universe")?;
                ensure!(
                    e.source_symbol.as_ref().and_then(Value::as_str)
                        == Some(descriptor.source_symbol.as_str()),
                    "inconsistent source_symbol"
                );
            }
            ensure!(
                expected.contains(&(e.market.clone(), e.ticker.clone()))
                    && seen.insert((e.market.clone(), e.ticker.clone())),
                "invalid universe"
            );
            ensure!(
                (e.market == "US" && e.currency == "USD" && e.session == "US_REGULAR")
                    || (e.market == "KR" && e.currency == "KRW" && e.session == "KR_INTEGRATED"),
                "inconsistent currency/session"
            );
            ensure!(
                !e.path.is_empty()
                    && Path::new(&e.path)
                        .components()
                        .all(|c| matches!(c, std::path::Component::Normal(_))),
                "invalid CSV path"
            );
            let csv_path = parent.join(&e.path);
            ensure!(paths.insert(csv_path.clone()), "duplicate CSV path");
            for p in csv_path
                .parent()
                .context("CSV parent")?
                .ancestors()
                .take_while(|p| p.starts_with(parent))
            {
                secure(p, true)?;
            }
            secure(&csv_path, false)?;
            let bytes = fs::read(&csv_path)?;
            let text = std::str::from_utf8(&bytes).context("CSV encoding")?;
            ensure!(
                e.sha256.len() == 64
                    && e.sha256.bytes().all(|b| b.is_ascii_hexdigit())
                    && digest(text.as_bytes()).eq_ignore_ascii_case(&e.sha256),
                "CSV hash mismatch"
            );
            let mut b = Bars::default();
            let mut lines = text.lines();
            ensure!(lines.next() == Some("date,open,high,low,close,volume"), "CSV header");
            for line in lines {
                let f: Vec<_> = line.split(',').collect();
                ensure!(f.len() == 6, "CSV columns");
                let d = strict_date(f[0])?;
                ensure!(
                    d < cutoff && b.dates.last().is_none_or(|previous| *previous < d),
                    "CSV date order/cutoff"
                );
                let n: Vec<f64> = f[1..]
                    .iter()
                    .map(|x| x.parse::<f64>().context("CSV number"))
                    .collect::<Result<_>>()?;
                ensure!(
                    n.iter().all(|x| x.is_finite())
                        && n[..4].iter().all(|x| *x > 0.)
                        && n[4] >= 0.
                        && n[2] <= n[0]
                        && n[0] <= n[1]
                        && n[2] <= n[3]
                        && n[3] <= n[1],
                    "invalid OHLCV"
                );
                b.dates.push(d);
                b.open.push(n[0]);
                b.high.push(n[1]);
                b.low.push(n[2]);
                b.close.push(n[3]);
                b.volume.push(n[4]);
            }
            ensure!(
                b.len() > 0
                    && b.len() == e.rows
                    && b.dates.first() == Some(&strict_date(&e.first)?)
                    && b.dates.last() == Some(&strict_date(&e.last)?),
                "CSV coverage mismatch"
            );
            snapshot.push((csv_path, bytes));
            markets.entry(e.market).or_default().push((e.ticker, b));
        }
        ensure!(seen == expected, "incomplete universe");
        let input = Self { markets, snapshot };
        input.verify()?;
        Ok(input)
    }
    pub fn market(&self, m: &str) -> Vec<(String, Bars)> {
        self.markets[m].clone()
    }
    pub fn verify(&self) -> Result<()> {
        for (path, original) in &self.snapshot {
            secure(path, false)?;
            let bytes = fs::read(path)?;
            ensure!(
                bytes == *original && digest(&bytes) == digest(original),
                "frozen input changed"
            );
        }
        Ok(())
    }
}

use serde_json::{Value, json};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};

/// A nonblocking exclusive kernel lock on a stable .writer.lock sidecar (#30).
/// Keep the file descriptor alive for the entire Store lifetime; closing it
/// (including process death) releases the lock. Never unlink the sidecar: a
/// replacement inode could otherwise admit a second writer. Unix File opens
/// are close-on-exec; fork-only descendants must not retain the descriptor.
/// Crash-left .pending files remain fail-closed/no-overwrite. The runner repairs
/// by using distinct attempt directories, not deleting unknown artifacts.
pub struct Store {
    dir: PathBuf,
    _lock: fs::File,
}
impl Store {
    pub fn open(dir: &Path) -> Result<Self> {
        private_path(dir)?;
        if !dir.exists() {
            let mut missing = vec![];
            let mut p = dir;
            while !p.exists() {
                missing.push(p.to_path_buf());
                p = p.parent().context("output parent")?;
            }
            for p in missing.iter().rev() {
                fs::DirBuilder::new().mode(0o700).create(p)?;
                secure(p, true)?;
            }
        }
        secure(dir, true)?;
        let lock_path = dir.join(".writer.lock");
        let lock = match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&lock_path)
        {
            Ok(lock) => lock,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                // Validate before opening: reject symlinks, hardlinks and
                // non-regular files (a FIFO must not block this open).
                secure(&lock_path, false)?;
                fs::OpenOptions::new().write(true).open(&lock_path)?
            }
            Err(e) => return Err(e).context("private output lock open"),
        };
        let metadata = lock.metadata()?;
        ensure!(
            metadata.is_file() && metadata.nlink() == 1,
            "invalid private lock type"
        );
        let named = fs::symlink_metadata(&lock_path)?;
        ensure!(
            named.is_file()
                && named.nlink() == 1
                && (named.dev(), named.ino()) == (metadata.dev(), metadata.ino()),
            "private lock inode changed"
        );
        lock.set_permissions(fs::Permissions::from_mode(0o600))?;
        lock.try_lock().context("private output locked")?;
        let store = Self {
            dir: dir.to_path_buf(),
            _lock: lock,
        };
        for e in fs::read_dir(dir)? {
            secure(&e?.path(), false)?;
        }
        store.index()?;
        Ok(store)
    }
    pub fn ensure_new(&self, id: &str) -> Result<()> {
        valid_id(id)?;
        ensure!(
            !self.index()?.iter().any(|e| e["id"] == id) && !self.dir.join(format!("{id}.json")).exists(),
            "result id already exists"
        );
        Ok(())
    }
    pub fn insert(&mut self, entry: Value, detail: Option<Value>) -> Result<()> {
        let id = entry["id"].as_str().context("result id")?;
        self.ensure_new(id)?;
        let mut index = self.index()?;
        // Publish detail first, then commit index with atomic rename. Index is
        // authoritative; a crash orphan is never overwritten/reused.
        if let Some(d) = detail {
            self.atomic(&format!("{id}.json"), &d)?;
        }
        index.push(entry);
        index.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
        self.atomic("index.json", &json!(index))
    }
    pub fn lesson(&mut self, id: &str, text: &str) -> Result<()> {
        valid_id(id)?;
        let mut index = self.index()?;
        let e = index
            .iter_mut()
            .find(|e| e["id"] == id)
            .context("no private result with id")?;
        e["lesson"] = json!(text);
        self.atomic("index.json", &json!(index))
    }
    pub fn index(&self) -> Result<Vec<Value>> {
        let p = self.dir.join("index.json");
        if !p.exists() {
            return Ok(vec![]);
        }
        secure(&p, false)?;
        let index: Vec<Value> = serde_json::from_slice(&fs::read(p)?)?;
        let mut seen = std::collections::BTreeSet::new();
        for e in &index {
            let id = e["id"].as_str().context("result id")?;
            valid_id(id)?;
            ensure!(seen.insert(id), "duplicate index id");
        }
        Ok(index)
    }
    fn atomic(&self, name: &str, value: &Value) -> Result<()> {
        secure(&self.dir, true)?;
        let target = self.dir.join(name);
        private_path(&target)?;
        if target.exists() {
            secure(&target, false)?;
        }
        let temp = self.dir.join(format!(".{name}.pending"));
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&temp)?;
        let result = (|| -> Result<()> {
            file.write_all(&serde_json::to_vec(value)?)?;
            file.sync_all()?;
            secure(&temp, false)?;
            fs::rename(&temp, &target)?;
            fs::File::open(&self.dir)?.sync_all()?;
            secure(&target, false)
        })();
        if result.is_err() {
            let _ = fs::remove_file(temp);
        }
        result
    }
}
fn valid_id(id: &str) -> Result<()> {
    ensure!(
        !id.is_empty() && id != "index" && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "invalid result id"
    );
    Ok(())
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use serde_json::{Value, json};
    use std::{fs, path::PathBuf};
    pub struct Fixture(pub PathBuf);
    impl Fixture {
        pub fn new() -> Self {
            use std::sync::atomic::{AtomicUsize, Ordering};
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let p = std::env::temp_dir().canonicalize().unwrap().join(format!(
                "sh-quant-synthetic-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&p).unwrap();
            Self(p)
        }
        pub fn manifest(&self) -> PathBuf {
            self.0.join("manifest.json")
        }
        pub fn populate(&self) -> Value {
            let text = "date,open,high,low,close,volume\n2022-12-29,10,12,9,11,0\n2022-12-30,11,13,10,12,5\n2023-01-02,12,14,11,13,8\n2023-01-03,13,15,12,14,9\n";
            let mut entries = vec![];
            for m in ["US", "KR"] {
                for t in crate::data::universe(m) {
                    let path = format!("{m}_{t}.toss.csv");
                    fs::write(self.0.join(&path), text).unwrap();
                    entries.push(json!({"market":m,"ticker":t,"currency":if m=="US" {"USD"} else {"KRW"},"session":if m=="US" {"US_REGULAR"} else {"KR_INTEGRATED"},"path":path,"sha256":digest(text.as_bytes()),"rows":4,"first":"2022-12-29","last":"2023-01-03"}));
                }
            }
            let v = json!({"schema_version":2,"provider":"toss","adjusted":true,"timezone":"Asia/Seoul","cutoff_exclusive":"2023-01-04","prepared_at":"2023-01-04T00:00:00+09:00","status":"complete","entries":entries});
            self.write(&v);
            v
        }
        pub fn write(&self, v: &Value) {
            fs::write(self.manifest(), serde_json::to_vec(v).unwrap()).unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    // All schema3 prices and classifications below are synthetic, not market coverage.
    fn synthetic_schema3(f: &Fixture) -> (Value, Value) {
        let mut manifest = f.populate();
        let old = manifest["entries"].as_array().unwrap();
        let mut entries = vec![old[0].clone(), old[12].clone()];
        let universe = json!({
            "schema_version":1,"universe_id":"synthetic-alternate",
            "classification_as_of":"2026-11-13","point_in_time":false,
            "selection_policy":"Synthetic test only","limitations":["Not market data"],
            "instruments":[
                {"market":"US","ticker":"TEST.A","source_symbol":"TEST-A","themes":["synthetic"]},
                {"market":"KR","ticker":"12345A","source_symbol":"12345B","themes":["synthetic"]}
            ]
        });
        for (entry, instrument) in entries
            .iter_mut()
            .zip(universe["instruments"].as_array().unwrap())
        {
            entry["ticker"] = instrument["ticker"].clone();
            entry["source_symbol"] = instrument["source_symbol"].clone();
        }
        manifest["schema_version"] = json!(3);
        manifest["entries"] = json!(entries);
        write_synthetic_universe(f, &mut manifest, &serde_json::to_vec(&universe).unwrap());
        (manifest, universe)
    }
    fn write_synthetic_universe(f: &Fixture, manifest: &mut Value, bytes: &[u8]) {
        fs::write(f.0.join("universe.json"), bytes).unwrap();
        manifest["universe"] = json!({"path":"universe.json","sha256":digest(bytes)});
        f.write(manifest);
    }
    #[test]
    fn schema3_loads_synthetic_alternate_two_market_universe() {
        let f = Fixture::new();
        let (mut manifest, _) = synthetic_schema3(&f);
        let input = Frozen::load(&f.manifest()).expect("schema3 alternate universe");
        assert_eq!(input.market("US")[0].0, "TEST.A");
        assert_eq!(input.market("KR")[0].0, "12345A");
        assert_eq!(input.market("US")[0].1.close, vec![11., 12., 13., 14.]);
        input.verify().unwrap();
        manifest["schema_version"] = json!(2);
        f.write(&manifest);
        assert!(
            Frozen::load(&f.manifest()).is_err(),
            "schema2 must retain exact24"
        );
    }
    #[test]
    fn schema3_universe_digest_and_verify_use_exact_raw_bytes() {
        let f = Fixture::new();
        let (mut manifest, _) = synthetic_schema3(&f);
        let path = f.0.join("universe.json");
        let mut bytes = fs::read(&path).unwrap();
        bytes.push(b'\n'); // Still identical JSON, different frozen bytes.
        fs::write(&path, &bytes).unwrap();
        assert!(Frozen::load(&f.manifest()).is_err(), "digest mismatch");
        write_synthetic_universe(&f, &mut manifest, &bytes);
        let input = Frozen::load(&f.manifest()).unwrap();
        bytes.push(b' ');
        fs::write(path, bytes).unwrap();
        assert!(input.verify().is_err(), "catalog tampering after load");
    }
    #[test]
    fn schema3_rejects_invalid_synthetic_catalog_contract() {
        let f = Fixture::new();
        let (mut manifest, catalog) = synthetic_schema3(&f);
        let mut invalid = vec![];
        for (field, value) in [
            ("schema_version", json!(2)),
            ("point_in_time", json!(true)),
            ("universe_id", json!("Upper")),
            ("universe_id", json!("-bad")),
            ("universe_id", json!("x".repeat(65))),
            ("classification_as_of", json!("2026-2-30")),
            ("classification_as_of", json!("2026-02-30")),
            ("selection_policy", json!("  ")),
            ("limitations", json!([])),
            ("limitations", json!([""])),
            ("unknown", json!(true)),
        ] {
            let mut c = catalog.clone();
            c[field] = value;
            invalid.push(c);
        }
        for field in [
            "schema_version",
            "universe_id",
            "classification_as_of",
            "point_in_time",
            "selection_policy",
            "limitations",
            "instruments",
        ] {
            let mut c = catalog.clone();
            c.as_object_mut().unwrap().remove(field);
            invalid.push(c);
        }
        for (index, field, value) in [
            (0, "ticker", json!("lower")),
            (0, "ticker", json!(".BAD")),
            (0, "ticker", json!("X".repeat(25))),
            (0, "source_symbol", json!("a/b")),
            (1, "ticker", json!("12345")),
            (1, "ticker", json!("12345a")),
            (1, "source_symbol", json!("1234567")),
            (0, "market", json!("XX")),
            (0, "themes", json!([])),
            (0, "themes", json!(["same", "same"])),
            (0, "themes", json!(["Bad tag"])),
            (0, "unknown", json!(0)),
        ] {
            let mut c = catalog.clone();
            c["instruments"][index][field] = value;
            invalid.push(c);
        }
        for field in ["market", "ticker", "source_symbol", "themes"] {
            let mut c = catalog.clone();
            c["instruments"][0].as_object_mut().unwrap().remove(field);
            invalid.push(c);
        }
        let mut duplicate = catalog.clone();
        duplicate["instruments"]
            .as_array_mut()
            .unwrap()
            .push(catalog["instruments"][0].clone());
        invalid.push(duplicate);
        let mut alias = catalog.clone();
        let mut other = catalog["instruments"][0].clone();
        other["ticker"] = json!("OTHER");
        alias["instruments"].as_array_mut().unwrap().push(other);
        invalid.push(alias);
        let mut single_market = catalog.clone();
        single_market["instruments"].as_array_mut().unwrap().pop();
        invalid.push(single_market);
        let mut empty = catalog.clone();
        empty["instruments"] = json!([]);
        invalid.push(empty);
        let mut oversized = catalog.clone();
        oversized["instruments"] = json!((0..513).map(|i| json!({"market":"US","ticker":format!("T{i}"),"source_symbol":format!("T{i}"),"themes":["synthetic"]})).collect::<Vec<_>>());
        invalid.push(oversized);
        let mut accepted = vec![];
        for (n, c) in invalid.iter().enumerate() {
            write_synthetic_universe(&f, &mut manifest, &serde_json::to_vec(c).unwrap());
            if Frozen::load(&f.manifest()).is_ok() {
                accepted.push(n);
            }
        }
        // Duplicate keys must be rejected at both catalog and instrument level.
        for (n, bytes) in [
            serde_json::to_string(&catalog)
                .unwrap()
                .replacen("{", "{\"point_in_time\":false,", 1),
            serde_json::to_string(&catalog).unwrap().replace(
                "\"ticker\":\"TEST.A\"",
                "\"ticker\":\"TEST.A\",\"ticker\":\"TEST.A\"",
            ),
        ]
        .iter()
        .enumerate()
        {
            write_synthetic_universe(&f, &mut manifest, bytes.as_bytes());
            if Frozen::load(&f.manifest()).is_ok() {
                accepted.push(1000 + n);
            }
        }
        assert!(
            accepted.is_empty(),
            "accepted invalid catalog cases {accepted:?}"
        );
    }
    #[test]
    fn schema3_requires_exact_manifest_descriptor_sources() {
        let mut accepted = vec![];
        for (n, (field, value)) in [
            ("source_symbol", json!("TEST.A")),
            ("source_symbol", Value::Null),
            ("currency", json!("KRW")),
            ("session", json!("KR_INTEGRATED")),
            ("ticker", json!("EXTRA")),
        ]
        .into_iter()
        .enumerate()
        {
            let f = Fixture::new();
            let (mut m, _) = synthetic_schema3(&f);
            m["entries"][0][field] = value;
            f.write(&m);
            if Frozen::load(&f.manifest()).is_ok() {
                accepted.push(n);
            }
        }
        for mode in 0..3 {
            let f = Fixture::new();
            let (mut m, _) = synthetic_schema3(&f);
            let entries = m["entries"].as_array_mut().unwrap();
            match mode {
                0 => {
                    entries.pop();
                }
                1 => entries.push(entries[0].clone()),
                _ => {
                    entries[0].as_object_mut().unwrap().remove("source_symbol");
                }
            }
            f.write(&m);
            if Frozen::load(&f.manifest()).is_ok() {
                accepted.push(100 + mode);
            }
        }
        assert!(
            accepted.is_empty(),
            "accepted mismatched entries {accepted:?}"
        );
    }
    #[test]
    fn schema3_rejects_unsafe_or_noncanonical_universe_reference() {
        for path in [
            "../universe.json",
            "/universe.json",
            "",
            "./universe.json",
            "alias.json",
        ] {
            let f = Fixture::new();
            let (mut m, _) = synthetic_schema3(&f);
            fs::copy(f.0.join("universe.json"), f.0.join("alias.json")).unwrap();
            m["universe"]["path"] = json!(path);
            f.write(&m);
            assert!(Frozen::load(&f.manifest()).is_err(), "accepted path {path}");
        }
        use std::os::unix::fs::symlink;
        for hardlink in [false, true] {
            let f = Fixture::new();
            synthetic_schema3(&f);
            let original = f.0.join("universe.json");
            let target = f.0.join("catalog");
            fs::rename(&original, &target).unwrap();
            if hardlink {
                fs::hard_link(&target, &original).unwrap();
            } else {
                symlink(&target, &original).unwrap();
            }
            fs::set_permissions(&target, fs::Permissions::from_mode(0o644)).unwrap();
            assert!(Frozen::load(&f.manifest()).is_err());
            assert_eq!(
                fs::metadata(target).unwrap().permissions().mode() & 0o777,
                0o644
            );
        }
    }
    #[test]
    fn schema3_requires_strict_reference_but_schema2_ignores_new_metadata() {
        let f = Fixture::new();
        let mut legacy = f.populate();
        legacy["universe"] = json!("ignored legacy extension");
        legacy["entries"][0]["source_symbol"] = json!({"ignored":true});
        f.write(&legacy);
        Frozen::load(&f.manifest()).expect("schema2 extension tolerance unchanged");
        let (manifest, _) = synthetic_schema3(&f);
        for reference in [
            Value::Null,
            json!({"path":"universe.json"}),
            json!({"path":"universe.json","sha256":manifest["universe"]["sha256"],"extra":0}),
        ] {
            let mut m = manifest.clone();
            m["universe"] = reference;
            f.write(&m);
            assert!(Frozen::load(&f.manifest()).is_err(), "invalid reference");
        }
        let raw = serde_json::to_string(&manifest).unwrap().replace(
            "\"path\":\"universe.json\"",
            "\"path\":\"universe.json\",\"path\":\"universe.json\"",
        );
        fs::write(f.manifest(), raw).unwrap();
        assert!(
            Frozen::load(&f.manifest()).is_err(),
            "duplicate reference key"
        );
    }
    #[test]
    fn frozen_rejects_reused_csv_paths() {
        let f = Fixture::new();
        let mut v = f.populate();
        v["entries"][1]["path"] = v["entries"][0]["path"].clone();
        f.write(&v);
        assert!(Frozen::load(&f.manifest()).is_err());
    }
    // Test-only (#50): parallel process spawning can inherit another test's
    // CLOEXEC lock descriptor until exec/exit. Only use after the intended
    // owner has gone away, never for live-owner rejection assertions.
    pub(crate) fn uncontended<T>(mut operation: impl FnMut() -> Result<T>) -> Result<T> {
        use std::time::{Duration, Instant};
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match operation() {
                Err(error)
                    if matches!(
                        error.downcast_ref::<fs::TryLockError>(),
                        Some(fs::TryLockError::WouldBlock)
                    ) && Instant::now() < deadline =>
                {
                    std::thread::sleep(Duration::from_millis(5));
                }
                result => return result,
            }
        }
    }

    #[test]
    fn uncontended_propagates_non_lock_errors_without_retry() {
        for error in [
            anyhow::anyhow!("private output locked: operation would block"),
            std::io::Error::from(std::io::ErrorKind::WouldBlock).into(),
            fs::TryLockError::Error(std::io::Error::from(std::io::ErrorKind::PermissionDenied)).into(),
        ] {
            let expected = format!("{error:#}");
            let mut error = Some(error);
            let mut attempts = 0;
            let result: Result<()> = uncontended(|| {
                attempts += 1;
                Err(error.take().expect("non-lock error must not retry"))
            });
            assert_eq!(attempts, 1);
            assert_eq!(format!("{:#}", result.unwrap_err()), expected);
        }
    }

    #[test]
    fn uncontended_stops_at_deadline_without_unlocking_live_owner() {
        use std::time::{Duration, Instant};
        let f = Fixture::new();
        let dir = f.0.join("output");
        let _owner = Store::open(&dir).unwrap();
        let start = Instant::now();
        let error = uncontended(|| Store::open(&dir)).err().unwrap();
        assert!(matches!(
            error.downcast_ref::<fs::TryLockError>(),
            Some(fs::TryLockError::WouldBlock)
        ));
        assert!(start.elapsed() >= Duration::from_secs(2));
        assert!(start.elapsed() < Duration::from_secs(5));
        assert!(Store::open(&dir).is_err());
    }

    #[test]
    fn private_store_reopens_after_inherited_fork_descriptor_closes() {
        use std::io::Write;
        use std::os::fd::AsRawFd;
        use std::os::unix::net::UnixStream;
        unsafe extern "C" {
            fn fork() -> i32;
            fn read(fd: i32, buffer: *mut std::ffi::c_void, count: usize) -> isize;
            fn _exit(status: i32) -> !;
            fn waitpid(pid: i32, status: *mut i32, options: i32) -> i32;
        }
        // Release and reap only this owned child, including on assertion panic.
        struct ForkChild(i32, UnixStream);
        impl Drop for ForkChild {
            fn drop(&mut self) {
                let _ = self.1.write_all(b"release");
                let mut status = 0;
                loop {
                    let result = unsafe { waitpid(self.0, &mut status, 0) };
                    if result == self.0 {
                        assert_eq!(status, 0, "fork child failed");
                        break;
                    }
                    if std::io::Error::last_os_error().kind() != std::io::ErrorKind::Interrupted {
                        panic!("could not reap owned fork child");
                    }
                }
            }
        }
        let f = Fixture::new();
        let dir = f.0.join("output");
        let store = Store::open(&dir).unwrap();
        let before = fs::metadata(dir.join(".writer.lock")).unwrap();
        let (parent, child) = UnixStream::pair().unwrap();
        let child_fd = child.as_raw_fd();
        let pid = unsafe { fork() };
        assert!(pid >= 0, "fork failed");
        if pid == 0 {
            // No Rust runtime, allocation, unwinding or destructors after fork.
            // Blocking here models the fork-to-exec window of a parallel spawn.
            let mut byte = 0u8;
            unsafe {
                loop {
                    let received = read(child_fd, (&mut byte as *mut u8).cast(), 1);
                    if received >= 0 {
                        _exit(if received == 1 { 0 } else { 1 });
                    }
                }
            }
        }
        let child = ForkChild(pid, parent);
        drop(store);
        let error = Store::open(&dir)
            .err()
            .expect("child must retain inherited lock");
        assert!(matches!(
            error.downcast_ref::<fs::TryLockError>(),
            Some(fs::TryLockError::WouldBlock)
        ));
        let mut child = Some(child);
        let reopened = uncontended(|| {
            let result = Store::open(&dir);
            if result.is_err() {
                // Release only after capturing the first real lock failure:
                // the old immediate-open path deterministically remains RED.
                drop(child.take());
            }
            result
        })
        .expect("uncontended reopen must tolerate inherited descriptor release");
        assert!(Store::open(&dir).is_err()); // Still rejects an actual live owner.
        let after = fs::metadata(dir.join(".writer.lock")).unwrap();
        assert_eq!((before.dev(), before.ino()), (after.dev(), after.ino()));
        drop(reopened);
    }

    // Invoked only by the process-death regression test, never by the suite.
    #[test]
    #[ignore]
    fn private_store_process_holder() {
        let dir = PathBuf::from(std::env::var_os("SH_QUANT_LOCK_TEST_DIR").unwrap());
        let ready = PathBuf::from(std::env::var_os("SH_QUANT_LOCK_TEST_READY").unwrap());
        let _store = Store::open(&dir).unwrap();
        fs::write(ready, b"ready").unwrap();
        loop {
            std::thread::sleep(std::time::Duration::from_secs(60));
        }
    }

    #[test]
    fn private_store_refuses_concurrent_process_and_reopens_after_sigkill() {
        use std::process::{Command, Stdio};
        use std::time::{Duration, Instant};
        struct ChildGuard(std::process::Child);
        impl Drop for ChildGuard {
            fn drop(&mut self) {
                let _ = self.0.kill();
                let _ = self.0.wait();
            }
        }
        let f = Fixture::new();
        let dir = f.0.join("output");
        let ready = f.0.join("ready");
        let mut child = ChildGuard(
            Command::new(std::env::current_exe().unwrap())
                .args([
                    "--ignored",
                    "--exact",
                    "frozen::tests::private_store_process_holder",
                ])
                .env("SH_QUANT_LOCK_TEST_DIR", &dir)
                .env("SH_QUANT_LOCK_TEST_READY", &ready)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap(),
        );
        let deadline = Instant::now() + Duration::from_secs(10);
        while !ready.exists() {
            assert!(
                child.0.try_wait().unwrap().is_none(),
                "lock holder exited before ready"
            );
            assert!(Instant::now() < deadline, "lock holder readiness timeout");
            std::thread::sleep(Duration::from_millis(10));
        }
        let lock_path = dir.join(".writer.lock");
        let before = fs::metadata(&lock_path).unwrap();
        // This process must fail immediately while the independent writer lives.
        assert!(Store::open(&dir).is_err());
        assert!(child.0.try_wait().unwrap().is_none());
        assert_eq!(fs::metadata(&lock_path).unwrap().ino(), before.ino());
        child.0.kill().unwrap(); // SIGKILL on Unix: Store::drop cannot run.
        use std::os::unix::process::ExitStatusExt;
        assert_eq!(child.0.wait().unwrap().signal(), Some(9));
        let store = Store::open(&dir).expect("kernel must release writer lock after SIGKILL");
        assert!(Store::open(&dir).is_err());
        drop(store);
        let after = fs::metadata(&lock_path).expect("lock sidecar must persist after normal drop");
        assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
        let _store = uncontended(|| Store::open(&dir)).unwrap();
    }

    #[test]
    fn private_store_preserves_pending_crash_artifacts_and_ids() {
        let f = Fixture::new();
        let dir = f.0.join("output");
        fs::create_dir(&dir).unwrap();
        // A pre-upgrade empty lock sidecar is safe to reuse, never delete.
        fs::write(dir.join(".writer.lock"), b"").unwrap();
        let pending = dir.join(".index.json.pending");
        fs::write(&pending, b"unknown interrupted write").unwrap();
        let orphan = dir.join("orphan.json");
        fs::write(&orphan, b"unknown orphan detail").unwrap();
        let mut store = Store::open(&dir).unwrap();
        assert!(store.insert(json!({"id":"new"}), None).is_err());
        assert_eq!(fs::read(&pending).unwrap(), b"unknown interrupted write");
        assert!(!dir.join("index.json").exists());
        assert!(
            store
                .insert(json!({"id":"orphan"}), Some(json!({})))
                .is_err()
        );
        assert_eq!(fs::read(&orphan).unwrap(), b"unknown orphan detail");
        drop(store);
        let mut store = uncontended(|| Store::open(&dir)).unwrap();
        assert!(store.insert(json!({"id":"new"}), None).is_err());
        assert_eq!(fs::read(&pending).unwrap(), b"unknown interrupted write");
    }

    #[test]
    fn private_store_rejects_aliased_lock_sidecars_without_removing_them() {
        use std::os::unix::fs::symlink;
        for hardlink in [false, true] {
            let f = Fixture::new();
            let dir = f.0.join("output");
            fs::create_dir(&dir).unwrap();
            let target = f.0.join("unrelated");
            fs::write(&target, b"must not change").unwrap();
            fs::set_permissions(&target, fs::Permissions::from_mode(0o644)).unwrap();
            let lock = dir.join(".writer.lock");
            if hardlink {
                fs::hard_link(&target, &lock).unwrap();
            } else {
                symlink(&target, &lock).unwrap();
            }
            assert!(Store::open(&dir).is_err());
            assert!(fs::symlink_metadata(&lock).is_ok());
            assert_eq!(fs::read(&target).unwrap(), b"must not change");
            assert_eq!(
                fs::metadata(&target).unwrap().permissions().mode() & 0o777,
                0o644
            );
        }
    }

    #[test]
    fn private_store_is_locked_atomic_and_refuses_duplicate_ids() {
        let f = Fixture::new();
        let dir = f.0.join("output");
        let mut store = Store::open(&dir).unwrap();
        assert!(Store::open(&dir).is_err());
        store
            .insert(
                json!({"id":"synthetic-a","markets":{"synthetic":1}}),
                Some(json!({"curves":{}})),
            )
            .unwrap();
        assert!(
            store
                .insert(json!({"id":"synthetic-a","status":"failed"}), None)
                .is_err()
        );
        assert!(store.insert(json!({"id":"../escape"}), None).is_err());
        assert!(store.lesson("missing", "text").is_err());
        store.lesson("synthetic-a", "synthetic lesson").unwrap();
        let index: Value = serde_json::from_slice(&fs::read(dir.join("index.json")).unwrap()).unwrap();
        assert_eq!(index[0]["lesson"], "synthetic lesson");
        assert_eq!(index[0]["markets"]["synthetic"], 1);
        assert!(dir.join("synthetic-a.json").exists());
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(&dir).unwrap().permissions().mode() & 0o777, 0o700);
        for e in fs::read_dir(&dir).unwrap() {
            assert_eq!(e.unwrap().metadata().unwrap().permissions().mode() & 0o777, 0o600);
        }
        drop(store);
        let mut store = uncontended(|| Store::open(&dir)).unwrap();
        store.insert(json!({"id":"synthetic-b"}), None).unwrap();
        assert_eq!(store.index().unwrap().len(), 2);
        assert!(Store::open(&crate::root().join("results")).is_err());
        assert!(Store::open(Path::new("relative")).is_err());
        let f = Fixture::new();
        fs::create_dir(f.0.join(".git")).unwrap();
        assert!(Store::open(&f.0.join("nested/out")).is_err());
    }
    #[test]
    fn frozen_private_paths_permissions_and_immutability() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let f = Fixture::new();
        f.populate();
        let input = Frozen::load(&f.manifest()).unwrap();
        assert_eq!(fs::metadata(&f.0).unwrap().permissions().mode() & 0o777, 0o700);
        for e in fs::read_dir(&f.0).unwrap() {
            assert_eq!(e.unwrap().metadata().unwrap().permissions().mode() & 0o777, 0o600);
        }
        fs::write(f.manifest(), b"{}").unwrap();
        assert!(input.verify().is_err());
        let f = Fixture::new();
        f.populate();
        let input = Frozen::load(&f.manifest()).unwrap();
        fs::write(f.0.join("US_SPY.toss.csv"), b"changed").unwrap();
        assert!(input.verify().is_err());
        let f = Fixture::new();
        f.populate();
        fs::create_dir(f.0.join(".git")).unwrap();
        assert!(Frozen::load(&f.manifest()).is_err());
        let f = Fixture::new();
        f.populate();
        let other = Fixture::new();
        let target = other.0.join("data");
        fs::rename(f.0.join("US_SPY.toss.csv"), &target).unwrap();
        symlink(target, f.0.join("US_SPY.toss.csv")).unwrap();
        assert!(Frozen::load(&f.manifest()).is_err());
        let f = Fixture::new();
        f.populate();
        let other = Fixture::new();
        symlink(&f.0, other.0.join("link")).unwrap();
        assert!(Frozen::load(&other.0.join("link/manifest.json")).is_err());
        assert!(Frozen::load(Path::new("relative.json")).is_err());
        assert!(Frozen::load(&crate::root().join("results/manifest.json")).is_err());
    }
    #[test]
    fn frozen_rejects_invalid_manifest_and_csv() {
        let cases: Vec<(&str, Value)> = vec![
            ("schema_version", json!(1)),
            ("provider", json!("yahoo")),
            ("adjusted", json!(false)),
            ("timezone", json!("UTC")),
            ("status", json!("partial")),
            ("prepared_at", json!("yesterday")),
            ("cutoff_exclusive", json!("2023-1-4")),
            ("cutoff_exclusive", json!("2023-01-03")),
        ];
        for (key, value) in cases {
            let f = Fixture::new();
            let mut v = f.populate();
            v[key] = value;
            f.write(&v);
            assert!(Frozen::load(&f.manifest()).is_err(), "accepted {key}");
        }
        for (key, value) in [
            ("market", json!("XX")),
            ("ticker", json!("EXTRA")),
            ("currency", json!("KRW")),
            ("session", json!("KR_INTEGRATED")),
            ("sha256", json!("0".repeat(64))),
            ("rows", json!(3)),
            ("first", json!("2022-12-28")),
            ("last", json!("2023-01-02")),
            ("path", json!("../US_SPY.toss.csv")),
        ] {
            let f = Fixture::new();
            let mut v = f.populate();
            v["entries"][0][key] = value;
            f.write(&v);
            assert!(Frozen::load(&f.manifest()).is_err(), "accepted entry {key}");
        }
        for duplicate in [false, true] {
            let f = Fixture::new();
            let mut v = f.populate();
            let a = v["entries"].as_array_mut().unwrap();
            if duplicate {
                a.push(a[0].clone());
            } else {
                a.pop();
            }
            f.write(&v);
            assert!(Frozen::load(&f.manifest()).is_err());
        }
        for bad in [
            "2022-12-29,0,12,9,11,0",
            "2022-12-29,10,8,9,11,0",
            "2022-12-29,10,12,9,NaN,0",
            "2022-12-29,10,12,9,11,-1",
            "2022-12-29,10,inf,9,11,0",
            "2022-12-30,10,12,9,11,0",
            "2022-2-29,10,12,9,11,0",
        ] {
            let f = Fixture::new();
            let mut v = f.populate();
            let p = f.0.join("US_SPY.toss.csv");
            let text = fs::read_to_string(&p).unwrap().replace("2022-12-29,10,12,9,11,0", bad);
            fs::write(p, &text).unwrap();
            v["entries"][0]["sha256"] = json!(digest(text.as_bytes()));
            f.write(&v);
            assert!(Frozen::load(&f.manifest()).is_err(), "accepted malformed CSV");
        }
        let f = Fixture::new();
        let mut v = f.populate();
        let p = f.0.join("US_SPY.toss.csv");
        let text = fs::read_to_string(&p)
            .unwrap()
            .replace("date,open,high,low,close,volume", "wrong,open,high,low,close,volume");
        fs::write(p, &text).unwrap();
        v["entries"][0]["sha256"] = json!(digest(text.as_bytes()));
        f.write(&v);
        assert!(Frozen::load(&f.manifest()).is_err());
    }
    #[test]
    fn frozen_loads_full_synthetic_universe_with_engine_parity() {
        let f = Fixture::new();
        f.populate();
        let input = Frozen::load(&f.manifest()).unwrap();
        let sig = crate::expr::compile("1", &|_| unreachable!()).unwrap();
        for m in ["US", "KR"] {
            let bars = input.market(m);
            assert_eq!(bars.len(), 12);
            let reference: Vec<_> = crate::data::universe(m)
                .iter()
                .map(|t| {
                    (
                        t.to_string(),
                        crate::data::Bars {
                            dates: vec!["2022-12-29", "2022-12-30", "2023-01-02", "2023-01-03"]
                                .into_iter()
                                .map(|d| d.parse().unwrap())
                                .collect(),
                            open: vec![10., 11., 12., 13.],
                            high: vec![12., 13., 14., 15.],
                            low: vec![9., 10., 11., 12.],
                            close: vec![11., 12., 13., 14.],
                            volume: vec![0., 5., 8., 9.],
                        },
                    )
                })
                .collect();
            let a = crate::backtest::run_market(&sig, &bars, m).unwrap();
            let b = crate::backtest::run_market(&sig, &reference, m).unwrap();
            assert_eq!(
                serde_json::to_value(a.metrics).unwrap(),
                serde_json::to_value(b.metrics).unwrap()
            );
            assert_eq!(
                serde_json::to_value(a.curve).unwrap(),
                serde_json::to_value(b.curve).unwrap()
            );
        }
        input.verify().unwrap();
    }
}
