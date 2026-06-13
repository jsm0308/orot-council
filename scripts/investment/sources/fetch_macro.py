"""
Module 1: Macroeconomic Data Collector
Pulls from FRED (Federal Reserve Economic Data), CME FedWatch, and other free sources.

Required env variables:
    FRED_API_KEY   - Free from https://fred.stlouisfed.org/docs/api/api_key.html

Usage:
    python fetch_macro.py              # Fetch all indicators, save to JSON
    python fetch_macro.py --indicator GDP  # Fetch specific indicator
    python fetch_macro.py --output macro_data.json

Output: data/macro_data.json
"""

import os
import json
import argparse
from datetime import datetime
from typing import Optional, Dict, Any

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(BASE_DIR, ".env"))

FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred"
DATA_DIR = os.path.join(BASE_DIR, "data")

# ---------------------------------------------------------------------------
# Indicator Registry
# ---------------------------------------------------------------------------

INDICATORS: Dict[str, Dict[str, Any]] = {
    # --- United States ---
    "FEDFUNDS": {
        "name": "Fed Funds Rate",
        "source": "FRED",
        "series": "FEDFUNDS",
        "unit": "%",
        "frequency": "monthly",
        "description": "Federal Funds Effective Rate"
    },
    "DGS10": {
        "name": "US 10Y Treasury Yield",
        "source": "FRED",
        "series": "DGS10",
        "unit": "%",
        "frequency": "daily",
        "description": "10-Year Treasury Constant Maturity Rate"
    },
    "DGS2": {
        "name": "US 2Y Treasury Yield",
        "source": "FRED",
        "series": "DGS2",
        "unit": "%",
        "frequency": "daily",
        "description": "2-Year Treasury Constant Maturity Rate"
    },
    "CPIAUCSL": {
        "name": "US CPI (All Urban Consumers)",
        "source": "FRED",
        "series": "CPIAUCSL",
        "unit": "index",
        "frequency": "monthly",
        "description": "Consumer Price Index for All Urban Consumers"
    },
    "CPILFESL": {
        "name": "US Core CPI",
        "source": "FRED",
        "series": "CPILFESL",
        "unit": "index",
        "frequency": "monthly",
        "description": "Core CPI (excl. food & energy)"
    },
    "PCE": {
        "name": "US PCE",
        "source": "FRED",
        "series": "PCE",
        "unit": "billions",
        "frequency": "monthly",
        "description": "Personal Consumption Expenditures"
    },
    "PCEPILFE": {
        "name": "US Core PCE",
        "source": "FRED",
        "series": "PCEPILFE",
        "unit": "index",
        "frequency": "monthly",
        "description": "Core PCE Price Index (Fed's preferred inflation gauge)"
    },
    "UNRATE": {
        "name": "US Unemployment Rate",
        "source": "FRED",
        "series": "UNRATE",
        "unit": "%",
        "frequency": "monthly",
        "description": "Civilian Unemployment Rate"
    },
    "PAYEMS": {
        "name": "US Nonfarm Payrolls",
        "source": "FRED",
        "series": "PAYEMS",
        "unit": "thousands",
        "frequency": "monthly",
        "description": "All Employees: Total Nonfarm"
    },
    "GDP": {
        "name": "US GDP",
        "source": "FRED",
        "series": "GDP",
        "unit": "billions",
        "frequency": "quarterly",
        "description": "Gross Domestic Product"
    },
    "VIXCLS": {
        "name": "VIX (CBOE Volatility Index)",
        "source": "FRED",
        "series": "VIXCLS",
        "unit": "index",
        "frequency": "daily",
        "description": "CBOE Volatility Index: VIX"
    },
    "T10YIE": {
        "name": "US 10Y Breakeven Inflation",
        "source": "FRED",
        "series": "T10YIE",
        "unit": "%",
        "frequency": "daily",
        "description": "10-Year Breakeven Inflation Rate"
    },
    "T10Y2Y": {
        "name": "US 10Y-2Y Yield Spread",
        "source": "FRED",
        "series": "T10Y2Y",
        "unit": "%",
        "frequency": "daily",
        "description": "10Y minus 2Y Treasury Spread"
    },
    "DTWEXBGS": {
        "name": "US Dollar Index (Broad)",
        "source": "FRED",
        "series": "DTWEXBGS",
        "unit": "index",
        "frequency": "daily",
        "description": "Trade Weighted US Dollar Index: Broad"
    },
    "DCOILWTICO": {
        "name": "WTI Crude Oil Price",
        "source": "FRED",
        "series": "DCOILWTICO",
        "unit": "$/barrel",
        "frequency": "daily",
        "description": "Crude Oil Prices: West Texas Intermediate"
    },
    "DCOILBRENTEU": {
        "name": "Brent Crude Oil Price",
        "source": "FRED",
        "series": "DCOILBRENTEU",
        "unit": "$/barrel",
        "frequency": "daily",
        "description": "Crude Oil Prices: Brent - Europe"
    },
    # --- South Korea ---
    "KORCPI": {
        "name": "Korea CPI",
        "source": "FRED",
        "series": "KORCPIALLMINMEI",
        "unit": "index",
        "frequency": "monthly",
        "description": "Consumer Price Index: All Items for South Korea"
    },
    "KORUR": {
        "name": "Korea Unemployment Rate",
        "source": "FRED",
        "series": "LRUN64TTKRM156S",
        "unit": "%",
        "frequency": "monthly",
        "description": "Unemployment Rate: Aged 15-64: All for South Korea"
    },
}


