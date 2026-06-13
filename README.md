# Personal Agent System — Coach + Wiki + Investment + Trading

한 사람의 연구, 학습, 투자, 운동, 일상 결정을 모두 커버하는 **개인 AI 에이전트 시스템**. Cursor IDE + DeepSeek v4 Pro + Upbit API로 구동.

## 철학

- **의도를 가진 100시간 > 의도 없는 10,000시간** — AI가 실행을 맡고, 나는 판단에 집중한다
- **Build to Learn** — Modern Robotics, Mamba, Dynamics 같은 이론을 공부할 때 반드시 코드로 증명
- **Public Shipping** — 배운 것은 곧바로 공개 가능한 결과물로. GitHub = 이력서

## 시스템 구조

```
├── core/                     Python engine
│   ├── coaches.py            Multi-domain coach personas
│   ├── config.py             Environment configuration
│   ├── converters.py         Format converters
│   ├── crossref.py           Cross-reference resolver
│   ├── google_calendar.py    Google Calendar integration
│   ├── ical_sync.py          iCal sync engine
│   ├── ingest.py             Content ingestion pipeline
│   ├── lint.py               Wiki health checker
│   ├── search_engine.py      Local wiki search
│   └── wiki_manager.py       Wiki CRUD with Obsidian sync
├── scripts/
│   ├── yt_transcript.py      YouTube transcript extractor v2
│   │                          (speaker detection, term fix, chapter breaks)
│   └── investment/
│       ├── sources/          Macro / Sector / KRX / News / Fund flow fetchers
│       ├── backtest/         Rule-based strategy backtest engine
│       │                      (Sharpe, Sortino, Calmar, VaR/CVaR)
│       └── reports/          Weekly investment report generator + deep dive
├── autotrade.py              BTC Auto-Trade Bot v2
│                              (DeepSeek + Upbit + Technical Indicators)
├── instructions.md           Trading bot decision instructions (LLM prompt)
├── ontology/                 Knowledge graph structure
│   ├── subject-tree.md       Subject taxonomy
│   ├── topics.md             Topic vocabulary
│   ├── wiki-manifest.json    Wiki inventory
│   └── wiki-dependencies.json Dependency graph
├── *.html / styles.css       Dashboard UIs (crypto, economy, fitness, etc.)
├── requirements.txt          Python dependencies
├── wiki_schema.md            Wiki v3 schema specification
├── CONVENTIONS.md            Operating rules for the system
└── QUICKREF.md               Quick reference
```

## 주요 기능

### 투자 분석 & 트레이딩

- **주간 투자 보고서**: 매크로 → 섹터 → 종목 Top-Down 분석, DeepSeek로 자동 생성
- **BTC Auto-Trade Bot v2**: 8시간 주기 자동매매. OHLCV + 기술적 지표(RSI/MACD/Bollinger/EMA) + 공포·탐욕 지수 + 뉴스 감성 + 온체인 데이터(스테이블코인 시총/체인 TVL) → DeepSeek v4 Pro 추론 → Upbit 주문
- **Deep Dive**: 개별 종목 정량 분석 (FCF, moat, 경쟁력, 시나리오 밸류에이션)
- **백테스트 엔진**: MACD Cross / RSI Reversal / Bollinger Breakout / EMA-SMA Momentum 전략에 대한 Sharpe, Sortino, Calmar, Max DD, Win Rate, VaR/CVaR 계산

### Wiki 시스템 (개인 지식 베이스)

- **v3 Wiki**: `kind: concept | entity | source-record | decision | insight | comparison` 분류 체계
- **Prose Relations**: `builds on [[x]]`, `contradicts [[y]]`, `applies to [[z]]` — 그래프 기반 지식 연결
- **Obsidian Sync**: `2_Wiki/` 디렉토리와 자동 동기화
- **Lint**: 기계적 검증 + 모순 탐지 + 고아 페이지 탐지
- **Ingest**: YouTube, 논문, 팟캐스트 → 자동 source-record + concept 페이지 분해

### YouTube 트랜스크립트

- `yt_transcript.py` — 자동 생성 자막의 오인식 교정(TERM_FIX), 화자 태그 기반 대화 포맷, 챕터 구분, 60초 간격 타임스탬프
- `raw` / `clean` / `dialogue` 3가지 출력 모드

### 대시보드

- `crypto-bot.html` — BTC 봇 상태 모니터링
- `economy.html` — 경제 지표 대시보드
- `fitness.html` / `study.html` / `research.html` — 도메인별 대시보드
- `index.html` — 시스템 오버뷰
- `styles.css` — 공통 스타일

## 기술 스택

| 레이어 | 기술 |
|---|---|
| Agent Runtime | Cursor IDE + Cursor Rules (.cursor/rules/*.mdc) |
| LLM Inference | DeepSeek v4 Pro (deepseek-v4-pro) |
| Trading | Upbit API (pyupbit) |
| Data | CoinGecko, DeFiLlama, KRX, FRED, Google News |
| Backtest | pandas + numpy |
| Wiki | Obsidian vault (flat directory) |
| Deployment | Windows 10, venv |

## 시작하기

```bash
git clone https://github.com/jsm0308/orot-council.git
cd orot-council
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# .env 파일 생성 (API 키 입력)
# DEEPSEEK_API_KEY=sk-...
# UPBIT_ACCESS_KEY=...
# UPBIT_SECRET_KEY=...
# SERPAPI_API_KEY=...

# BTC Auto-Trade Bot (dry run)
python autotrade.py

# 주간 투자 보고서 생성
python scripts/investment/reports/generate_weekly.py --dry-run

# YouTube 트랜스크립트 추출
python scripts/yt_transcript.py "https://youtu.be/VIDEO_ID" --mode dialogue
```

## 현재 스터디/프로젝트

- **로보틱스**: Modern Robotics (Lynch & Park) Ch 2-8, ROS2, HYPER 로보틱스 클럽 (8월~)
- **AI/ML**: Mamba (SSM), Decision Transformer, Vision-Language-Action 모델
- **투자**: ISA 200만원 S&P500 중심 코어-위성 전략 (8월 집행)
- **퀀트**: BTC 단기 트레이딩 전략 개발 및 백테스트

## 라이선스

MIT

---

*"The best way to predict the future is to build it."*  
*한 명의 개발자 + 100개의 에이전트.*
