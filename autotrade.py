"""
BTC Auto-Trade Bot (v2)
LLM-based Bitcoin trading system using DeepSeek + Upbit API.
Based on Jocoding's GPT-Bitcoin project, adapted for DeepSeek v4 Pro.

Architecture:
    Module 1: Market Data (OHLCV + Technical Indicators)
    Module 2: Sentiment Data (News + Fear & Greed Index)
    Module 4: LLM Inference (DeepSeek + Prompt Assembly)
    Module 5: Order Execution (TradeManager + Upbit)
    Module 6: Memory (SQLite + Recursive Improvement)

Usage:
    python autotrade.py          # Run once
    nohup python3 -u autotrade.py > output.log 2>&1 &   # Daemon mode
"""

import os
import sys

# Fix SSL certificate verification on Windows
import certifi
os.environ["SSL_CERT_FILE"] = certifi.where()

import re
import json
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

import requests
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
import pyupbit
import schedule

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY", "")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY", "")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

TICKER = "KRW-BTC"
TRADE_INTERVAL_HOURS = 8
MAX_SINGLE_TRADE_PCT = 0.30    # Maximum 30% of KRW balance per trade
MIN_TRADE_KRW = 5000           # Upbit minimum order amount
FEE_RATE = 0.0005              # 0.05% transaction fee
MAX_CONSECUTIVE_LOSSES = 3     # Circuit breaker threshold
DB_PATH = os.path.join(BASE_DIR, "trading.db")

# DeepSeek client (OpenAI-compatible)
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# Upbit client (only if keys are provided)
upbit = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY) if (UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY) else None


# ---------------------------------------------------------------------------
# Module 6: Database Manager
# ---------------------------------------------------------------------------

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._setup_tables()

    def _setup_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trading_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                decision TEXT NOT NULL,
                percentage REAL NOT NULL,
                reason TEXT NOT NULL,
                btc_balance REAL NOT NULL,
                krw_balance REAL NOT NULL,
                btc_avg_buy_price REAL NOT NULL,
                btc_krw_price REAL NOT NULL
            )
        """)
        self.conn.commit()

    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM trading_history ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_last_n_decisions(self, n: int = 5) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM trading_history WHERE decision != 'hold' ORDER BY timestamp DESC LIMIT ?",
            (n,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def count_consecutive_losses(self) -> int:
        """Count consecutive sell transactions where price dropped below buy price."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT decision, btc_krw_price, btc_avg_buy_price FROM trading_history "
            "WHERE decision != 'hold' ORDER BY timestamp DESC LIMIT ?",
            (MAX_CONSECUTIVE_LOSSES * 2,)
        )
        rows = cursor.fetchall()
        losses = 0
        for row in rows:
            if row["decision"] == "sell":
                if row["btc_krw_price"] < row["btc_avg_buy_price"]:
                    losses += 1
                else:
                    break
            elif row["decision"] == "buy":
                continue
        return losses

    def record_trade(self, trade_data: Dict) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO trading_history
            (timestamp, decision, percentage, reason, btc_balance, krw_balance, btc_avg_buy_price, btc_krw_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            trade_data["decision"],
            trade_data["percentage"],
            trade_data["reason"],
            trade_data.get("btc_balance", 0),
            trade_data.get("krw_balance", 0),
            trade_data.get("btc_avg_buy_price", 0),
            trade_data.get("btc_krw_price", 0)
        ))
        self.conn.commit()
        return cursor.lastrowid


db = DatabaseManager()


# ---------------------------------------------------------------------------
# Module 5: Trade Manager
# ---------------------------------------------------------------------------

