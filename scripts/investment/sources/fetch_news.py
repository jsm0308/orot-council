"""
Module 4: Economic News Collector
Aggregates economic and financial news from free RSS feeds.

Sources:
    - Reuters Business News RSS
    - CNBC Top News RSS
    - Bloomberg Markets RSS
    - Yonhap News Economy RSS (Korean)

Usage:
    python fetch_news.py                  # Fetch all sources
    python fetch_news.py --source reuters  # Fetch specific source
    python fetch_news.py --output news_data.json

Output: data/news_data.json
"""

import os
import json
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------------------------------------------------------------------
# RSS Feed Registry
# ---------------------------------------------------------------------------

RSS_FEEDS: Dict[str, Dict[str, str]] = {
    "reuters_business": {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "language": "en",
        "category": "business"
    },
    "reuters_markets": {
        "name": "Reuters Markets",
        "url": "https://feeds.reuters.com/reuters/marketsNews",
        "language": "en",
        "category": "markets"
    },
    "cnbc_top": {
        "name": "CNBC Top News",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "language": "en",
        "category": "finance"
    },
    "marketwatch_top": {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "language": "en",
        "category": "markets"
    },
    # Korean sources
    "yonhap_economy": {
        "name": "Yonhap News Economy",
        "url": "https://www.yonhapnewstv.co.kr/browse/feed/",
        "language": "ko",
        "category": "economy"
    },
    "hankyung_headline": {
        "name": "Hankyung Headlines",
        "url": "https://www.hankyung.com/feed/headline",
        "language": "ko",
        "category": "economy"
    },
    "maeil_economy": {
        "name": "Maeil Business News",
        "url": "https://www.mk.co.kr/rss/30100041/",
        "language": "ko",
        "category": "economy"
    },
}

# Keywords to filter relevant news
RELEVANT_KEYWORDS = [
    "federal reserve", "fed", "interest rate", "inflation", "cpi", "pce",
    "gdp", "recession", "treasury", "bond", "yield", "stock market",
    "s&p 500", "nasdaq", "dow jones", "oil price", "dollar", "euro",
    "한국은행", "금리", "기준금리", "물가", "소비자물가", "환율", "원달러",
    "수출", "반도체", "코스피", "코스닥", "ETF", "ISA", "증시",
    "fomc", "ecb", "boj", "bank of korea", "powell", "jay powell",
    "비트코인", "bitcoin", "crypto", "btc",
]


def _fetch_rss(url: str, timeout: int = 15) -> Optional[List[Dict]]:
    """Fetch and parse an RSS feed."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        items = []

        for item in root.iter("item"):
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            description = item.find("description")

            entry = {
                "title": title.text.strip() if title is not None and title.text else "",
                "link": link.text.strip() if link is not None and link.text else "",
                "published": pub_date.text.strip() if pub_date is not None and pub_date.text else "",
            }

            if description is not None and description.text:
                # Strip HTML tags for clean text
                desc = description.text
                import re
                clean_desc = re.sub(r"<[^>]+>", "", desc)
                entry["summary"] = clean_desc.strip()[:300]

            if entry["title"]:
                items.append(entry)

        return items if items else None
    except ET.ParseError as e:
        print(f"[WARN] RSS parse error for {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[WARN] RSS fetch failed for {url}: {e}")
        return None


def is_relevant(title: str, summary: str = "") -> bool:
    """Filter articles by keyword relevance."""
    text = (title + " " + summary).lower()
    return any(kw in text for kw in RELEVANT_KEYWORDS)


def fetch_all_feeds(filter_relevant: bool = True) -> Dict:
    """Fetch all registered RSS feeds."""
    result = {
        "generated_at": datetime.now().isoformat(),
        "feeds": {},
        "total_articles": 0,
        "relevant_articles": 0,
    }

    for feed_id, meta in RSS_FEEDS.items():
        print(f"[FETCH] {meta['name']}...")
        items = _fetch_rss(meta["url"])

        if items is None:
            result["feeds"][feed_id] = {"name": meta["name"], "status": "error", "articles": []}
            continue

        if filter_relevant:
            items = [i for i in items if is_relevant(i["title"], i.get("summary", ""))]

        result["feeds"][feed_id] = {
            "name": meta["name"],
            "language": meta["language"],
            "category": meta["category"],
            "status": "ok",
            "article_count": len(items),
            "articles": items[:20],  # Cap at 20 per feed
        }
        result["total_articles"] += len(items)
        if filter_relevant:
            result["relevant_articles"] += len(items)

    return result


def save_output(data: Dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch economic news from RSS feeds")
    parser.add_argument("--source", "-s", type=str, help="Fetch specific source (e.g., reuters_business)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path")
    parser.add_argument("--all", action="store_true", help="Include non-relevant articles")
    args = parser.parse_args()

    output_path = args.output or os.path.join(DATA_DIR, "news_data.json")

    print("=== JSM News Collector ===\n")

    if args.source:
        if args.source not in RSS_FEEDS:
            print(f"[ERROR] Unknown source: {args.source}")
            print(f"Available: {', '.join(RSS_FEEDS.keys())}")
            return
        meta = RSS_FEEDS[args.source]
        items = _fetch_rss(meta["url"])
        if items:
            filter_relevant = not args.all
            if filter_relevant:
                items = [i for i in items if is_relevant(i["title"], i.get("summary", ""))]
            print(f"[{meta['name']}] {len(items)} articles")
            for i, item in enumerate(items[:15], 1):
                print(f"  {i:2d}. {item['title'][:100]}")
        return

    data = fetch_all_feeds(filter_relevant=not args.all)
    saved = save_output(data, output_path)

    print(f"\n[DONE] Total: {data['total_articles']} articles ({data['relevant_articles']} relevant)")
    print(f"[SAVED] {saved}")

    # Top headlines summary
    print("\n=== Top Headlines ===")
    count = 0
    for feed_id, feed_data in data["feeds"].items():
        for article in feed_data.get("articles", [])[:5]:
            if count >= 15:
                break
            print(f"  [{feed_data['name']}] {article['title'][:100]}")
            count += 1


if __name__ == "__main__":
    main()
