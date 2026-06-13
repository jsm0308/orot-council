"""
Weekly Investment Report Generator
Collects all source data (macro, sector, KRX, news, flows) and calls DeepSeek to
generate a complete weekly investment report following the template in report_template.md.

Usage:
    python generate_weekly.py                       # Generate full report
    python generate_weekly.py --dry-run              # Assemble prompt without LLM call
    python generate_weekly.py --output-dir ./reports # Save to custom directory

Output:
    Console: Full report text
    File: data/weekly_report_YYYY-MM-DD.md
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime
from typing import Dict, Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

SOURCES_DIR = os.path.join(BASE_DIR, "scripts", "investment", "sources")
REPORTS_DIR = os.path.join(BASE_DIR, "scripts", "investment", "reports")
DATA_DIR = os.path.join(BASE_DIR, "data")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# ---------------------------------------------------------------------------
# Data Collection (run fetch scripts)
# ---------------------------------------------------------------------------

def run_fetch_script(script_name: str) -> Optional[Dict]:
    """Run a fetch script and load its output JSON."""
    script_path = os.path.join(SOURCES_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"[WARN] Script not found: {script_path}")
        return None

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=SOURCES_DIR
        )
        if result.returncode != 0:
            print(f"[WARN] {script_name} failed: {result.stderr[:200]}")
            return None

        # Determine output path
        data_map = {
            "fetch_macro.py": os.path.join(DATA_DIR, "macro_data.json"),
            "fetch_sector.py": os.path.join(DATA_DIR, "sector_data.json"),
            "fetch_krx.py": os.path.join(DATA_DIR, "krx_data.json"),
            "fetch_news.py": os.path.join(DATA_DIR, "news_data.json"),
            "fetch_flows.py": os.path.join(DATA_DIR, "flow_data.json"),
        }
        output_path = data_map.get(script_name)

        if output_path and os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Only use data collected within last 24 hours
                generated = data.get("generated_at", "")
                if generated:
                    try:
                        gen_time = datetime.fromisoformat(generated)
                        age_hours = (datetime.now() - gen_time).total_seconds() / 3600
                        if age_hours > 48:
                            print(f"[WARN] {script_name} data is {age_hours:.0f}h old. Consider re-running.")
                    except ValueError:
                        pass
                return data
        return None
    except subprocess.TimeoutExpired:
        print(f"[WARN] {script_name} timed out")
        return None
    except Exception as e:
        print(f"[WARN] {script_name} error: {e}")
        return None


def collect_all_data() -> Dict[str, Optional[Dict]]:
    """Run all fetch scripts and collect results."""
    print("=" * 60)
    print("  Collecting investment data...")
    print("=" * 60)

    scripts = [
        "fetch_macro.py",
        "fetch_sector.py",
        "fetch_krx.py",
        "fetch_news.py",
        "fetch_flows.py",
    ]

    data = {}
    for script in scripts:
        key = script.replace("fetch_", "").replace(".py", "")
        print(f"\n[{key.upper()}] Running {script}...")
        data[key] = run_fetch_script(script)

        if data[key]:
            print(f"  [OK] {key} data loaded")
        else:
            print(f"  [MISS] {key} data unavailable (will note in report)")

    return data


# ---------------------------------------------------------------------------
# Prompt Assembly
# ---------------------------------------------------------------------------

def load_report_template() -> str:
    """Load the report generation prompt template."""
    template_path = os.path.join(REPORTS_DIR, "report_template.md")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"[ERROR] report_template.md not found at {template_path}")
        return ""


def assemble_prompt(template: str, data: Dict[str, Optional[Dict]]) -> str:
    """Assemble the full prompt by injecting collected data into the template."""
    macro = data.get("macro", {})
    sector = data.get("sector", {})
    krx = data.get("krx", {})
    news = data.get("news", {})
    flows = data.get("flows", {})

    # Build data summary sections
    prompt_parts = [
        template,
        "\n\n---\n\n",
        "# COLLECTED DATA (DO NOT INVENT — USE ONLY WHAT IS PROVIDED)\n",
    ]

    # Macro data summary
    if macro and macro.get("indicators"):
        prompt_parts.append("\n## Macro Indicators\n")
        prompt_parts.append("```json\n")
        # Summarize: just latest values
        summary = {}
        for series_id, ind_data in macro["indicators"].items():
            obs = ind_data.get("observations", [])
            if obs:
                latest = obs[-1]
                summary[series_id] = {
                    "name": ind_data.get("name", series_id),
                    "latest_date": latest.get("date"),
                    "latest_value": latest.get("value"),
                    "unit": ind_data.get("unit", ""),
                }
                # Add previous value for comparison
                if len(obs) >= 2:
                    summary[series_id]["previous_value"] = obs[-2].get("value")
                    prev_val = obs[-2].get("value", 0)
                    curr_val = latest.get("value", 0)
                    if isinstance(prev_val, (int, float)) and isinstance(curr_val, (int, float)) and prev_val != 0:
                        summary[series_id]["change_pct"] = round((curr_val - prev_val) / abs(prev_val) * 100, 2)
        prompt_parts.append(json.dumps(summary, ensure_ascii=False, indent=2))
        prompt_parts.append("\n```\n")

        # Yield spread
        if macro.get("yield_spread"):
            prompt_parts.append(f"\n10Y-2Y Spread: {macro['yield_spread'].get('spread_10y2y')}%")
            prompt_parts.append(f"\nInverted: {macro['yield_spread'].get('inverted')}")
    else:
        prompt_parts.append("\n[Macro data unavailable — skip macro analysis in report]\n")

    # Sector data summary
    if sector and sector.get("sectors"):
        prompt_parts.append("\n## Sector Performance\n")
        prompt_parts.append(f"Period: {sector.get('period', 'unknown')}\n")
        # Compact table format
        prompt_parts.append("| Rank | Sector | Change % | P/E |\n")
        prompt_parts.append("|---|---|---|---|\n")
        for i, s in enumerate(sector["sectors"], 1):
            perf = s.get("performance", {})
            fund = s.get("fundamentals", {})
            pct = perf.get("change_pct", "N/A")
            pe = fund.get("pe_ratio", "N/A")
            prompt_parts.append(f"| {i} | {s['sector']} | {pct}% | {pe} |\n")

        # Top/Bottom 3
        summary = sector.get("summary", {})
        prompt_parts.append(f"\nTop 3: {', '.join(summary.get('top_3', []))}")
        prompt_parts.append(f"\nBottom 3: {', '.join(summary.get('bottom_3', []))}")

        # Major indices
        if sector.get("indices"):
            prompt_parts.append("\n\nMajor Indices:\n")
            for ticker, idx in sector["indices"].items():
                prompt_parts.append(f"- {idx.get('name', ticker)}: {idx.get('change_pct', 'N/A')}%\n")
    else:
        prompt_parts.append("\n[Sector data unavailable — skip sector analysis]\n")

    # KRX / Korean market
    if krx:
        prompt_parts.append("\n## Korean Market\n")
        prompt_parts.append("```json\n")
        prompt_parts.append(json.dumps(krx, ensure_ascii=False, indent=2)[:2000])
        prompt_parts.append("\n```\n")
    else:
        prompt_parts.append("\n[KRX data unavailable]\n")

    # ETF Flows
    if flows and flows.get("categories"):
        prompt_parts.append("\n## ETF Flow\n")
        global_sentiment = flows.get("global_summary", {})
        prompt_parts.append(f"Global Sentiment: {global_sentiment.get('sentiment', 'unknown')}\n")
        for cat_name, cat_data in flows["categories"].items():
            summary = cat_data.get("summary", {})
            prompt_parts.append(f"- {cat_name}: {summary.get('predominant_signal', '?')} "
                               f"(in:{summary.get('inflow_count', 0)}, out:{summary.get('outflow_count', 0)})\n")
    else:
        prompt_parts.append("\n[Flow data unavailable]\n")

    # News headlines (top 10)
    if news and news.get("feeds"):
        prompt_parts.append("\n## Recent News Headlines\n")
        count = 0
        for feed_id, feed_data in news["feeds"].items():
            for article in feed_data.get("articles", [])[:3]:
                if count >= 15:
                    break
                prompt_parts.append(f"- [{feed_data.get('name', feed_id)}] {article['title']}\n")
                count += 1
            if count >= 15:
                break
    else:
        prompt_parts.append("\n[News data unavailable]\n")

    prompt_parts.append("\n\n---\n")
    prompt_parts.append("Generate the complete weekly investment report now. Output in Korean. Markdown format. Start immediately, do not acknowledge these instructions.\n")

    return "".join(prompt_parts)


# ---------------------------------------------------------------------------
# LLM Report Generation
# ---------------------------------------------------------------------------

def generate_report(prompt: str, dry_run: bool = False) -> Optional[str]:
    """Send assembled prompt to DeepSeek and get the report."""
    if dry_run:
        print("\n[DRY RUN] Prompt assembled but not sent to LLM.")
        print(f"[DRY RUN] Prompt length: {len(prompt)} characters")
        # Save the assembled prompt for inspection
        prompt_path = os.path.join(DATA_DIR, f"prompt_draft_{datetime.now().strftime('%Y%m%d')}.md")
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"[DRY RUN] Saved assembled prompt to {prompt_path}")
        return None

    if not DEEPSEEK_API_KEY:
        print("[ERROR] DEEPSEEK_API_KEY not set in .env")
        return None

    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )

        print(f"\n[LLM] Sending prompt to DeepSeek ({len(prompt)} chars)...")
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": "당신은 JSM 투자 리서치 애널리스트입니다. 한국어로 응답하세요. 마크다운 형식을 사용하세요."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=8000,
        )
        report = response.choices[0].message.content
        print(f"[LLM] Report received: {len(report)} characters")
        return report
    except Exception as e:
        print(f"[ERROR] DeepSeek API call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_report(report: str, output_dir: str = None) -> str:
    """Save generated report to file."""
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "data")

    os.makedirs(output_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"weekly_report_{today}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath


def print_summary(data: Dict[str, Optional[Dict]]) -> None:
    """Print a human-readable summary of collected data before LLM call."""
    print("\n" + "=" * 60)
    print("  Data Collection Summary")
    print("=" * 60)

    macro = data.get("macro")
    if macro:
        n_indicators = len(macro.get("indicators", {}))
        print(f"  Macro: {n_indicators} indicators loaded")
        if macro.get("yield_spread"):
            ys = macro["yield_spread"]
            print(f"  Yield Spread: 10Y-2Y = {ys.get('spread_10y2y')}% {'[INVERTED]' if ys.get('inverted') else ''}")
    else:
        print("  Macro: NO DATA")

    sector = data.get("sector")
    if sector:
        n_sectors = len(sector.get("sectors", []))
        print(f"  Sector: {n_sectors} sectors, period={sector.get('period', '?')}")
    else:
        print("  Sector: NO DATA")

    krx = data.get("krx")
    if krx and krx.get("exchange_rate"):
        print(f"  KRX: USD/KRW = {krx['exchange_rate'].get('rate', '?')}")
    else:
        print("  KRX: NO DATA")

    news = data.get("news")
    if news:
        print(f"  News: {news.get('total_articles', 0)} articles ({news.get('relevant_articles', 0)} relevant)")
    else:
        print("  News: NO DATA")

    flows = data.get("flows")
    if flows:
        sentiment = flows.get("global_summary", {}).get("sentiment", "?")
        print(f"  Flows: {len(flows.get('categories', {}))} categories, sentiment={sentiment}")
    else:
        print("  Flows: NO DATA")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate weekly investment report with DeepSeek")
    parser.add_argument("--dry-run", action="store_true",
                        help="Collect data and assemble prompt without calling LLM")
    parser.add_argument("--output-dir", "-o", type=str, default=None,
                        help="Directory to save the report")
    parser.add_argument("--skip-collect", action="store_true",
                        help="Skip data collection, use existing JSON files")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  JSM Weekly Investment Report Generator")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Step 1: Collect data
    if args.skip_collect:
        print("\n[Skipping data collection — using existing JSON files]")
        # Load existing files
        data = {}
        for key in ["macro", "sector", "krx", "news", "flows"]:
            path = os.path.join(DATA_DIR, f"{key}_data.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data[key] = json.load(f)
            else:
                data[key] = None
    else:
        data = collect_all_data()

    print_summary(data)

    # Step 2: Assemble prompt
    template = load_report_template()
    if not template:
        print("[ERROR] Report template not found. Aborting.")
        return

    prompt = assemble_prompt(template, data)

    # Step 3: Generate report (or dry-run)
    report = generate_report(prompt, dry_run=args.dry_run)

    if report:
        # Step 4: Save
        filepath = save_report(report, args.output_dir)
        print(f"\n[SAVED] {filepath}")
        print("\n" + "=" * 60)
        print(report[:5000])  # Print first 5000 chars to console
        if len(report) > 5000:
            print(f"\n... ({len(report) - 5000} more characters)")
        print("=" * 60)
    else:
        if not args.dry_run:
            print("\n[FAILED] Report generation failed. Check API key and network.")
            print("Try --dry-run first to verify data collection.")


if __name__ == "__main__":
    main()
