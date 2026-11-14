# Strategy backlog

사람이 아이디어를 적는 큐. Hermes는 매일 맨 위 `- [ ]` 항목 하나를 구현하고 `- [x]`로 바꾼다.
비어 있으면 에이전트가 과거 결과를 보고 스스로 가설을 만든다.

- [x] EMA 20/60 크로스: 50/200보다 빠른 추세 추종이 OOS에서 나은지 — [2026-11-10 세트](research/2026-11-10_ema_cross/report-toss-completed.md), 완료·defer; IS 선택은40/120, 채택 아님.
- [x] RSI(14) < 30 매수, > 70 매도 평균회귀 — [2026-11-11 세트](research/2026-11-11_rsi14_hysteresis/publication.json), 완료·reject; IS 선택은30/70 기본형, 채택 아님. [정성 기록](research/2026-11-11_rsi14_hysteresis/research-addendum.md), #37 / PR #39.
- [x] 볼린저밴드(20, 2σ) 하단 이탈 매수, 중심선 회귀 시 청산 — [2026-11-13 세트](research/2026-11-13_bollinger_reversion/publication.json), 완료·defer; IS 선택은2.5σ 변형, 채택 아님. [정성 기록](research/2026-11-13_bollinger_reversion/research-addendum.md), #53 / PR #55. 후속12-1 모멘텀 #54.
- [x] 12-1 모멘텀: 12개월 수익률(최근 1개월 제외) > 0 일 때만 보유 — [2026-11-14 세트](research/2026-11-14_momentum_12_1/publication.json), 완료·reject; IS 선택은231일 변형(최근21일 제외), 채택 아님. [정성 기록](research/2026-11-14_momentum_12_1/research-addendum.md), #65 / PR #67. 후속 돈치안 #66.
- [ ] 돈치안 55일 고가 돌파 매수, 20일 저가 이탈 청산 (터틀 변형)
- [ ] MACD(12,26,9) 시그널선 상향 돌파
- [ ] 변동성 타기팅: 20일 실현변동성 역수로 포지션 크기 조절 (목표 연 15%)
- [ ] 200일선 위 + RSI(2) < 10 눌림목 매수
- [ ] 거래량 급증(20일 평균의 2배) + 양봉 다음날 진입, 5일 보유
- [ ] 52주 신고가 근접(95% 이상)일 때만 보유
