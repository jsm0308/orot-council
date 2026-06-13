"""
Auto Telegram Push v2 — DeepSeek-powered daily briefs

Investment: Real market data + DeepSeek analysis
Health: Personalized workout guidance
Status: System summary

Runs on GitHub Actions (PC not required).
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not TELEGRAM_TOKEN:
    print("[AutoPush] ERROR: TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------
DRAFT_PATH = BASE_DIR / "data" / "tweet_draft.json"
CHAT_ID_PATH = BASE_DIR / "data" / "telegram_chat_id.txt"

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com") if DEEPSEEK_KEY else None

def get_chat_id() -> int:
    env_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if env_id:
        return int(env_id)
    if CHAT_ID_PATH.exists():
        return int(CHAT_ID_PATH.read_text().strip())
    raise RuntimeError("No chat_id found")

def send_message(chat_id: int, text: str):
    if len(text) > 4096:
        text = text[:4090] + "..."
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        print(f"[AutoPush] Telegram error: {data.get('description', data)}")
    return data

# ---------------------------------------------------------------------------
# Market Data Fetchers (free APIs, no keys needed on GitHub runner)
# ---------------------------------------------------------------------------

def fetch_market_snapshot() -> dict:
    """Fetch key market data from free APIs."""
    data = {"fetched_at": datetime.now().isoformat(), "errors": []}

    # S&P500, NASDAQ, KOSPI via Yahoo Finance (no key needed)
    try:
        tickers = {"SPY": "S&P500 ETF", "QQQ": "NASDAQ100 ETF", "^KS11": "KOSPI"}
        for symbol, label in tickers.items():
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            if resp.status_code == 200:
                result = resp.json()["chart"]["result"][0]
                meta = result["meta"]
                quotes = result["indicators"]["quote"][0]
                close_prices = [x for x in quotes["close"] if x is not None]
                if len(close_prices) >= 2:
                    prev_close = close_prices[-2]
                    current = meta["regularMarketPrice"]
                    change_pct = ((current - prev_close) / prev_close) * 100
                    data[label] = {
                        "price": current,
                        "change_pct": round(change_pct, 2),
                        "prev_close": prev_close,
                    }
                elif "regularMarketPrice" in meta and "previousClose" in meta:
                    data[label] = {
                        "price": meta["regularMarketPrice"],
                        "change_pct": round(meta.get("regularMarketChangePercent", 0), 2),
                    }
            else:
                data["errors"].append(f"{label}: HTTP {resp.status_code}")
    except requests.exceptions.Timeout:
        data["errors"].append("Yahoo: timeout")
    except Exception as e:
        data["errors"].append(f"Yahoo: {str(e)[:80]}")

    # Fear & Greed Index (crypto)
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        if resp.status_code == 200:
            fg = resp.json()["data"][0]
            data["fear_greed"] = {"value": int(fg["value"]), "classification": fg["value_classification"]}
    except Exception as e:
        data["errors"].append(f"FearGreed: {str(e)[:60]}")

    # USD/KRW via free API
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        if resp.status_code == 200:
            krw = resp.json()["rates"]["KRW"]
            data["usd_krw"] = round(krw, 1)
    except Exception as e:
        data["errors"].append(f"FX: {str(e)[:60]}")

    # CME FedWatch (current rate probabilities)
    try:
        resp = requests.get(
            "https://www.cmegroup.com/CmeWS/mvc/AtmOptions/AtmOptionChains",
            params={"ticker": "ZQ", "productName": "30-Day Federal Funds"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        # CME often blocks non-browser, try simplified approach
    except:
        pass

    return data


def fetch_btc_status() -> dict:
    """Quick BTC price check via Upbit public API."""
    try:
        resp = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC", timeout=10)
        if resp.status_code == 200:
            ticker = resp.json()[0]
            return {
                "price": int(ticker["trade_price"]),
                "change_pct": round(float(ticker["signed_change_rate"]) * 100, 2),
                "volume_24h": round(float(ticker["acc_trade_price_24h"]) / 1e8, 1),
            }
    except Exception as e:
        return {"error": str(e)[:80]}
    return {"error": "no data"}


# ---------------------------------------------------------------------------
# DeepSeek-powered generators
# ---------------------------------------------------------------------------

def generate_invest_brief() -> str:
    """DeepSeek-generated investment brief with real market data.
    On Sundays, generates a weekly deep-dive report instead of daily brief."""
    if not client:
        return fallback_invest_brief()

    now = datetime.now()
    is_sunday = now.weekday() == 6
    market = fetch_market_snapshot()
    btc = fetch_btc_status()

    if is_sunday:
        system = """당신은 JSM의 개인 투자 리서치 애널리스트다. 월스트리트 셀사이드 방법론을 따르며, 한국어로 응답.
사용자 프로필:
- 미래에셋증권 ISA 보유, 8월 말 200만원 S&P500 ETF 중심 코어-위성 전략 집행 예정
- 투자 성향: 장기 성장 (5년+), 중간 변동성 감내
- 모든 데이터 포인트에 출처를 명시할 것 (번호 매겨서 하단에 주석)

