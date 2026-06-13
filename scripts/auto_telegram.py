"""
Auto Telegram Push — Scheduled daily reports via Telegram

Runs on schedule:
  - 07:00 Morning: workout routine for today
  - 09:00 Morning: investment brief + market open
  - 19:00 Evening: tweet draft ready notification
  - 21:00 Evening: system status summary

Reads CHAT_ID from data/telegram_chat_id.txt (auto-saved on /start).

Usage:
  python scripts/auto_telegram.py             # Run once (send current reports)
  python scripts/auto_telegram.py --mode health     # Send only health
  python scripts/auto_telegram.py --mode invest     # Send only investment
  python scripts/auto_telegram.py --mode status     # Send only status
"""

import os
import sys
import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not TELEGRAM_TOKEN:
    print("[AutoPush] ERROR: TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CHAT_ID_PATH = BASE_DIR / "data" / "telegram_chat_id.txt"
DRAFT_PATH = BASE_DIR / "data" / "tweet_draft.json"
MEMO_PATH = BASE_DIR / "JSM-memo.md"
WIKI_PATH = Path("C:/Users/Gram/Desktop/jsm obsidian/jsm personal agents (obsidian files)/Agents/2_Wiki")

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def get_chat_id() -> int:
    if not CHAT_ID_PATH.exists():
        raise RuntimeError(
            "Chat ID not found. Send /start to @ttttooonny_bot on Telegram first."
        )
    return int(CHAT_ID_PATH.read_text().strip())


def send_message(chat_id: int, text: str):
    if len(text) > 4096:
        text = text[:4090] + "..."
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

def generate_health_report() -> str:
    """Generate today's workout routine report."""
    now = datetime.now()
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    today_str = now.strftime("%Y-%m-%d")

    # Try to find today's workout in memo
    if MEMO_PATH.exists():
        content = MEMO_PATH.read_text(encoding="utf-8")
        sections = content.split("## [")
        for s in sections:
            if s.startswith(today_str) and any(kw in s for kw in ["운동", "헬스", "루틴"]):
                lines = [l.strip("- ").strip() for l in s.split("\n")[1:15] if l.strip()]
                routine = "\n".join(f"  {i+1}. {l}" for i, l in enumerate(lines) if l)
                if routine:
                    return f"<b>오늘의 운동</b> | {now.strftime('%m/%d')} ({weekday_kr})\n\n{routine}"
                break

    # Fallback: weekly template based on day
    templates = {
        0: "월요일 — 데이터구조 + Mamba\n  스쿼트 3x8, 벤치프레스 3x8, 바벨로우 3x10\n  복근 3x15",
        1: "화요일 — Dynamics + 데이터구조\n  데드리프트 3x8, OHP 3x8, 풀업 3x10\n  사이드레터럴레이즈 3x12",
        2: "수요일 — Mamba + Dynamics\n  스쿼트 3x8, 인클라인벤치 3x8, RDL 3x10\n  암컬 3x12",
        3: "목요일 — Dynamics + 데이터구조\n  데드리프트 3x8, 딥스 3x10, 바벨로우 3x10\n  페이스풀 3x15",
        4: "금요일 — Mamba + 버퍼\n  스쿼트 3x8, 벤치프레스 3x8, 풀업 3x10\n  복근 3x15",
        5: "토요일 — 자율 / 축구\n  유산소 또는 가벼운 전신 운동",
        6: "일요일 — 휴식\n  스트레칭 + 다음 주 루틴 정비",
    }
    default = templates.get(now.weekday(), "오늘은 휴식입니다.")

    return f"<b>오늘의 운동</b> | {now.strftime('%m/%d')} ({weekday_kr})\n\n{default}\n\n<i>메모에 기록된 실제 루틴이 있으면 자동 반영됩니다.</i>"


def generate_invest_brief() -> str:
    """Generate today's investment brief."""
    now = datetime.now()

    # Check for recent investment wiki pages
    wiki_items = []
    keywords = ["투자", "invest", "경제", "ETF", "S&P", "BTC", "비트", "코인", "매크로"]
    if WIKI_PATH.exists():
        for f in sorted(WIKI_PATH.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            name = f.name
            if any(kw in name.lower() for kw in keywords):
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                wiki_items.append(f"  - {f.stem} ({mtime.strftime('%m/%d')})")
        wiki_items = wiki_items[:3]

    # Daily checklist
    lines = [
        f"<b>투자 브리핑</b> | {now.strftime('%m/%d')}",
        "",
        "상시 체크:",
        "  - S&P500 지수 방향성",
        "  - Fed 금리 / CME FedWatch",
        "  - BTC 8시간봉 (자동매매 봇)",
        "  - 원/달러 환율",
    ]

    if wiki_items:
        lines.append("\n최근 위키 업데이트:")
        lines.extend(wiki_items)

    lines.append(f"\n<i>ISA 200만원 8월 집행 예정 | .env DRY_RUN=false 확인</i>")

    return "\n".join(lines)


def generate_status_report() -> str:
    """Generate system status summary."""
    now = datetime.now()

    parts = [f"<b>시스템 상태</b> | {now.strftime('%m/%d %H:%M')}"]

    # Tweet draft
    if DRAFT_PATH.exists():
        draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        approved = "승인 완료" if draft.get("approved") else "검토 필요"
        parts.append(f"\n트윗: {approved}")
    else:
        parts.append("\n트윗: 미생성")

    # BTC bot status (check if dry run)
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    parts.append(f"BTC봇: {'시뮬레이션' if dry_run else '실거래'} 모드")

    # Wiki count
    if WIKI_PATH.exists():
        wiki_count = len(list(WIKI_PATH.glob("*.md")))
        parts.append(f"위키: {wiki_count}페이지")

    parts.append("\n/test 로 명령어 목록 확인")

    return "\n".join(parts)


def notify_tweet_ready():
    """Send notification that today's tweet draft is ready for review."""
    if not DRAFT_PATH.exists():
        return False

    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    if draft.get("approved"):
        return False  # Already approved, no need to notify

    chat_id = get_chat_id()
    text = (
        "오늘의 트윗 초안이 준비되었습니다:\n\n"
        f"<blockquote>{draft['tweet']}</blockquote>\n\n"
        "/tweet 으로 확인 후 승인/거절"
    )
    send_message(chat_id, text)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Auto Telegram Push")
    parser.add_argument("--mode", choices=["health", "invest", "status", "tweet", "all"],
                        default="all", help="Which report to send")
    args = parser.parse_args()

    try:
        chat_id = get_chat_id()
    except RuntimeError as e:
        print(f"[AutoPush] {e}")
        return

    print(f"[AutoPush] Sending to chat_id={chat_id}, mode={args.mode}")

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
        print(f"[AutoPush] Tweet: {'sent' if notified else 'skipped (no draft or already approved)'}")

    if args.mode in ("status", "all"):
        msg = generate_status_report()
        result = send_message(chat_id, msg)
        print(f"[AutoPush] Status: {result.get('ok')}")

    print("[AutoPush] Done")


if __name__ == "__main__":
    main()
