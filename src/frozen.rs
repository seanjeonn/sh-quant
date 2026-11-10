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
struct Entry {
    market: String,
    ticker: String,
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
            manifest.schema_version == 2
                && manifest.provider == "toss"
                && manifest.adjusted
                && manifest.timezone == "Asia/Seoul"
                && manifest.status == "complete",
            "invalid manifest policy"
        );
        chrono::DateTime::parse_from_rfc3339(&manifest.prepared_at).context("invalid prepared_at")?;
        let cutoff = strict_date(&manifest.cutoff_exclusive)?;
        let expected: std::collections::BTreeSet<_> = ["US", "KR"]
            .into_iter()
            .flat_map(|m| {
                crate::data::universe(m)
                    .iter()
                    .map(move |t| (m.to_string(), t.to_string()))
            })
            .collect();
        let mut seen = std::collections::BTreeSet::new();
        let mut paths = std::collections::BTreeSet::new();
        let mut markets: BTreeMap<String, Vec<(String, Bars)>> = BTreeMap::new();
        for e in manifest.entries {
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

/// A fail-closed exclusive writer lock. A crash may leave .writer.lock; inspect
/// and remove it manually only after confirming no writer is alive.
pub struct Store {
    dir: PathBuf,
    _lock: fs::File,
}
impl Drop for Store {
    fn drop(&mut self) {
        let _ = fs::remove_file(self.dir.join(".writer.lock"));
    }
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
        let lock = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join(".writer.lock"))
            .context("private output locked")?;
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
    #[test]
    fn frozen_rejects_reused_csv_paths() {
        let f = Fixture::new();
        let mut v = f.populate();
        v["entries"][1]["path"] = v["entries"][0]["path"].clone();
        f.write(&v);
        assert!(Frozen::load(&f.manifest()).is_err());
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
        let mut store = Store::open(&dir).unwrap();
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