def _fred_request(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Make a FRED API request with proper error handling."""
    if not FRED_API_KEY:
        print("[WARN] FRED_API_KEY not set. Set it in .env (free from https://fred.stlouisfed.org/docs/api/api_key.html)")
        return None

    url = f"{FRED_BASE}{path}"
    req_params = {"api_key": FRED_API_KEY, "file_type": "json"}
    if params:
        req_params.update(params)

    try:
        resp = requests.get(url, params=req_params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] FRED request failed ({path}): {e}")
        return None


def fetch_series(series_id: str, limit: int = 12) -> Optional[Dict]:
    """Fetch a single FRED series with most recent observations."""
    data = _fred_request(
        "/series/observations",
        {"series_id": series_id, "sort_order": "desc", "limit": limit, "output_type": 4}
    )
    if data is None:
        return None

    observations = data.get("observations", [])
    values = []
    for obs in observations:
        try:
            val = float(obs["value"])
        except (ValueError, TypeError):
            val = obs["value"]
        values.append({"date": obs["date"], "value": val})

    return {
        "series_id": series_id,
        "unit": INDICATORS.get(series_id, {}).get("unit", ""),
        "observations": list(reversed(values)),  # chronological order
        "fetched_at": datetime.now().isoformat()
    }


def fetch_fedwatch() -> Optional[Dict]:
    """Scrape CME FedWatch tool for rate probabilities."""
    try:
        url = "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/8478/G?quoteCodes=null"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        # Extract current target rate range and probabilities
        quotes = raw.get("quotes", [])
        if not quotes:
            return None

        current = {
            "fed_funds_target": quotes[0].get("last", "N/A"),
            "fetched_at": datetime.now().isoformat()
        }

        # Try to get probability data from the event calendar URL
        event_url = "https://www.cmegroup.com/CmeWS/mvc/EventCalendar/All"
        event_resp = requests.get(event_url, headers=headers, timeout=15)
        if event_resp.status_code == 200:
            events = event_resp.json()
            for event in events:
                if "FOMC" in str(event.get("title", "")):
                    current["next_fomc"] = event.get("start", "")
                    break

        return current
    except Exception as e:
        print(f"[WARN] CME FedWatch fetch failed: {e}")
        return None


def fetch_yield_spread() -> Optional[Dict]:
    """Calculate US 2Y-10Y yield spread manually if T10Y2Y series is stale."""
    dgs10 = fetch_series("DGS10", limit=1)
    dgs2 = fetch_series("DGS2", limit=1)

    if dgs10 and dgs2 and dgs10["observations"] and dgs2["observations"]:
        ten_yr = dgs10["observations"][-1]["value"]
        two_yr = dgs2["observations"][-1]["value"]
        if isinstance(ten_yr, (int, float)) and isinstance(two_yr, (int, float)):
            return {
                "spread_10y2y": round(ten_yr - two_yr, 4),
                "10y": ten_yr,
                "2y": two_yr,
                "date": dgs10["observations"][-1]["date"],
                "inverted": (ten_yr - two_yr) < 0
            }
    return None


def fetch_all_indicators() -> Dict:
    """Fetch all registered macro indicators and assemble a single report."""
    result = {
        "generated_at": datetime.now().isoformat(),
        "indicators": {},
        "fedwatch": None,
        "yield_spread": None,
        "errors": []
    }

    for series_id in INDICATORS:
        print(f"[FETCH] {series_id} ({INDICATORS[series_id]['name']})...")
        data = fetch_series(series_id)
        if data:
            result["indicators"][series_id] = data
        else:
            result["errors"].append(f"Failed to fetch {series_id}")

    # Supplementary data
    result["fedwatch"] = fetch_fedwatch()
    result["yield_spread"] = fetch_yield_spread()

    return result


def load_existing_data(path: str) -> Dict:
    """Load previously saved macro data if it exists."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def diff_indicators(prev: Dict, current: Dict) -> list:
    """Compare previous and current indicator values, return changes."""
    changes = []
    prev_indicators = prev.get("indicators", {})
    curr_indicators = current.get("indicators", {})

    for series_id, curr_data in curr_indicators.items():
        curr_obs = curr_data.get("observations", [])
        prev_obs = prev_indicators.get(series_id, {}).get("observations", [])

        if curr_obs and prev_obs:
            curr_val = curr_obs[-1]["value"]
            prev_val = prev_obs[-1]["value"]
            if isinstance(curr_val, (int, float)) and isinstance(prev_val, (int, float)):
                change = curr_val - prev_val
                changes.append({
                    "indicator": INDICATORS.get(series_id, {}).get("name", series_id),
                    "series_id": series_id,
                    "previous": prev_val,
                    "current": curr_val,
                    "change": round(change, 4),
                    "change_pct": round((change / abs(prev_val)) * 100, 2) if prev_val != 0 else 0
                })

    return changes


def save_output(data: Dict, output_path: str) -> str:
    """Save macro data to JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Fetch macroeconomic indicators from FRED & CME")
    parser.add_argument("--indicator", "-i", type=str, help="Fetch specific indicator (e.g., FEDFUNDS, UNRATE)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path")
    parser.add_argument("--diff", action="store_true", help="Compare with previous data and show changes")
    parser.print_help = parser.print_help  # type: ignore
    args = parser.parse_args()

    output_path = args.output or os.path.join(DATA_DIR, "macro_data.json")

    if args.indicator:
        indicator = INDICATORS.get(args.indicator.upper())
        if not indicator:
            print(f"[ERROR] Unknown indicator: {args.indicator}")
            available = ", ".join(INDICATORS.keys())
            print(f"Available: {available}")
            return
        data = fetch_series(indicator["series"])
        if data:
            print(json.dumps(data, indent=2))
        return

    print("=== JSM Macro Data Collector ===\n")

    prev_data = load_existing_data(output_path) if args.diff else {}
    data = fetch_all_indicators()
    saved = save_output(data, output_path)

    success_count = len(data["indicators"])
    error_count = len(data["errors"])
    print(f"\n[DONE] {success_count} indicators fetched, {error_count} errors")
    print(f"[SAVED] {saved}")

    if args.diff and prev_data:
        changes = diff_indicators(prev_data, data)
        if changes:
            print("\n=== Changes from previous fetch ===")
            for c in changes:
                direction = "↑" if c["change"] > 0 else "↓"
                print(f"  {c['indicator']}: {c['previous']} → {c['current']} ({direction}{abs(c['change_pct']):.1f}%)")
        else:
            print("\nNo significant changes detected.")

    if data["fedwatch"]:
        print(f"\n[FEDWATCH] Fed Funds Target: {data['fedwatch'].get('fed_funds_target', 'N/A')}")

    if data["yield_spread"]:
        ys = data["yield_spread"]
        warning = " [INVERTED - Recession Signal]" if ys.get("inverted") else ""
        print(f"[SPREAD] 10Y-2Y: {ys.get('spread_10y2y')}%{warning}")


if __name__ == "__main__":
    main()