class TradeManager:
    def __init__(self, ticker: str = TICKER):
        self.ticker = ticker

    def get_current_balances(self) -> Dict[str, float]:
        btc_price = 0.0
        try:
            btc_price = float(pyupbit.get_current_price(self.ticker) or 0)
        except Exception:
            pass

        if upbit is None or DRY_RUN:
            print("[DRY RUN] No Upbit keys - using simulated balances")
            return {
                "btc_balance": 0.0,
                "krw_balance": 100000.0,  # Simulated: 100,000 KRW for testing
                "btc_avg_buy_price": 0.0,
                "btc_krw_price": btc_price
            }

        try:
            return {
                "btc_balance": float(upbit.get_balance(self.ticker) or 0),
                "krw_balance": float(upbit.get_balance("KRW") or 0),
                "btc_avg_buy_price": float(upbit.get_avg_buy_price(self.ticker) or 0),
                "btc_krw_price": btc_price
            }
        except Exception as e:
            print(f"[ERROR] Failed to get real balances: {e}")
            return {"btc_balance": 0, "krw_balance": 0, "btc_avg_buy_price": 0, "btc_krw_price": btc_price}

    def adjust_trade_ratio(self, base_ratio: float, fear_greed_value: int, trade_type: str) -> float:
        ratio = min(base_ratio / 100.0, MAX_SINGLE_TRADE_PCT)

        if trade_type == "buy":
            if fear_greed_value <= 25:
                ratio = min(ratio * 1.2, MAX_SINGLE_TRADE_PCT)
            elif fear_greed_value >= 75:
                ratio = ratio * 0.8
        elif trade_type == "sell":
            if fear_greed_value >= 75:
                ratio = min(ratio * 1.2, 1.0)
            elif fear_greed_value <= 25:
                ratio = ratio * 0.8

        return ratio

    def execute_buy(self, krw_amount: float) -> Optional[Dict]:
        if krw_amount < MIN_TRADE_KRW:
            print(f"[SKIP] Buy amount {krw_amount:.0f} KRW below minimum {MIN_TRADE_KRW}")
            return None

        if upbit is None or DRY_RUN:
            btc_price = pyupbit.get_current_price(self.ticker) or 0
            btc_bought = (krw_amount * (1 - FEE_RATE)) / btc_price if btc_price else 0
            print(f"[DRY RUN BUY] Would buy {btc_bought:.8f} BTC for {krw_amount:.0f} KRW (fee: {krw_amount * FEE_RATE:.0f} KRW)")
            return {"uuid": "dry-run-buy", "state": "dry_run", "btc_bought": btc_bought}

        try:
            amount_with_fee = krw_amount * (1 - FEE_RATE)
            result = upbit.buy_market_order(self.ticker, amount_with_fee)
            print(f"[BUY] Order executed: {result}")
            return result
        except Exception as e:
            print(f"[ERROR] Buy order failed: {e}")
            return None

    def execute_sell(self, btc_amount: float) -> Optional[Dict]:
        try:
            current_price = pyupbit.get_current_price(self.ticker)
            if current_price is None:
                print("[ERROR] Could not fetch current price for sell")
                return None
            krw_value = btc_amount * current_price
            if krw_value < MIN_TRADE_KRW:
                print(f"[SKIP] Sell value {krw_value:.0f} KRW below minimum {MIN_TRADE_KRW}")
                return None

            if upbit is None or DRY_RUN:
                print(f"[DRY RUN SELL] Would sell {btc_amount:.8f} BTC for ~{krw_value:.0f} KRW (fee: {krw_value * FEE_RATE:.0f} KRW)")
                return {"uuid": "dry-run-sell", "state": "dry_run", "krw_received": krw_value}

            result = upbit.sell_market_order(self.ticker, btc_amount)
            print(f"[SELL] Order executed: {result}")
            return result
        except Exception as e:
            print(f"[ERROR] Sell order failed: {e}")
            return None


trader = TradeManager()


