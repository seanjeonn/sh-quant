# GDELT 과거 뉴스 백필 — #112

출처: [#11](https://github.com/seanjeonn/sh-quant/issues/11)의 재정의. 데이터: The GDELT Project, <https://www.gdeltproject.org/>.

## 왜 백필인가

- 매일 RSS로 쌓는다는 원래 계획은 실제로 1일치(`data/news/2026-11-09.json`)만 남겼다. 연구 PR이 자기 세트 파일만 커밋하기 때문이다. RSS로는 과거를 채울 수 없다.
- GDELT GKG 2.1은 2015-02-18부터 15분마다 영어 파일과 번역 파일(한국어 원문 포함, `srclc:kor`)을 공개한다. 이용과 재배포는 GDELT 인용과 링크를 조건으로 자유롭다(2026-11-19 about 페이지 확인).

## 점수 방식: 사전 계산 tone만 쓴다

과거 헤드라인을 지금의 LLM으로 점수화하면, 모델이 그 뒤 주가 흐름을 이미 알고 있어 미래 정보가 섞인다. 그래서 GDELT가 기사 수집 시점에 계산한 V1.5 Tone 7개 값(tone, positive, negative, polarity, activity, self/group reference, word count)만 쓴다.

## 데이터 흐름

```text
masterfilelist(.txt, -translation.txt)
  → plan.json            기간 내 *.gkg.csv.zip 목록(크기·md5) 고정
  → run                  다운로드 → md5 검증 → 스트리밍 파싱
                         → V1Organizations(13열)가 별칭과 정확히 일치하는 기사만 보존
                         → matches/<YYYYMM>/<파일>.jsonl, zip 삭제, done.jsonl 기록
  → status               건수·바이트만 출력
```

- 출력은 Git 밖 private 디렉터리(700/600)에 둔다. 기사 단위 기록은 `t`(GDELT 15분 배치 UTC), `src`, `url`, `tone`, `lang`, `inst`다. 헤드라인과 본문은 저장하지 않는다.
- 재개: 같은 `plan.json`과 `done.jsonl`을 쓴다. 완료된 파일은 다시 받지 않는다. 결과 파일은 원자적으로 교체하므로, 중단 뒤 다시 실행해도 행이 중복되지 않는다.
- 실패: `failed.jsonl`에 사유 코드를 남긴다. 같은 파일이 3회 실패하면 전체를 차단한다. 조용히 건너뛰지 않는다.
- 별칭 파일이 바뀌면(`aliases_sha256` 불일치) 실행을 차단한다. 별칭을 바꾸려면 새 버전 파일과 새 출력 디렉터리를 쓴다.

```text
python3 tools/gdelt_backfill.py plan --start 2024-01-01 --end 2024-02-01 --output <private>/gdelt-202401
python3 tools/gdelt_backfill.py run --output <private>/gdelt-202401 --aliases universes/thematic-v1-news-aliases.json --max-files 6000 --max-minutes 300
python3 tools/gdelt_backfill.py status --output <private>/gdelt-202401
```

## 별칭 카탈로그 `universes/thematic-v1-news-aliases.json`

- thematic-v1 96종목 중 개별 종목 60개만 `coverage: orgs`다. ETF와 지수 상품은 `none`이다. 기사가 0건인 것과 커버리지가 없는 것을 구분하기 위해서다.
- 규칙은 파일의 `policy`에 있다. 요약하면 다음과 같다.
  - 영어 법인명(현재·과거 이름)에 법인 접미사를 붙여 정확히 일치시킨다.
  - 그 자체로 흔한 단어나 플랫폼인 이름(apple, amazon, google, alphabet, facebook, kia, hmm)은 접미사가 붙은 형태만 인정한다.
  - 그룹명은 제외한다.
  - 이름이 나중에 다른 회사를 가리키게 되면 `until`로 사용 기한을 둔다.
- 2024-01-08~14 표본의 조직명 빈도와 알려진 옛 이름만 보고 만들었다. 가격이나 전략 결과는 보지 않았다.
- 단독 `google`, `facebook`, `samsung`, `hyundai` 같은 이름을 빼서 일부 기사를 놓친다. 대신 잡음을 줄인다. 이 선택이 결과에 미치는 영향은 2단계 연구에서 한계로 적는다.

## 시점 정렬 (2단계, 미구현)

거래일 t의 피처는 그날 장 마감 전 기사만 쓴다.
- KR: UTC 06:00 이전
- US: UTC 19:30 이전

GKG `t`는 GDELT 수집 배치 시각이라 실제 공개 시각보다 늦거나 같다. 따라서 이 규칙은 보수적이다. 엔진 DSL(`news_count`, `news_tone`)과 supervisor 공급은 별도 feature에서 다룬다.

## 파일럿 (2024-01)

2026-11-19, 이 개발 Mac, 동시 다운로드 4개, 별칭 카탈로그 첫 버전 기준.

| 항목 | 값 |
|---|---|
| 파일 | 5,952개(영어·번역 각 2,976개), 45.1GB |
| 소요 | 2,945초(약 15MB/s) |
| 실패 | 타임아웃 4건. 재실행으로 모두 완료, 재다운로드 없음 |
| 형식 오류 행 | 985개(건너뛰고 개수를 기록) |
| 매칭 기사 | 75,674건. 영어 원문 약 77%, 한국어 원문 약 6%, 그 밖의 언어 약 17% |
| 매칭 결과 크기 | 34MB |

- 커버리지 편차가 크다. 60개 종목의 중앙값은 월 18.5건이다. 미국 대형주와 삼성전자는 월 수천 건이다. 한국 중소형주 11개는 한 달 동안 0건이었다.
- 0건 종목을 한국어 원문 기사 3,493건에서 직접 찾아봤다. 해당 회사명이 거의 나오지 않았다. 별칭 표기 문제가 아니라 GDELT의 한국 매체 수집 범위 한계다. 이 종목들은 뉴스 피처가 사실상 비어 있는 것으로 취급해야 한다.

### 전체 기간 추정

master file list 기준(2015-02-18 ~ 2026-11-18)으로 GKG 파일 804,049개, 약 7.2TB다. 연도별로는 2016년이 약 986GB로 가장 크고 2026년은 약 397GB다. 파일럿 처리량이면 약 130시간(5~6일)이 걸린다. 매칭 결과는 약 5GB로 예상한다. zip은 처리 즉시 지우므로 동시에 쓰는 디스크는 수십 MB다.
