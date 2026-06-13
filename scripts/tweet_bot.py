"""
Daily Tweet Draft Generator
Runs once daily (night). Generates a tweet draft based on:
1. Recent podcast consumption (from JSM-memo.md)
2. Recent wiki activity (new concepts/insights)
3. Coach-suggested reflection topics

Draft is saved to data/tweet_draft.json for review via Telegram bot.
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MEMO_PATH = BASE_DIR / "JSM-memo.md"
WIKI_PATH = Path("C:/Users/Gram/Desktop/jsm obsidian/jsm personal agents (obsidian files)/Agents/2_Wiki")
DRAFT_PATH = BASE_DIR / "data" / "tweet_draft.json"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# ---------------------------------------------------------------------------
# Source detectors
# ---------------------------------------------------------------------------

def detect_podcast_from_memo(memo_path: Path) -> list[str]:
    """Scan JSM-memo.md for recent podcast mentions (last 48 hours)."""
    if not memo_path.exists():
        return []

    content = memo_path.read_text(encoding="utf-8")
    cutoff = datetime.now() - timedelta(hours=48)

    podcasts = []
    # Find sections with podcast-related keywords
    podcast_section = False
    for line in content.split("\n"):
        if line.startswith("## ["):
            podcast_section = False
            # Check date
            try:
                date_str = line[4:20].strip()
                entry_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                if entry_date < cutoff:
                    continue
            except ValueError:
                continue

        if any(kw in line.lower() for kw in ["podcast", "afr", "팟캐스트", "유튜브", "youtube"]):
            podcast_section = True
            podcasts.append(line.strip("- ").strip())

    return podcasts


def detect_recent_wiki_activity() -> list[dict]:
    """Find recently created wiki pages (last 7 days) that could be tweet material."""
    if not WIKI_PATH.exists():
        return []

    recent = []
    cutoff = datetime.now() - timedelta(days=7)

    for f in WIKI_PATH.glob("*.md"):
        if f.name in ("index.md", "log.md", "_stubs.md"):
            continue
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime >= cutoff:
            content = f.read_text(encoding="utf-8")
            # Extract first meaningful sentence after frontmatter
            lines = content.split("\n")
            summary = ""
            in_body = False
            for line in lines:
                if line.strip() == "---":
                    if in_body:
                        continue
                    in_body = True
                    continue
                if in_body and line.startswith("#"):
                    title = line.lstrip("#").strip()
                    continue
                if in_body and line.strip() and not line.startswith("---"):
                    if len(line) > 30:
                        summary = line.strip()
                        break

            recent.append({
                "title": f.stem,
                "modified": mtime.isoformat(),
                "summary": summary,
            })

    recent.sort(key=lambda x: x["modified"], reverse=True)
    return recent[:5]


# ---------------------------------------------------------------------------
# Tweet prompt assembly
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are JSM, a Korean undergraduate AI/ML researcher and builder.
You post daily tweets about what you're learning, building, and thinking about.

Rules for your tweets:
- Korean with English technical terms
- 280 characters max
- One clear insight or question (not a thread)
- No emoji except sometimes a single one at the end
- Personal tone — "I learned", "I built", "I'm thinking about"
- Never sound like a generic AI tweet
- End with a question or call to thought when appropriate

Output JSON only: {"tweet": "text", "topic_source": "podcast/wiki/daily_reflection"}"""


def build_user_prompt(podcasts: list[str], wiki_pages: list[dict]) -> str:
    """Assemble context for tweet generation."""
    parts = ["Generate ONE tweet draft based on the following context. Prioritize podcast content if available.\n"]

    if podcasts:
        parts.append("## Recent Podcast Activity")
        for p in podcasts[:3]:
            parts.append(f"- {p}")

    if wiki_pages:
        parts.append("\n## Recent Wiki Activity (last 7 days)")
        for w in wiki_pages[:3]:
            parts.append(f"- {w['title']}: {w['summary'][:80]}")

    if not podcasts and not wiki_pages:
        parts.append("\n## No recent activity detected.")
        parts.append("Generate a reflective tweet about one of these topics:")
        parts.append("- What I learned from Modern Robotics this week")
        parts.append("- A question about AI agent economics")
        parts.append("- A thought on building vs studying as a student")
        parts.append("- Something about the relationship between robotics and AI")

    parts.append("\nToday's date is " + datetime.now().strftime("%Y-%m-%d"))
    parts.append("Write in Korean. Keep it under 280 characters.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_tweet_draft() -> dict:
    """Generate a tweet draft and save to file."""
    podcasts = detect_podcast_from_memo(MEMO_PATH)
    wiki_pages = detect_recent_wiki_activity()
    user_prompt = build_user_prompt(podcasts, wiki_pages)

    print("[TweetBot] Context assembled:")
    print(f"  Podcasts found: {len(podcasts)}")
    print(f"  Wiki pages found: {len(wiki_pages)}")

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=300,
        )
        content = response.choices[0].message.content

        # Extract JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            parsed = {"tweet": content.strip(), "topic_source": "auto"}

        draft = {
            "generated_at": datetime.now().isoformat(),
            "tweet": parsed.get("tweet", ""),
            "topic_source": parsed.get("topic_source", "unknown"),
            "approved": False,
            "posted_at": None,
        }

        # Save draft
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_PATH.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[TweetBot] Draft saved to {DRAFT_PATH}")
        print(f"[TweetBot] Draft: {draft['tweet'][:100]}...")
        return draft

    except Exception as e:
        print(f"[TweetBot] Error: {e}")
        # Save fallback draft
        fallback = {
            "generated_at": datetime.now().isoformat(),
            "tweet": f"오늘 하루 무엇을 배웠는가. {datetime.now().strftime('%Y.%m.%d')}",
            "topic_source": "fallback",
            "approved": False,
            "posted_at": None,
        }
        DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_PATH.write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
        return fallback


if __name__ == "__main__":
    result = generate_tweet_draft()
    print(f"\n[Result] {json.dumps(result, ensure_ascii=False, indent=2)}")