# ---------------------------------------------------------------------------
# Module 1: Market Data (OHLCV + Technical Indicators)
# ---------------------------------------------------------------------------

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    # SMA & EMA (10)
    df["SMA_10"] = close.rolling(window=10).mean()
    df["EMA_10"] = close.ewm(span=10, adjust=False).mean()

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    # Stochastic Oscillator (%K=14, %D=3)
    low_14 = low.rolling(window=14).min()
    high_14 = high.rolling(window=14).max()
    df["Stoch_%K"] = ((close - low_14) / (high_14 - low_14).replace(0, 1e-10)) * 100
    df["Stoch_%D"] = df["Stoch_%K"].rolling(window=3).mean()

    # MACD (fast=12, slow=26, signal=9)
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["Signal_Line"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Histogram"] = df["MACD"] - df["Signal_Line"]

    # Bollinger Bands (period=20, std=2)
    df["Middle_Band"] = close.rolling(window=20).mean()
    std_20 = close.rolling(window=20).std()
    df["Upper_Band"] = df["Middle_Band"] + (std_20 * 2)
    df["Lower_Band"] = df["Middle_Band"] - (std_20 * 2)

    return df


def fetch_market_data() -> str:
    df_daily = pyupbit.get_ohlcv(TICKER, "day", count=30)
    df_hourly = pyupbit.get_ohlcv(TICKER, interval="minute60", count=24)

    if df_daily is None or df_hourly is None:
        print("[ERROR] Failed to fetch OHLCV data")
        return "{}"

    df_daily = add_technical_indicators(df_daily)
    df_hourly = add_technical_indicators(df_hourly)

    combined = pd.concat([df_daily, df_hourly], keys=["daily", "hourly"])
    return combined.to_json(orient="split", date_format="iso")


# ---------------------------------------------------------------------------
# Module 0: On-Chain Context (Stablecoins, Competing Chains)
# ---------------------------------------------------------------------------

ONCHAIN_CACHE = {"data": None, "timestamp": 0}
ONCHAIN_CACHE_TTL = 3600  # 1 hour


def fetch_onchain_context() -> Dict:
    """Fetch stablecoin dominance and competing chain metrics for LLM context.

    Returns a compact dict for prompt injection. Cached for 1 hour to avoid
    rate limiting on free APIs.
    """
    global ONCHAIN_CACHE
    now = time.time()
    if ONCHAIN_CACHE["data"] is not None and (now - ONCHAIN_CACHE["timestamp"]) < ONCHAIN_CACHE_TTL:
        return ONCHAIN_CACHE["data"]

    data = {
        "source": "CoinGecko + DeFiLlama (public APIs)",
        "fetched_at": datetime.now().isoformat(),
    }

    try:
        # --- Stablecoin market caps via CoinGecko ---
        cg_url = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=tether,usd-coin,dai,first-digital-usd,usds"
            "&vs_currencies=usd&include_market_cap=true"
        )
        resp = requests.get(cg_url, timeout=15)
        if resp.status_code == 200:
            stable_data = resp.json()
            stablecoins = {}
            total_mcap = 0
            for coin_id, vals in stable_data.items():
                mcap = vals.get("usd_market_cap", 0)
                stablecoins[coin_id] = mcap
                total_mcap += mcap
            data["stablecoins"] = stablecoins
            data["stablecoin_total_mcap_usd"] = total_mcap
        else:
            data["stablecoins_error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        data["stablecoins_error"] = str(e)[:100]

    try:
        # --- DeFi TVL per chain via DeFiLlama ---
        tvl_url = "https://api.llama.fi/v2/chains"
        resp = requests.get(tvl_url, timeout=15)
        if resp.status_code == 200:
            chains = resp.json()
            chain_tvl = {}
            for c in chains:
                name = c.get("name", "")
                tvl = c.get("tvl", 0)
                if name in ("Ethereum", "Solana", "Base", "Arbitrum", "Optimism", "Polygon"):
                    chain_tvl[name] = tvl
            data["chain_tvl"] = chain_tvl
            data["chain_tvl_unit"] = "USD"
        else:
            data["chain_tvl_error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        data["chain_tvl_error"] = str(e)[:100]

    try:
        # --- Top L1/L2 market caps (competing settlement layers) ---
        cg_url2 = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=ethereum,solana,avalanche-2,near,polkadot"
            "&vs_currencies=usd&include_market_cap=true"
        )
        resp = requests.get(cg_url2, timeout=15)
        if resp.status_code == 200:
            layer1_data = resp.json()
            l1_mcaps = {}
            for coin_id, vals in layer1_data.items():
                l1_mcaps[coin_id] = vals.get("usd_market_cap", 0)
            data["layer1_mcaps"] = l1_mcaps
        else:
            data["layer1_mcaps_error"] = f"HTTP {resp.status_code}"
    except Exception as e:
        data["layer1_mcaps_error"] = str(e)[:100]

    ONCHAIN_CACHE["data"] = data
    ONCHAIN_CACHE["timestamp"] = now
    return data


def fetch_orderbook() -> Dict:
    try:
        ob = pyupbit.get_orderbook(ticker=TICKER)
        if ob is None:
            return {}
        return {
            "timestamp": ob.get("timestamp"),
            "total_ask_size": ob.get("total_ask_size"),
            "total_bid_size": ob.get("total_bid_size"),
            "orderbook_units": ob.get("orderbook_units", [])[:5]
        }
    except Exception as e:
        print(f"[ERROR] Failed to fetch orderbook: {e}")
        return {}


# ---------------------------------------------------------------------------
# Module 2: Sentiment Data (News + Fear & Greed)
# ---------------------------------------------------------------------------

def fetch_news() -> List[Tuple[str, str, int]]:
    if not SERPAPI_API_KEY:
        print("[WARN] No SERPAPI_API_KEY set, skipping news")
        return []

    try:
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_news",
            "q": "Bitcoin crypto",
            "api_key": SERPAPI_API_KEY,
            "num": 10
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        news_items = []
        for article in data.get("news_results", [])[:10]:
            title = article.get("title", "")
            source = article.get("source", {}).get("name", "Unknown")
            ts_str = article.get("date", "")
            try:
                ts = int(datetime.fromisoformat(ts_str).timestamp() * 1000) if ts_str else 0
            except (ValueError, TypeError):
                ts = 0
            news_items.append((title, source, ts))

        print(f"[NEWS] Fetched {len(news_items)} articles")
        return news_items
    except Exception as e:
        print(f"[ERROR] News fetch failed: {e}")
        return []


def fetch_fear_greed_index() -> List[Dict]:
    try:
        url = "https://api.alternative.me/fng/?limit=30"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        entries = data.get("data", [])
        print(f"[FGI] Fear & Greed Index fetched: {len(entries)} days, latest={entries[0]['value']} ({entries[0]['value_classification']})")
        return entries
    except Exception as e:
        print(f"[ERROR] Fear & Greed Index fetch failed: {e}")
        return []


def get_latest_fear_greed_value() -> int:
    entries = fetch_fear_greed_index()
    if entries:
        return int(entries[0].get("value", 50))
    return 50


# ---------------------------------------------------------------------------
# Module 4: LLM Inference (DeepSeek)
# ---------------------------------------------------------------------------

def load_instructions() -> str:
    path = os.path.join(BASE_DIR, "instructions.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print("[ERROR] instructions.md not found")
        return "You are a Bitcoin trading assistant. Output JSON only."


def extract_json(content: str) -> Optional[Dict]:
    # Method 1: direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Method 2: code block extraction
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Method 3: first { to last }
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def validate_decision(parsed: Dict, balances: Dict) -> Dict:
    decision = parsed.get("decision", "hold")
    percentage = parsed.get("percentage", 0)
    reason = parsed.get("reason", "No reason provided")

    # Normalize decision
    if decision not in ("buy", "sell", "hold"):
        print(f"[WARN] Invalid decision '{decision}', defaulting to hold")
        decision = "hold"
        percentage = 0

    # Clamp percentage
    try:
        percentage = int(percentage)
    except (ValueError, TypeError):
        percentage = 0
    percentage = max(0, min(percentage, 100))

    # Safety overrides
    krw_balance = balances.get("krw_balance", 0)
    btc_balance = balances.get("btc_balance", 0)

    if decision == "buy" and krw_balance < MIN_TRADE_KRW:
        print(f"[SAFETY] KRW balance {krw_balance:.0f} below minimum, switching to hold")
        decision = "hold"
        percentage = 0

    if decision == "sell" and btc_balance <= 0:
        print(f"[SAFETY] No BTC to sell, switching to hold")
        decision = "hold"
        percentage = 0

    if decision == "buy" and percentage > 30:
        print(f"[SAFETY] Percentage {percentage}% capped at 30%")
        percentage = 30

    return {"decision": decision, "percentage": percentage, "reason": reason}


def analyze_with_deepseek(
    market_data: str,
    news_data: List,
    previous_decisions: List[Dict],
    fear_greed_data: List[Dict],
    current_status: Dict,
    onchain_context: Dict
) -> Optional[Dict]:
    instructions = load_instructions()

    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f"## Data 0: On-Chain & Macro Context (Stablecoins, Competing Chains, Layer-1 MCaps)\n```json\n{json.dumps(onchain_context, ensure_ascii=False)}\n```"},
        {"role": "user", "content": f"## Data 1: Crypto News\n{json.dumps(news_data, ensure_ascii=False)}"},
        {"role": "user", "content": f"## Data 2: Market Analysis (BTC OHLCV + Technical Indicators)\n```json\n{market_data}\n```"},
        {"role": "user", "content": f"## Data 3: Previous Decisions\n{json.dumps(previous_decisions, ensure_ascii=False, default=str)}"},
        {"role": "user", "content": f"## Data 4: Fear & Greed Index\n{json.dumps(fear_greed_data, ensure_ascii=False)}"},
        {"role": "user", "content": f"## Data 5: Current State\n{json.dumps(current_status, ensure_ascii=False, default=str)}"},
    ]

    for attempt in range(5):
        try:
            print(f"[LLM] Calling DeepSeek (attempt {attempt + 1}/5)...")
            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )
            content = response.choices[0].message.content
            print(f"[LLM] Raw response ({len(content)} chars): {content[:200]}...")

            parsed = extract_json(content)
            if parsed:
                validated = validate_decision(parsed, current_status)
                print(f"[LLM] Decision: {validated['decision']} {validated['percentage']}%")
                return validated
            else:
                print(f"[WARN] Could not extract JSON from response, retrying...")

        except Exception as e:
            print(f"[ERROR] DeepSeek API call failed (attempt {attempt + 1}): {e}")

        if attempt < 4:
            wait = 2 ** attempt
            print(f"[RETRY] Waiting {wait}s before retry...")
            time.sleep(wait)

    print("[ERROR] All 5 DeepSeek attempts failed")
    return None


