# sh-quant / kingfish

토스증권 Open API로 미국 주식 **1분봉**을 24시간 무인 수집하고 **5분봉**으로 집계해 SQLite에 저장하는 파이프라인.
외부 의존성 없음 (Python 3.11+ stdlib).

## 준비

1. 토스증권 WTS → 설정 → Open API 에서 `client_id`/`client_secret` 발급, **허용 IP**에 이 Mac의 공인 IP 등록.
2. `cp .env.example .env` 후 `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` 입력 (`.env`는 git에 올라가지 않음. 이미 export된 환경변수가 있으면 그쪽이 우선).
3. `config.toml` 의 `symbols` 를 원하는 관심종목으로 수정.

## 실행

```sh
python3 -m kingfish backfill --since 2026-01-01   # 과거 1분봉 백필 (5분봉 자동 집계)
python3 -m kingfish run                            # 상시 수집 루프 (포그라운드)
python3 -m kingfish repair                         # 최근 repair_days 재동기화
python3 -m kingfish status                         # 심볼별 마지막 봉·오류·정규장 결손
python3 -m unittest kingfish.test_kingfish -v      # 테스트 (네트워크 없음)
```

데이터: `kingfish.db` 의 `candles_1m`, `candles_5m` (`ts` = 봉 **종료** 시각, UTC), `market_sessions`, `sync_log`.
API 토큰은 별도 파일 `.kingfish-token.db`(권한 0600)에 있다. `kingfish.db`는 토큰 없이 복사·공유해도 된다.

```sql
SELECT symbol, ts, open, high, low, close, volume, n_bars FROM candles_5m
WHERE symbol='AAPL' AND complete=1 ORDER BY ts DESC LIMIT 20;
```

- `complete=1`: 버킷이 닫히고 65초 이상 지난 뒤 다시 조회된 확정 5분봉. 소비 측은 이것만 쓴다.
- `n_bars`: 버킷 안에서 체결이 있었던 분 수. 정규장에서 5 미만이면 결손, 장외 세션에서는 정상일 수 있다.

## 자가 복구 방식

- 저장은 전부 upsert → 같은 봉을 다시 받아도 안전, 토스가 사후 정정한 값도 반영.
- 진행 중인 봉은 저장하지 않는다. 매 분 :05초에 폴링해 종료 후 5초가 지난 봉만 저장.
- 매 분 최근 `poll_overlap`(30)봉을 다시 받음 → 30분 이내 폴링 실패·재시작은 다음 분에 메워짐.
- 시작 시와 매시간 최근 `repair_days`(3)일에서 **수집 공백**(성공한 폴링이 덮지 못한 세션 시간)과 **정규장 1분 결손**만 재조회.
- 하루 1회, 끝난 마지막 거래일 전체를 재동기화해 사후 정정을 반영.
- repair 작업은 큐로 쪼개 폴링 사이 남는 시간(다음 :05초 10초 전까지)에만 처리 → 폴링이 밀리지 않음.
- 오류 정책: 자격증명 오류는 30분마다 재시도·ERROR 로그, 403(허용 IP 등)은 1분→30분 지수 백오프, 심볼 오류는 해당 심볼만 건너뜀, 429·5xx·네트워크는 즉시 재시도.
- 프로세스가 죽으면 launchd `KeepAlive` 가 재기동. 루프 내부 예외는 로그 후 60초 뒤 계속.
- 로그: `~/Library/Logs/kingfish.log` (10MB × 5 회전).

## launchd 상시 실행

```sh
# 자격증명은 WorkingDirectory(저장소 루트)의 .env 에서 읽는다
sed -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" \
    launchd/com.sh-quant.kingfish.plist > ~/Library/LaunchAgents/com.sh-quant.kingfish.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sh-quant.kingfish.plist
launchctl print gui/$(id -u)/com.sh-quant.kingfish | grep state     # state = running
# 중지: launchctl bootout gui/$(id -u)/com.sh-quant.kingfish
```

## 주의

- 토스 API는 **클라이언트당 토큰 1개**만 유효. kingfish는 토큰을 `.kingfish-token.db` 로 공유하므로 데몬이 돌고 있을 때 `backfill`/`status` 를 병행해도 안전하다. 단, 같은 키를 **다른 프로그램**에서 쓰면 서로 토큰을 무효화한다.
- 1m `timestamp` 는 봉 **종료** 시각. 5분봉 `ts` 도 버킷 종료 시각 (`13:31~13:35` 봉 → `13:35`).
- API는 **진행 중인 분의 봉도 돌려준다**(예: 12:06:14에 `ts=12:07:00` 봉). kingfish는 이를 저장하지 않는다. 5분봉은 `complete=1`만 확정값.
- 미국 1분봉은 2021-12-01 이후만 제공. 정규장 외 세션은 체결 없는 분이 비는 것이 정상이라 `status` 의 결손 집계는 정규장만 본다.