주간 보고서 형식 (한국어 1,500자 내외):
## 1. 포트폴리오 상태
- 현재 보유, 현금 비중, 리밸런싱 필요 여부

## 2. 이번 주 주목할 섹터/종목 (2-3개)
- 각각 3줄 근거 + JSM과의 연관성 1줄

## 3. 매크로 환경
- Fed 금리, CPI, VIX, 원/달러, 10년물 금리 등 핵심 지표
- 이번 주 주요 이벤트

## 4. 액션 추천 (2-3개 옵션, 그중 하나 선택해 설득)
- 옵션 A/B with 근거, 리스크, 예상 수익

## 5. 리스크/손실 제한선

근거 없는 주장 금지. 베어 케이스 반드시 포함. 확률적 언어 사용."""
    else:
        system = """당신은 JSM의 개인 투자 리서치 애널리스트다.
한국어로 응답. 사용자 프로필:
- 미래에셋증권 ISA 보유, 8월 말 200만원 S&P500 ETF 중심 코어-위성 전략 집행 예정
- 현재 보유: TIGER 미국S&P500 (진행 중)
- 투자 성향: 장기 성장 (5년+), 중간 변동성 감내

매일 아침 브리핑 형식:
1. 주요 지수 스냅샷 (S&P500, NASDAQ, KOSPI, BTC, 원/달러)
2. 오늘 주목할 포인트 1-2개 (데이터에 근거, 추측 금지)
3. JSM 포트폴리오 관련 코멘트 (ISA 집행 타이밍, S&P500 매수 적기 여부)
4. 한 줄 요약

300-400자 내외. 불필요한 수식어 금지. 데이터 기반. 근거 없는 낙관/비관 금지."""

    user = f"다음 시장 데이터를 기반으로 오늘({datetime.now().strftime('%Y-%m-%d')}) 아침 투자 브리핑을 작성해라:\n\n```json\n{json.dumps(market, ensure_ascii=False, indent=2)}\n```\n\n비트코인: {json.dumps(btc, ensure_ascii=False)}"

    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            max_tokens=800,
        )
        content = resp.choices[0].message.content
        print(f"[AutoPush] DeepSeek invest: {len(content) if content else 'None'} chars")
        if not content or not content.strip():
            print("[AutoPush] Invest: empty response from DeepSeek, using fallback")
            return fallback_invest_brief()
        brief = content.strip()
        return f"투자 브리핑 | {now.strftime('%m/%d %H:%M')}\n{brief}"
    except Exception as e:
        print(f"[AutoPush] DeepSeek invest error: {e}")
        return fallback_invest_brief()


def fallback_invest_brief() -> str:
    """Fallback when DeepSeek unavailable."""
    market = fetch_market_snapshot()
    btc = fetch_btc_status()
    lines = [f"투자 브리핑 | {datetime.now().strftime('%m/%d %H:%M')}", ""]

    if "S&P500 ETF" in market:
        sp = market["S&P500 ETF"]
        lines.append(f"S&P500: {sp['price']:.0f} ({sp['change_pct']:+.2f}%)")
    if "NASDAQ100 ETF" in market:
        nq = market["NASDAQ100 ETF"]
        lines.append(f"NASDAQ100: {nq['price']:.0f} ({nq['change_pct']:+.2f}%)")
    if "KOSPI" in market:
        ks = market["KOSPI"]
        lines.append(f"KOSPI: {ks['price']:.0f} ({ks['change_pct']:+.2f}%)")
    if "usd_krw" in market:
        lines.append(f"USD/KRW: {market['usd_krw']}")
    if isinstance(btc, dict) and "price" in btc:
        lines.append(f"BTC: {btc['price']:,}원 ({btc.get('change_pct', 0):+.2f}%)")
    if "fear_greed" in market:
        fg = market["fear_greed"]
        lines.append(f"공포·탐욕: {fg['value']} ({fg['classification']})")

    lines.append("\nISA 200만원 8월 집행 예정")
    return "\n".join(lines)


def generate_health_report() -> str:
    """DeepSeek-generated personalized workout guidance."""
    if not client:
        return fallback_health_report()

    now = datetime.now()
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

    system = """당신은 JSM의 개인 운동 코치다. 한국어로 응답. 지시조(명령문)로 말할 것. "~하세요" 금지. "~해라" "~한다"로 명령.

JSM 프로필:
- 20대 남성, 근비대 + 축구 퍼포먼스 듀얼 골
- 주 4-5회 웨이트 트레이닝, 운동 시간대: 21:00-22:30
- 약점: 어깨, 팔 (보완 필요) — 어깨/팔 운동에 ⭐ 표시
- 비대칭: 골반 비대칭 교정 운동 포함
- 운동 순서: 워밍업을 실제 세트와 섞어서 실행 순서대로 기록
- 현재 루틴: 2분할 (상체/하체) + 약점 보강