# ---------------------------------------------------------------------------
# Main Decision Loop
# ---------------------------------------------------------------------------

circuit_breaker_active = False


def make_decision_and_execute():
    global circuit_breaker_active

    print(f"\n{'='*60}")
    print(f"[LOOP] Starting decision cycle at {datetime.now().isoformat()}")
    print(f"{'='*60}")

    # Check circuit breaker
    if circuit_breaker_active:
        print("[CIRCUIT BREAKER] Active - skipping all trades. Manual restart required.")
        return

    consecutive_losses = db.count_consecutive_losses()
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        circuit_breaker_active = True
        print(f"[CIRCUIT BREAKER] {consecutive_losses} consecutive losses detected. Halting trades.")
        return

    # Step 1: Fetch market data
    print("[DATA] Fetching market data...")
    market_data = fetch_market_data()

    # Step 0: Fetch on-chain context (stablecoins, competing chains)
    print("[DATA] Fetching on-chain context...")
    onchain_context = fetch_onchain_context()

    # Step 2: Fetch news and sentiment
    print("[DATA] Fetching news and sentiment...")
    news_data = fetch_news()
    fear_greed_data = fetch_fear_greed_index()

    # Step 3: Get current balances
    balances = trader.get_current_balances()
    orderbook = fetch_orderbook()
    current_status = {
        "current_time": int(datetime.now().timestamp() * 1000),
        "orderbook": orderbook,
        "btc_balance": balances["btc_balance"],
        "krw_balance": balances["krw_balance"],
        "btc_avg_buy_price": balances["btc_avg_buy_price"],
        "btc_krw_price": balances["btc_krw_price"]
    }
    print(f"[STATUS] BTC: {balances['btc_balance']:.8f}, KRW: {balances['krw_balance']:.0f}, Price: {balances['btc_krw_price']:.0f}")

    # Step 4: Get previous decisions
    previous_decisions = db.get_recent_trades(limit=10)

    # Step 5: LLM analysis
    print("[LLM] Requesting analysis from DeepSeek...")
    decision = analyze_with_deepseek(
        market_data, news_data, previous_decisions, fear_greed_data, current_status, onchain_context
    )

    if decision is None:
        print("[ERROR] Failed to get valid decision from DeepSeek, holding")
        return

    # Step 6: Execute trade
    action = decision["decision"]
    percentage = decision["percentage"]

    if action == "hold":
        print(f"[DECISION] HOLD - {decision['reason'][:100]}...")
        # Record hold for history
        db.record_trade({
            "decision": "hold", "percentage": 0, "reason": decision["reason"],
            "btc_balance": balances["btc_balance"], "krw_balance": balances["krw_balance"],
            "btc_avg_buy_price": balances["btc_avg_buy_price"], "btc_krw_price": balances["btc_krw_price"]
        })

    elif action == "buy":
        fg_value = get_latest_fear_greed_value()
        ratio = trader.adjust_trade_ratio(percentage, fg_value, "buy")
        krw_to_use = balances["krw_balance"] * ratio
        print(f"[DECISION] BUY {ratio*100:.1f}% = {krw_to_use:.0f} KRW (FGI={fg_value})")
        result = trader.execute_buy(krw_to_use)
        if result:
            balances = trader.get_current_balances()
            db.record_trade({
                "decision": "buy", "percentage": ratio * 100, "reason": decision["reason"],
                "btc_balance": balances["btc_balance"], "krw_balance": balances["krw_balance"],
                "btc_avg_buy_price": balances["btc_avg_buy_price"], "btc_krw_price": balances["btc_krw_price"]
            })

    elif action == "sell":
        fg_value = get_latest_fear_greed_value()
        ratio = trader.adjust_trade_ratio(percentage, fg_value, "sell")
        btc_to_sell = balances["btc_balance"] * ratio
        print(f"[DECISION] SELL {ratio*100:.1f}% = {btc_to_sell:.8f} BTC (FGI={fg_value})")
        result = trader.execute_sell(btc_to_sell)
        if result:
            balances = trader.get_current_balances()
            db.record_trade({
                "decision": "sell", "percentage": ratio * 100, "reason": decision["reason"],
                "btc_balance": balances["btc_balance"], "krw_balance": balances["krw_balance"],
                "btc_avg_buy_price": balances["btc_avg_buy_price"], "btc_krw_price": balances["btc_krw_price"]
            })

    print(f"[LOOP] Cycle complete. Next run in ~{TRADE_INTERVAL_HOURS} hours.")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("BTC Auto-Trade Bot (v2 - DeepSeek Edition)")
    print(f"Ticker: {TICKER}")
    print(f"Interval: every {TRADE_INTERVAL_HOURS} hour(s)")
    print(f"Max per trade: {MAX_SINGLE_TRADE_PCT*100:.0f}% of KRW balance")
    print(f"LLM: DeepSeek v4 Pro (deepseek-v4-pro)")
    print(f"DB: {DB_PATH}")
    if DRY_RUN:
        print("MODE: DRY RUN (no real trades, simulated balances)")
        print("      Set DRY_RUN=false in .env to enable live trading")
    else:
        print(f"MODE: LIVE (Real Upbit trading)")
    print("=" * 60)

    # Run immediately on startup
    print("\n[STARTUP] Running initial decision cycle...")
    make_decision_and_execute()

    # Schedule periodic runs
    schedule.every(TRADE_INTERVAL_HOURS).hours.do(make_decision_and_execute)
    print(f"[SCHEDULE] Next run scheduled in {TRADE_INTERVAL_HOURS} hour(s)")
    print("[SCHEDULE] Entering loop - press Ctrl+C to stop\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] User interrupted. Exiting.")
