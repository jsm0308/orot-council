"""
Module 3: Korean Market Data Collector
Fetches KOSPI/KOSDAQ indices, sector data, won/dollar FX rate.

Required pip packages:
    pykrx>=1.0.0       (Korean exchange data)
    requests>=2.28.0

Usage:
    python fetch_krx.py                  # Fetch market snapshot
    python fetch_krx.py --fx-only         # Only fetch FX rates
    python fetch_krx.py --output krx_data.json

Output: data/krx_data.json
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")

try:
    from pykrx import stock
    HAS_PYKRX = True
except ImportError:
    HAS_PYKRX = False
    print("[WARN] pykrx not installed. Install with: pip install pykrx")

# ---------------------------------------------------------------------------
# Exchange Rate (Won/Dollar)
# ---------------------------------------------------------------------------

def fetch_exchange_rate() -> Optional[Dict]:
    """Fetch USD/KRW exchange rate via free API."""
    try:
        # Using currencyfreaks or exchangerate-api free tier
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        krw_rate = data.get("rates", {}).get("KRW")
        if krw_rate:
            return {
                "pair": "USD/KRW",
                "rate": krw_rate,
                "date": data.get("date", ""),
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        print(f"[WARN] Exchange rate API failed: {e}")

    # Fallback: try open.er-api.com
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        krw_rate = data.get("rates", {}).get("KRW")
        if krw_rate:
            return {
                "pair": "USD/KRW",
                "rate": krw_rate,
                "date": data.get("time_last_update_utc", ""),
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        print(f"[ERROR] All FX rate sources failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Korean Market Indices (KOSPI, KOSDAQ)
# ---------------------------------------------------------------------------

def fetch_kospi_snapshot() -> Optional[Dict]:
    """Fetch KOSPI/KOSDAQ index data via pykrx."""
    if not HAS_PYKRX:
        print("[ERROR] pykrx is required for KRX data. Install: pip install pykrx")
        return None

    today = datetime.now()
    # Get last trading day
    date = today.strftime("%Y%m%d")

    try:
        # KOSPI
        kospi_idx = stock.get_index_ohlcv(date, date, "1001")  # KOSPI
        kosdaq_idx = stock.get_index_ohlcv(date, date, "2001")  # KOSDAQ

        result = {
            "generated_at": datetime.now().isoformat(),
            "indices": {}
        }

        if not kospi_idx.empty:
            row = kospi_idx.iloc[-1]
            result["indices"]["KOSPI"] = {
                "name": "KOSPI",
                "close": float(row["종가"]),
                "open": float(row["시가"]),
                "high": float(row["고가"]),
                "low": float(row["저가"]),
                "volume": int(row["거래량"]),
                "amount": float(row["거래대금"]),
            }

        if not kosdaq_idx.empty:
            row = kosdaq_idx.iloc[-1]
            result["indices"]["KOSDAQ"] = {
                "name": "KOSDAQ",
                "close": float(row["종가"]),
                "open": float(row["시가"]),
                "high": float(row["고가"]),
                "low": float(row["저가"]),
                "volume": int(row["거래량"]),
                "amount": float(row["거래대금"]),
            }

        # Market cap
        try:
            kospi_cap = stock.get_market_cap(date, date, "KOSPI")
            kosdaq_cap = stock.get_market_cap(date, date, "KOSDAQ")
            if not kospi_cap.empty:
                result["indices"]["KOSPI"]["market_cap"] = int(kospi_cap.iloc[-1]["시가총액"]) // 100000000
            if not kosdaq_cap.empty:
                result["indices"]["KOSDAQ"]["market_cap"] = int(kosdaq_cap.iloc[-1]["시가총액"]) // 100000000
        except Exception:
            pass

        # Trading value by investor type
        try:
            investor_data = stock.get_market_trading_value_by_investor(date, date, "KOSPI")
            if not investor_data.empty:
                row = investor_data.iloc[-1]
                result["investor_flows"] = {
                    "individual": int(row.get("개인", 0)) // 100000000,
                    "foreign": int(row.get("외국인", 0)) // 100000000,
                    "institution": int(row.get("기관합계", 0)) // 100000000,
                    "unit": "KRW 100M"
                }
        except Exception:
            pass

        return result
    except Exception as e:
        print(f"[ERROR] KRX data fetch failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Korean Export Data (Monthly)
# ---------------------------------------------------------------------------

def fetch_export_data() -> Optional[Dict]:
    """Fetch Korea export data (simplified - returns structure for manual fill)."""
    # Korean export data is published by Korea Customs Service around 1st of each month.
    # This function provides a placeholder. In production, could scrape KCS or use Naver Finance.

    today = datetime.now()
    return {
        "note": "Korea export data is published by Korea Customs Service around the 1st of each month.",
        "source_url": "https://tradedata.kita.net/",
        "next_release": f"{today.year}-{(today.month % 12) + 1:02d}-01 (estimated)",
        "last_known": {
            "period": f"{today.year}-{today.month - 1:02d}" if today.month > 1 else f"{today.year - 1}-12",
            "exports_yoy": None,  # Fill manually or via future scraping
            "semiconductor_exports_yoy": None,
        }
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch_all() -> Dict:
    """Fetch all Korean market data."""
    result = {
        "generated_at": datetime.now().isoformat(),
        "exchange_rate": fetch_exchange_rate(),
        "market": fetch_kospi_snapshot(),
        "exports": fetch_export_data(),
    }
    return result


def save_output(data: Dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch Korean market data (KOSPI, KOSDAQ, FX)")
    parser.add_argument("--fx-only", action="store_true", help="Only fetch exchange rate")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    output_path = args.output or os.path.join(DATA_DIR, "krx_data.json")

    print("=== JSM Korean Market Data Collector ===\n")

    if args.fx_only:
        fx = fetch_exchange_rate()
        if fx:
            print(f"[FX] USD/KRW = {fx['rate']:.2f}")
            print(json.dumps(fx, indent=2))
        return

    data = fetch_all()
    saved = save_output(data, output_path)

    print(f"[SAVED] {saved}")

    fx = data.get("exchange_rate")
    if fx:
        print(f"[FX] USD/KRW = {fx['rate']:.2f}")

    market = data.get("market", {})
    indices = market.get("indices", {}) if market else {}
    for code, idx in indices.items():
        print(f"[{code}] Close: {idx.get('close', 'N/A'):,.2f}")

    flows = market.get("investor_flows", {}) if market else {}
    if flows:
        print(f"[FLOW] Individual: {flows.get('individual', '?')} | Foreign: {flows.get('foreign', '?')} | Institution: {flows.get('institution', '?')} (10B KRW)")


if __name__ == "__main__":
    main()
