"""
Telegram Bot — Mobile Interface for JSM Personal Agent System

Commands:
  /start   - Welcome message
  /tweet   - Show today's tweet draft (approve/reject)
  /health  - Show today's workout routine
  /invest  - Show today's investment brief
  /wiki    - Search wiki for a topic: /wiki <query>
  /approve - Approve and queue today's tweet for posting
  /reject  - Reject today's tweet and request regeneration
  /status  - System status check

Setup:
  1. Create bot via @BotFather on Telegram → get TOKEN
  2. Set TELEGRAM_BOT_TOKEN in .env
  3. Run: python scripts/telegram_bot.py
  4. (For persistent run: use Windows Task Scheduler or run as daemon)
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
    print("[TelegramBot] ERROR: TELEGRAM_BOT_TOKEN not set in .env")
    print("  1. Create a bot via @BotFather on Telegram")
    print("  2. Copy the token to .env as TELEGRAM_BOT_TOKEN=...")
    sys.exit(1)

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DRAFT_PATH = BASE_DIR / "data" / "tweet_draft.json"
MEMO_PATH = BASE_DIR / "JSM-memo.md"
WIKI_PATH = Path("C:/Users/Gram/Desktop/jsm obsidian/jsm personal agents (obsidian files)/Agents/2_Wiki")

# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Send a message to a Telegram chat."""
    # Truncate to Telegram's limit
    if len(text) > 4096:
        text = text[:4090] + "..."

    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        },
        timeout=15,
    )
    return resp.json()


def send_keyboard(chat_id: int, text: str, buttons: list[list[str]]):
    """Send a message with inline keyboard buttons."""
    inline_keyboard = []
    for row in buttons:
        inline_keyboard.append([{"text": btn, "callback_data": btn} for btn in row])

    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": inline_keyboard},
        },
        timeout=15,
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_start(chat_id: int):
    welcome = (
        "JSM Personal Agent System\n\n"
        "Commands:\n"
        "/tweet — 오늘의 트윗 초안\n"
        "/health — 오늘의 운동 루틴\n"
        "/invest — 오늘의 투자 브리핑\n"
        "/wiki <query> — 위키 검색\n"
        "/status — 시스템 상태\n"
    )
    send_message(chat_id, welcome)


def cmd_tweet(chat_id: int):
    """Show today's tweet draft with approve/reject buttons."""
    if not DRAFT_PATH.exists():
        send_message(chat_id, "아직 오늘의 트윗 초안이 생성되지 않았습니다.\n잠시 후 다시 시도하거나 /status 로 확인해주세요.")
        return

    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))

    if draft.get("approved"):
        text = f"오늘의 트윗 (승인 완료):\n\n<blockquote>{draft['tweet']}</blockquote>\n\n주제: {draft.get('topic_source', 'unknown')}"
        send_message(chat_id, text)
    else:
        text = (
            f"오늘의 트윗 초안:\n\n"
            f"<blockquote>{draft['tweet']}</blockquote>\n\n"
            f"주제: {draft.get('topic_source', 'unknown')}\n"
            f"생성 시간: {draft.get('generated_at', '?')}"
        )
        send_keyboard(chat_id, text, [["승인 (Approved)", "거절 (Reject)"]])


def cmd_health(chat_id: int):
    """Show today's workout routine from JSM-memo.md."""
    if not MEMO_PATH.exists():
        send_message(chat_id, "메모 파일을 찾을 수 없습니다.")
        return

    content = MEMO_PATH.read_text(encoding="utf-8")
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Find today's entries
    sections = content.split("## [")
    today_section = None
    for s in sections:
        if s.startswith(today_str):
            today_section = s
            break

    if today_section and ("운동" in today_section or "헬스" in today_section or "루틴" in today_section):
        lines = today_section.strip().split("\n")[1:10]  # Skip date line
        msg = "오늘의 운동:\n" + "\n".join(f"- {l.strip('- ')}" for l in lines if l.strip())
    else:
        # Fallback: show most recent workout entry
        workout_sections = []
        for s in sections:
            if "운동" in s or "헬스" in s or "루틴" in s:
                workout_sections.append(s)
        if workout_sections:
            latest = workout_sections[0]
            lines = latest.strip().split("\n")[1:10]
            date_match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", latest)
            date_str = date_match.group(1) if date_match else "?"
            msg = f"가장 최근 운동 기록 ({date_str}):\n" + "\n".join(f"- {l.strip('- ')}" for l in lines if l.strip())
        else:
            msg = "아직 운동 기록이 없습니다."

    send_message(chat_id, msg)