매일 아침 전송할 운동 오더 형식:
1. 워밍업 (공통: 90/90 스트레칭, 클램쉘, 데드버그, 힙스러스트 — 5분)
2. 메인 운동 (종목, 세트x렙, 휴식 시간, 목적)
3. 보조 운동
4. 약점 보강 (어깨/팔 — ⭐ 표시)
5. 오늘의 집중 포인트 1개 (자세 코칭, 템포, 마인드머슬커넥션)

구체적으로 써라. 예: "벤치프레스 3x8 60kg, 휴식 90초, 어깨 후인 금지" """

    user = f"오늘은 {now.strftime('%Y년 %m월 %d일')} {weekday_kr}요일이다. JSM의 현재 운동 루틴에 맞춰 오늘의 운동 가이드를 작성해라."

    try:
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.5,
            max_tokens=500,
        )
        content = resp.choices[0].message.content
        print(f"[AutoPush] DeepSeek health: {len(content) if content else 'None'} chars")
        if not content or not content.strip():
            print("[AutoPush] Health: empty response from DeepSeek, using fallback")
            return fallback_health_report()
        guide = content.strip()
        return f"오늘의 운동 | {now.strftime('%m/%d')} ({weekday_kr})\n{guide}"
    except Exception as e:
        print(f"[AutoPush] DeepSeek health error: {e}")
        return fallback_health_report()


def fallback_health_report() -> str:
    now = datetime.now()
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

    templates = {
        0: "월요일 — 상체 A + 데이터구조\n  벤치프레스 3x8 (메인)\n  바벨로우 3x8-10\n  OHP 3x8\n  사이드레터럴레이즈 3x12\n  바벨컬 3x10\n  복근 3x15",
        1: "화요일 — 하체 A + Dynamics\n  스쿼트 3x8 (메인)\n  RDL 3x8-10\n  레그프레스 3x10\n  레그컬 3x12\n  카프레이즈 3x15",
        2: "수요일 — 상체 B + Mamba\n  인클라인벤치 3x8 (메인)\n  풀업 3x10\n  딥스 3x10\n  페이스풀 3x12\n  해머컬 3x10",
        3: "목요일 — 하체 B + Dynamics\n  데드리프트 3x5-8 (메인)\n  프론트스쿼트 3x8\n  런지 3x10/leg\n  레그익스텐션 3x12",
        4: "금요일 — 약점 보강 + Mamba\n  밀리터리프레스 3x8\n  얼터네이트 덤벨컬 3x10\n  트라이셉스 푸시다운 3x12\n  리어델트 플라이 3x15",
        5: "토요일 — 유산소 / 축구\n  45-60분 축구 또는 인터벌 러닝\n  코어 + 스트레칭",
        6: "일요일 — 완전 휴식\n  폼롤러 + 스트레칭\n  다음 주 루틴 리뷰",
    }
    return f"오늘의 운동 | {now.strftime('%m/%d')} ({weekday_kr})\n\n{templates.get(now.weekday(), '휴식')}"


def generate_status_report() -> str:
    now = datetime.now()

    parts = [f"시스템 상태 | {now.strftime('%m/%d %H:%M')}"]

    # Tweet
    if DRAFT_PATH.exists():
        draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        approved = "승인 완료" if draft.get("approved") else "검토 필요"
        parts.append(f"\n트윗: {approved}")
    else:
        parts.append("\n트윗: 미생성")

    # BTC
    btc = fetch_btc_status()
    if "price" in btc:
        parts.append(f"BTC: {btc['price']:,}원 ({btc.get('change_pct', 0):+.2f}%)")

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    parts.append(f"BTC봇: {'시뮬레이션' if dry_run else '실거래'} 모드")
    parts.append("\n/start 로 명령어 확인")

    return "\n".join(parts)


def notify_tweet_ready():
    if not DRAFT_PATH.exists():
        return False
    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    if draft.get("approved"):
        return False
    chat_id = get_chat_id()
    text = f"오늘의 트윗 초안:\n\n{draft['tweet']}\n\n/tweet 으로 확인 후 승인/거절"
    send_message(chat_id, text)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["health", "invest", "status", "tweet", "all"], default="all")
    args = parser.parse_args()

    try:
        chat_id = get_chat_id()
    except RuntimeError as e:
        print(f"[AutoPush] {e}")
        return

    print(f"[AutoPush] mode={args.mode}, chat_id={chat_id}, deepseek={'ready' if client else 'unavailable'}")

    if args.mode in ("health", "all"):
        msg = generate_health_report()
        result = send_message(chat_id, msg)
        print(f"[AutoPush] Health: {result.get('ok')}")

    if args.mode in ("invest", "all"):
        msg = generate_invest_brief()
        result = send_message(chat_id, msg)
        print(f"[AutoPush] Invest: {result.get('ok')}")

    if args.mode in ("tweet", "all"):
        notified = notify_tweet_ready()
        print(f"[AutoPush] Tweet: {'sent' if notified else 'skipped'}")

    if args.mode in ("status", "all"):
        msg = generate_status_report()
        result = send_message(chat_id, msg)
        print(f"[AutoPush] Status: {result.get('ok')}")

    print("[AutoPush] Done")


if __name__ == "__main__":
    main()
