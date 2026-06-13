"""
Module 5: ETF Flow Data Collector
Tracks capital flows into/out of major ETFs and asset classes.

Data sources:
    - ETF.com (web scraping, limited free access)
    - Yahoo Finance (volume data as flow proxy)
    - Alternative: Fidelity ETF screener data

NOTE: Real-time ETF flow data from ETF.com requires a paid subscription ($49/mo).
This module uses Yahoo Finance volume changes as a proxy indicator and provides
the scaffolding for future premium data integration.

Usage:
    python fetch_flows.py                 # Fetch flow proxies
    python fetch_flows.py --output flow_data.json

Output: data/flow_data.json
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

# ---------------------------------------------------------------------------
# ETF Flow Proxies
# ---------------------------------------------------------------------------

# Major asset-class ETFs tracked for flow analysis
FLOW_ETFS: Dict[str, List[Dict[str, str]]] = {
    "equity_us_large_cap": [
        {"ticker": "SPY",  "name": "SPDR S&P 500 ETF", "aum_bn": 580},
        {"ticker": "IVV",  "name": "iShares Core S&P 500 ETF", "aum_bn": 490},
        {"ticker": "VOO",  "name": "Vanguard S&P 500 ETF", "aum_bn": 440},
    ],
    "equity_us_tech": [
        {"ticker": "QQQ",  "name": "Invesco QQQ Trust", "aum_bn": 260},
        {"ticker": "XLK",  "name": "Technology Select Sector SPDR", "aum_bn": 65},
        {"ticker": "SOXX", "name": "iShares Semiconductor ETF", "aum_bn": 12},
    ],
    "equity_us_dividend": [
        {"ticker": "SCHD", "name": "Schwab US Dividend Equity ETF", "aum_bn": 55},
        {"ticker": "VYM",  "name": "Vanguard High Dividend Yield ETF", "aum_bn": 50},
    ],
    "equity_korea": [
        {"ticker": "EWY",  "name": "iShares MSCI South Korea ETF", "aum_bn": 5},
    ],
    "bond_us_aggregate": [
        {"ticker": "AGG",  "name": "iShares Core US Aggregate Bond ETF", "aum_bn": 110},
        {"ticker": "BND",  "name": "Vanguard Total Bond Market ETF", "aum_bn": 100},
    ],
    "bond_us_treasury": [
        {"ticker": "TLT",  "name": "iShares 20+ Year Treasury Bond ETF", "aum_bn": 50},
        {"ticker": "SHY",  "name": "iShares 1-3 Year Treasury Bond ETF", "aum_bn": 25},
    ],
    "commodity_gold": [
        {"ticker": "GLD",  "name": "SPDR Gold Shares", "aum_bn": 60},
        {"ticker": "IAU",  "name": "iShares Gold Trust", "aum_bn": 30},
    ],
    "commodity_oil": [
        {"ticker": "USO",  "name": "United States Oil Fund", "aum_bn": 3},
    ],
    "volatility": [
        {"ticker": "VIXY", "name": "ProShares VIX Short-Term Futures ETF", "aum_bn": 1},
    ],
}


def fetch_volume_data(categories: Optional[List[str]] = None) -> Dict:
    """Fetch recent volume data as flow proxy for tracked ETFs."""
    if not HAS_YFINANCE:
        print("[ERROR] yfinance required. pip install yfinance")
        return {"error": "yfinance not installed"}

    if categories is None:
        categories = list(FLOW_ETFS.keys())

    result = {"generated_at": datetime.now().isoformat(), "categories": {}}

    for category in categories:
        if category not in FLOW_ETFS:
            continue

        etfs = FLOW_ETFS[category]
        result["categories"][category] = {"etfs": []}

        for etf in etfs:
            ticker = etf["ticker"]
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="1mo")
                info = t.info

                if hist.empty:
                    result["categories"][category]["etfs"].append({
                        "ticker": ticker, "name": etf["name"], "error": "No data"
                    })
                    continue

                # Calculate volume metrics
                recent_vol = float(hist["Volume"].tail(5).mean())
                prev_vol = float(hist["Volume"].head(5).mean())
                total_vol = float(hist["Volume"].sum())
                price_change = float(((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 100)

                # Volume ratio > 1.0 indicates above-average recent activity (potential inflow)
                vol_ratio = round(recent_vol / prev_vol, 2) if prev_vol > 0 else 0

                result["categories"][category]["etfs"].append({
                    "ticker": ticker,
                    "name": etf["name"],
                    "aum_bn": etf.get("aum_bn"),
                    "latest_price": float(hist["Close"].iloc[-1]),
                    "price_change_pct": round(price_change, 2),
                    "avg_volume_5d": int(recent_vol),
                    "avg_volume_5d_prior": int(prev_vol),
                    "volume_ratio": vol_ratio,
                    "total_volume_1mo": int(total_vol),
                    "flow_signal": "inflow" if vol_ratio > 1.2 else ("outflow" if vol_ratio < 0.8 else "neutral")
                })

            except Exception as e:
                result["categories"][category]["etfs"].append({
                    "ticker": ticker, "name": etf["name"], "error": str(e)
                })

        # Category-level summary
        signals = [e.get("flow_signal") for e in result["categories"][category]["etfs"] if "flow_signal" in e]
        inflow_count = signals.count("inflow")
        outflow_count = signals.count("outflow")
        neutral_count = signals.count("neutral")

        result["categories"][category]["summary"] = {
            "inflow_count": inflow_count,
            "outflow_count": outflow_count,
            "neutral_count": neutral_count,
            "predominant_signal": "inflow" if inflow_count > outflow_count else ("outflow" if outflow_count > inflow_count else "neutral")
        }

    # Global summary
    all_signals = []
    for cat_data in result["categories"].values():
        if "summary" in cat_data:
            all_signals.append(cat_data["summary"]["predominant_signal"])

    result["global_summary"] = {
        "risk_on_categories": sum(1 for s in all_signals if s == "inflow"),
        "risk_off_categories": sum(1 for s in all_signals if s == "outflow"),
        "neutral_categories": sum(1 for s in all_signals if s == "neutral"),
        "sentiment": "risk_on" if all_signals.count("inflow") > all_signals.count("outflow") else "risk_off"
    }

    return result


def save_output(data: Dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch ETF flow proxy data")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path")
    parser.add_argument("--category", "-c", type=str, default=None,
                        help="Specific category (e.g., equity_us_large_cap)")
    args = parser.parse_args()

    output_path = args.output or os.path.join(DATA_DIR, "flow_data.json")

    print("=== JSM ETF Flow Data Collector ===\n")

    categories = [args.category] if args.category else None
    data = fetch_volume_data(categories)
    saved = save_output(data, output_path)

    print(f"[SAVED] {saved}")
    print(f"\nGlobal Sentiment: {data.get('global_summary', {}).get('sentiment', 'unknown')}")

    for cat_name, cat_data in data.get("categories", {}).items():
        summary = cat_data.get("summary", {})
        print(f"  [{cat_name}] {summary.get('predominant_signal', '?')} "
              f"(in:{summary.get('inflow_count',0)} out:{summary.get('outflow_count',0)} neutral:{summary.get('neutral_count',0)})")


if __name__ == "__main__":
    main()
