"""
Module 2: Sector Data Collector
Fetches GICS 11-sector ETF performance data via Yahoo Finance.

Required pip packages:
    yfinance>=0.2.0

Usage:
    python fetch_sector.py                  # Fetch all sectors
    python fetch_sector.py --period 3mo      # 3-month returns
    python fetch_sector.py --output sector_data.json

Output: data/sector_data.json
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------------------------------------------------------------------
# GICS 11 Sectors mapped to SPDR Select Sector ETF proxies
# Tickers are US-listed but track the same sectors globally
# ---------------------------------------------------------------------------

SECTOR_ETFS: Dict[str, Dict[str, str]] = {
    "Energy":                    {"ticker": "XLE", "name": "Energy Select Sector SPDR"},
    "Materials":                 {"ticker": "XLB", "name": "Materials Select Sector SPDR"},
    "Industrials":               {"ticker": "XLI", "name": "Industrial Select Sector SPDR"},
    "Consumer Discretionary":    {"ticker": "XLY", "name": "Consumer Discretionary Select Sector SPDR"},
    "Consumer Staples":          {"ticker": "XLP", "name": "Consumer Staples Select Sector SPDR"},
    "Health Care":               {"ticker": "XLV", "name": "Health Care Select Sector SPDR"},
    "Financials":                {"ticker": "XLF", "name": "Financial Select Sector SPDR"},
    "Information Technology":    {"ticker": "XLK", "name": "Technology Select Sector SPDR"},
    "Communication Services":    {"ticker": "XLC", "name": "Communication Services Select Sector SPDR"},
    "Utilities":                 {"ticker": "XLU", "name": "Utilities Select Sector SPDR"},
    "Real Estate":               {"ticker": "XLRE", "name": "Real Estate Select Sector SPDR"},
}

# Major indices for context
INDICES: Dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ Composite",
    "^DJI":  "Dow Jones Industrial Average",
    "^KS11": "KOSPI",
    "^KQ11": "KOSDAQ",
}

# ---------------------------------------------------------------------------
# Yahoo Finance Query (using yfinance or direct API)
# ---------------------------------------------------------------------------

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    print("[WARN] yfinance not installed. Install with: pip install yfinance")


def _fetch_yahoo_api(symbols: List[str], period: str = "1mo") -> Optional[Dict]:
    """Fetch historical data via yfinance."""
    if not HAS_YFINANCE:
        print("[ERROR] yfinance is required for sector data. pip install yfinance")
        return None

    try:
        data = {}
        for symbol in symbols:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if not hist.empty:
                start_price = float(hist["Close"].iloc[0])
                end_price = float(hist["Close"].iloc[-1])
                high = float(hist["High"].max())
                low = float(hist["Low"].min())
                change_pct = round(((end_price - start_price) / start_price) * 100, 2)

                data[symbol] = {
                    "start_price": start_price,
                    "end_price": end_price,
                    "high": high,
                    "low": low,
                    "change_pct": change_pct,
                    "period": period,
                }
            else:
                data[symbol] = {"error": "No data returned"}

        return data
    except Exception as e:
        print(f"[ERROR] yfinance fetch failed: {e}")
        return None


def _fetch_yahoo_info(symbols: List[str]) -> Dict[str, Dict]:
    """Fetch fundamental data (P/E, market cap, etc.) via yfinance info."""
    result = {}
    if not HAS_YFINANCE:
        return result

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            result[symbol] = {
                "name": info.get("longName", info.get("shortName", symbol)),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "market_cap": info.get("marketCap"),
                "dividend_yield": info.get("dividendYield"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            }
        except Exception as e:
            result[symbol] = {"error": str(e)}
    return result


def fetch_sector_performance(period: str = "1mo") -> Dict:
    """Fetch performance data for all 11 GICS sector ETFs + major indices."""
    sector_tickers = [v["ticker"] for v in SECTOR_ETFS.values()]
    all_tickers = sector_tickers + list(INDICES.keys())

    print(f"[FETCH] {len(all_tickers)} tickers for period={period}...")
    perf_data = _fetch_yahoo_api(all_tickers, period)
    info_data = _fetch_yahoo_info(sector_tickers)

    # Assemble result
    sectors = []
    for sector_name, meta in SECTOR_ETFS.items():
        ticker = meta["ticker"]
        sector_entry = {
            "sector": sector_name,
            "ticker": ticker,
            "etf_name": meta["name"],
        }

        if perf_data and ticker in perf_data:
            sector_entry["performance"] = perf_data[ticker]
        if info_data and ticker in info_data:
            sector_entry["fundamentals"] = info_data[ticker]

        sectors.append(sector_entry)

    # Rank by performance
    sectors.sort(key=lambda s: s.get("performance", {}).get("change_pct", -999), reverse=True)

    # Indices
    indices = {}
    if perf_data:
        for ticker, name in INDICES.items():
            if ticker in perf_data:
                indices[ticker] = {"name": name, **perf_data[ticker]}

    return {
        "generated_at": datetime.now().isoformat(),
        "period": period,
        "sectors": sectors,
        "indices": indices,
        "summary": {
            "top_3": [s["sector"] for s in sectors[:3]],
            "bottom_3": [s["sector"] for s in sectors[-3:]],
        }
    }


def save_output(data: Dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch GICS 11-sector ETF performance")
    parser.add_argument("--period", "-p", type=str, default="1mo",
                        choices=["5d", "1mo", "3mo", "6mo", "1y", "ytd"],
                        help="Performance period (default: 1mo)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file path")
    args = parser.parse_args()

    output_path = args.output or os.path.join(DATA_DIR, "sector_data.json")

    print("=== JSM Sector Data Collector ===\n")
    data = fetch_sector_performance(args.period)
    saved = save_output(data, output_path)

    print(f"\n[DONE] {len(data['sectors'])} sectors fetched")
    print(f"[SAVED] {saved}")

    print("\n=== Sector Ranking ===")
    for i, s in enumerate(data["sectors"], 1):
        perf = s.get("performance", {})
        pct = perf.get("change_pct", "N/A")
        print(f"  {i:2d}. {s['sector']:<28s} {pct:>+7.2f}%")

    if data.get("indices"):
        print("\n=== Major Indices ===")
        for ticker, idx in data["indices"].items():
            print(f"  {idx['name']:<30s} {idx.get('change_pct', 'N/A'):>+7.2f}%")


if __name__ == "__main__":
    main()