def cmd_invest(chat_id: int):
    """Show investment brief from wiki or generate a quick summary."""
    # Try to find recent investment-related wiki pages
    invest_pages = []
    keywords = ["투자", "invest", "경제", "ETF", "S&P", "BTC", "비트"]

    if WIKI_PATH.exists():
        for f in sorted(WIKI_PATH.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            name_lower = f.name.lower()
            if any(kw.lower() in name_lower for kw in keywords):
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if (datetime.now() - mtime).days <= 7:
                    invest_pages.append(f"- {f.stem} ({mtime.strftime('%m/%d')})")

    if invest_pages:
        msg = "최근 투자 관련 위키 업데이트:\n" + "\n".join(invest_pages[:5])
    else:
        # Fallback quick summary
        msg = (
            "투자 브리핑 (자동 생성):\n\n"
            f"{datetime.now().strftime('%Y-%m-%d')}\n"
            "- CPI 발표 (6/10) 결과 확인 필요\n"
            "- S&P500 ETF 매수 타이밍 검토\n"
            "- ISA 200만원 8월 집행 준비\n"
            "- BTC 봇: /status 로 확인"
        )

    send_message(chat_id, msg)


def cmd_wiki(chat_id: int, query: str):
    """Search wiki for a topic."""
    if not query:
        send_message(chat_id, "사용법: /wiki <검색어>\n예: /wiki 의도 경제")
        return

    if not WIKI_PATH.exists():
        send_message(chat_id, "위키 경로를 찾을 수 없습니다.")
        return

    results = []
    for f in WIKI_PATH.glob("*.md"):
        if f.name in ("index.md", "log.md", "_stubs.md"):
            continue
        content = f.read_text(encoding="utf-8")
        if query.lower() in content.lower():
            # Extract first paragraph
            lines = [l for l in content.split("\n") if l.strip() and not l.startswith("---") and not l.startswith("#") and not l.startswith("kind:") and not l.startswith("form:") and not l.startswith("topics:") and not l.startswith("subject:") and not l.startswith("source-types:") and not l.startswith("confidence:") and not l.startswith("created:") and not l.startswith("updated:")]
            snippet = lines[0][:200] if lines else "(내용 없음)"
            results.append((f.stem, snippet))

    if results:
        msg = f"'{query}' 검색 결과 ({len(results)}개):\n\n"
        for title, snippet in results[:5]:
            msg += f"<b>{title}</b>\n{snippet}\n\n"
    else:
        msg = f"'{query}'에 대한 검색 결과가 없습니다."

    send_message(chat_id, msg)


def cmd_status(chat_id: int):
    """System status overview."""
    now = datetime.now()

    # Check tweet draft
    if DRAFT_PATH.exists():
        draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        draft_status = f"트윗 초안: {'승인 완료' if draft.get('approved') else '검토 필요'} ({draft.get('generated_at', '?')})"
    else:
        draft_status = "트윗 초안: 아직 생성되지 않음"

    # Check memo
    memo_exists = "있음" if MEMO_PATH.exists() else "없음"

    # Check wiki
    wiki_count = len(list(WIKI_PATH.glob("*.md"))) if WIKI_PATH.exists() else 0

    msg = (
        f"시스템 상태 ({now.strftime('%H:%M')}):\n\n"
        f"- {draft_status}\n"
        f"- 위키 페이지: {wiki_count}개\n"
        f"- 메모 파일: {memo_exists}\n"
        f"- 현재 시간: {now.strftime('%Y-%m-%d %H:%M')}"
    )
    send_message(chat_id, msg)


def handle_callback(callback_data: str, chat_id: int, message_id: int):
    """Handle inline keyboard button presses."""
    if "승인" in callback_data:
        if DRAFT_PATH.exists():
            draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
            draft["approved"] = True
            DRAFT_PATH.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
            send_message(chat_id, f"트윗 승인 완료!\n\n<blockquote>{draft['tweet']}</blockquote>\n\n밤 9시에 자동 포스팅됩니다.")
        else:
            send_message(chat_id, "오류: 트윗 초안을 찾을 수 없습니다.")

    elif "거절" in callback_data:
        if DRAFT_PATH.exists():
            DRAFT_PATH.unlink()
        send_message(chat_id, "트윗이 거절되었습니다. 새로운 초안이 필요하면 /tweet 으로 요청해주세요.")


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

def main():
    print("[TelegramBot] Starting...")
    print(f"[TelegramBot] API: {API_BASE}")
    print("[TelegramBot] Commands: /start /tweet /health /invest /wiki /status")

    last_update_id = 0

    while True:
        try:
            resp = requests.get(
                f"{API_BASE}/getUpdates",
                params={
                    "offset": last_update_id + 1,
                    "timeout": 30,
                },
                timeout=35,
            )
            data = resp.json()

            if not data.get("ok"):
                print(f"[TelegramBot] API error: {data}")
                continue

            for update in data.get("result", []):
                last_update_id = update["update_id"]

                # Handle callback queries (button presses)
                if "callback_query" in update:
                    cb = update["callback_query"]
                    handle_callback(
                        cb.get("data", ""),
                        cb["message"]["chat"]["id"],
                        cb["message"]["message_id"],
                    )
                    # Answer callback query
                    requests.post(
                        f"{API_BASE}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                        timeout=5,
                    )
                    continue

                # Handle messages
                if "message" not in update:
                    continue

                msg = update["message"]
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")

                print(f"[TelegramBot] Received: '{text}' from {chat_id}")

                if text.startswith("/start"):
                    cmd_start(chat_id)
                elif text.startswith("/tweet"):
                    cmd_tweet(chat_id)
                elif text.startswith("/health"):
                    cmd_health(chat_id)
                elif text.startswith("/invest"):
                    cmd_invest(chat_id)
                elif text.startswith("/status"):
                    cmd_status(chat_id)
                elif text.startswith("/wiki"):
                    query = text.replace("/wiki", "").strip()
                    cmd_wiki(chat_id, query)
                else:
                    send_message(chat_id, "명령어를 인식할 수 없습니다.\n/start 로 명령어 목록을 확인해주세요.")

        except requests.exceptions.Timeout:
            continue
        except KeyboardInterrupt:
            print("[TelegramBot] Shutting down...")
            break
        except Exception as e:
            print(f"[TelegramBot] Error: {e}")
            import time
            time.sleep(5)


if __name__ == "__main__":
    main()
