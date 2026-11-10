"""One-off #23 data preparation; no strategy/engine invocation."""
import concurrent.futures,csv,datetime,hashlib,io,json,math,pathlib,shutil,time,urllib.request,zoneinfo
# Publication copy: ROOT is portable; historical executed copy and its exact hash
# are retained in the local snapshot (manifest.preparation_script_sha256).
ROOT=pathlib.Path(__file__).resolve().parents[2]
SID='2026-11-10_ema_cross'
BASE=ROOT/'data/cache'/('snapshot_'+SID)
BASE.mkdir(parents=True,exist_ok=False)
shutil.copy2(__file__,BASE/'prepare.py')
NOW=datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Seoul'))
END=int(NOW.timestamp())
U={'US':['SPY','QQQ','AAPL','MSFT','NVDA','AMZN','GOOGL','META','JPM','XOM','JNJ','BRK-B'],'KR':['069500','005930','000660','207940','005380','000270','035420','051910','006400','105560','055550','035720']}
def sha(b): return hashlib.sha256(b).hexdigest()
def task(pair):
 m,t=pair; symbol=t+'.KS' if m=='KR' else t
 url=f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?period1=1420070400&period2={END}&interval=1d&events=div%2Csplit'
 attempts=[]
 for attempt in range(1,4):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=40) as r: raw=r.read()
   (BASE/f'{m}_{t}.raw.json').write_bytes(raw)
   v=json.loads(raw); x=v['chart']['result'][0]; q=x['indicators']['quote'][0]; adj=x['indicators']['adjclose'][0]['adjclose']; off=x['meta'].get('gmtoffset',0)
   rows=[]; skipped=0; live=0
   for i,stamp in enumerate(x['timestamp']):
    vals=[q[k][i] for k in ['open','high','low','close','volume']]+[adj[i]]
    if any(z is None for z in vals) or vals[3]<=0: skipped+=1; continue
    d=datetime.datetime.fromtimestamp(stamp+off,datetime.timezone.utc).date().isoformat()
    # Conservative cutoff: only dates strictly before preparation's KST date.
    if d>=NOW.date().isoformat(): live+=1; continue
    o,h,l,c,vol,a=vals; k=a/c
    row=[d,o*k,h*k,l*k,a,vol]
    assert all(math.isfinite(z) for z in row[1:]) and min(row[1:5])>0 and vol>=0
    assert row[2]+1e-6>=max(row[1],row[3],row[4]) and row[3]-1e-6<=min(row[1],row[2],row[4])
    if rows and d==rows[-1][0]: continue
    assert not rows or d>rows[-1][0]
    rows.append(row)
   assert len(rows)>1500 and rows[0][0]<'2017-01-01' and rows[-1][0]=='2026-11-09', (m,t,len(rows),rows[-1][0])
   text=io.StringIO(); w=csv.writer(text,lineterminator='\n'); w.writerow(['date','open','high','low','close','volume']); w.writerows(rows); b=text.getvalue().encode()
   name=f'{m}_{t}.yahoo.csv'; (BASE/name).write_bytes(b)
   attempts.append({'attempt':attempt,'status':'ok'})
   return {'market':m,'ticker':t,'symbol':symbol,'url':url,'received_at':datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Seoul')).isoformat(),'rows':len(rows),'first':rows[0][0],'last':rows[-1][0],'null_or_nonpositive_skipped':skipped,'current_date_bars_excluded':live,'cache_path':'data/cache/'+name,'snapshot_csv':'data/cache/snapshot_'+SID+'/'+name,'sha256':sha(b),'raw_path':'data/cache/snapshot_'+SID+f'/{m}_{t}.raw.json','raw_sha256':sha(raw),'attempts':attempts}
  except Exception as e:
   attempts.append({'attempt':attempt,'status':'failed','error':str(e)})
   if attempt<3: time.sleep(attempt*2)
 return {'market':m,'ticker':t,'status':'failed','attempts':attempts}
pairs=[(m,t) for m,ts in U.items() for t in ts]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: entries=list(pool.map(task,pairs))
failed=[e for e in entries if e.get('status')=='failed']
manifest={'schema_version':1,'set_id':SID,'prepared_at':NOW.isoformat(),'provider':'Yahoo chart API (existing engine source)','period1':1420070400,'period2':END,'timezone':'Asia/Seoul','cutoff_exclusive':NOW.date().isoformat(),'adjustment':'OHLC multiplied by adjclose/close; volume unchanged, same as pinned src/data.rs','quality_policy':'strict date ordering, finite positive OHLC, high/low bounds, nonnegative volume, >1500 rows, starts before 2017, last date 2026-11-09; null provider bars omitted per engine; same-date live bars excluded','snapshot_location':'data/cache/snapshot_'+SID,'preparation_script_sha256':sha(pathlib.Path(__file__).read_bytes()),'entries':entries,'expected_count':len(pairs),'validated_count':len(entries)-len(failed),'failed_count':len(failed),'limitations':['Fixed current universe is survivorship-biased; 207940 begins after 2015.','Yahoo adjusted prices are a current-vintage revision, not point-in-time.','Freshness relies on same-KST-date mtime; verify hashes and freshness before/after every run.','No exchange calendar completeness guarantee; missing provider dates are not imputed.']}
(BASE/'data-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
assert not failed, 'data setup failed: no caches installed'
for e in entries:
 dest=ROOT/e['cache_path']; assert not dest.exists(); shutil.copyfile(ROOT/e['snapshot_csv'],dest)
print('INSTALLED',len(entries),'validated caches; no strategy executed')
