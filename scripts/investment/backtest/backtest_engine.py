"""
BTC Trading Bot Backtest Engine
Supports historical simulation and live performance analysis.

Two modes:
    1. Historical Backtest (rule-based strategies, no LLM)
       - Simulates buy/sell decisions using configurable technical indicator rules
       - Computes: Sharpe Ratio, Max Drawdown, Win Rate, CAGR, Calmar, Sortino
    2. Live Performance Analysis
       - Reads trading_history from SQLite DB
       - Computes the same metrics on actual LLM-driven trades

Usage:
    python backtest_engine.py --mode rule --start 2025-01-01 --end 2026-06-01
    python backtest_engine.py --mode live --db-path ../autotrade/trading.db
    python backtest_engine.py --mode rule --strategy macd_cross --plot

Output: data/backtest_report.json + optional chart
"""

import os
import sys
import json
import math
import sqlite3
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable

import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Add project root to path for autotrade imports
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "trading.db")

# ---------------------------------------------------------------------------
# Performance Metrics
# ---------------------------------------------------------------------------

def compute_metrics(
    equity_curve: List[float],
    trades: List[Dict],
    risk_free_rate: float = 0.03,
    trading_days: int = 365
) -> Dict:
    """
    Compute comprehensive performance metrics from an equity curve and trade list.

    Args:
        equity_curve: List of portfolio values over time (daily or per-trade snapshots)
        trades: List of trade result dicts with 'pnl', 'pnl_pct', 'entry_time', 'exit_time'
        risk_free_rate: Annual risk-free rate (default: 3% for US T-bill proxy)
        trading_days: Days per year for annualization (365 for crypto, 252 for stocks)

    Returns:
        Dict of performance metrics
    """
    if len(equity_curve) < 2:
        return {"error": "Insufficient data for metrics"}

    initial = equity_curve[0]
    final = equity_curve[-1]

    # --- Basic P&L ---
    total_return = (final / initial - 1) if initial > 0 else 0
    total_pnl = final - initial

    # Calculate daily returns from equity curve
    equity_series = pd.Series(equity_curve)
    returns = equity_series.pct_change().dropna()

    if len(returns) == 0:
        return {"error": "No return data to compute metrics"}

    # --- CAGR (Compound Annual Growth Rate) ---
    n_days = len(returns)
    n_years = n_days / trading_days
    cagr = (final / initial) ** (1 / n_years) - 1 if n_years > 0 and initial > 0 else 0

    # --- Volatility (Annualized) ---
    ann_vol = float(returns.std() * np.sqrt(trading_days)) if len(returns) > 1 else 0

    # --- Sharpe Ratio ---
    excess_returns = returns - (risk_free_rate / trading_days)
    sharpe = float(excess_returns.mean() / returns.std() * np.sqrt(trading_days)) if returns.std() > 0 else 0

    # --- Sortino Ratio (downside deviation only) ---
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0
    sortino = float(excess_returns.mean() / downside_std * np.sqrt(trading_days)) if downside_std > 0 else 0

    # --- Max Drawdown ---
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = float(drawdown.min())
    max_drawdown_duration = 0
    if max_drawdown < 0:
        # Count consecutive negative drawdown days
        dd_period = 0
        max_dd_period = 0
        for dd in drawdown:
            if dd < 0:
                dd_period += 1
                max_dd_period = max(max_dd_period, dd_period)
            else:
                dd_period = 0
        max_drawdown_duration = max_dd_period

    # --- Calmar Ratio (CAGR / Max Drawdown) ---
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0

    # --- Trade-Level Metrics ---
    winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in trades if t.get("pnl", 0) < 0]

    total_trades = len(trades)
    win_count = len(winning_trades)
    loss_count = len(losing_trades)
    win_rate = win_count / total_trades if total_trades > 0 else 0

    avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([t["pnl"] for t in losing_trades]) if losing_trades else 0
    avg_win_pct = np.mean([t.get("pnl_pct", 0) for t in winning_trades]) if winning_trades else 0
    avg_loss_pct = np.mean([t.get("pnl_pct", 0) for t in losing_trades]) if losing_trades else 0

    # Profit Factor (Gross Profit / Gross Loss)
    gross_profit = sum(t["pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Expectancy (average P&L per trade)
    expectancy = sum(t.get("pnl", 0) for t in trades) / total_trades if total_trades > 0 else 0

    # Maximum consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    curr_wins = 0
    curr_losses = 0
    for t in trades:
        pnl = t.get("pnl", 0)
        if pnl > 0:
            curr_wins += 1
            curr_losses = 0
            max_consec_wins = max(max_consec_wins, curr_wins)
        elif pnl < 0:
            curr_losses += 1
            curr_wins = 0
            max_consec_losses = max(max_consec_losses, curr_losses)
        else:
            curr_wins = 0
            curr_losses = 0

    # --- Final Assembly ---
    return {
        "summary": {
            "total_return_pct": round(total_return * 100, 2),
            "total_pnl": round(total_pnl, 2),
            "cagr_pct": round(cagr * 100, 2),
            "annualized_volatility_pct": round(ann_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "max_drawdown_duration_days": max_drawdown_duration,
            "calmar_ratio": round(calmar, 3),
        },
        "trade_metrics": {
            "total_trades": total_trades,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate_pct": round(win_rate * 100, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_pct": round(avg_win_pct, 4),
            "avg_loss_pct": round(avg_loss_pct, 4),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
            "expectancy": round(expectancy, 2),
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
        },
        "risk_metrics": {
            "risk_free_rate_pct": risk_free_rate * 100,
            "annualized_downside_volatility_pct": round(downside_std * np.sqrt(trading_days) * 100, 2),
            "value_at_risk_95_pct": round(float(returns.quantile(0.05)) * 100, 3),
            "conditional_var_95_pct": round(float(returns[returns <= returns.quantile(0.05)].mean()) * 100, 3),
        },
        "metadata": {
            "start_date": str(equity_series.index[0]) if hasattr(equity_series, 'index') else "N/A",
            "end_date": str(equity_series.index[-1]) if hasattr(equity_series, 'index') else "N/A",
            "trading_days": n_days,
            "n_years": round(n_years, 2),
            "generated_at": datetime.now().isoformat(),
        }
    }


# ---------------------------------------------------------------------------
# Mode 1: Rule-Based Backtest (No LLM)
# ---------------------------------------------------------------------------

# Technical indicator calculation (same as autotrade.py Module 1)
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["SMA_10"] = close.rolling(window=10).mean()
    df["EMA_10"] = close.ewm(span=10, adjust=False).mean()
    df["SMA_20"] = close.rolling(window=20).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df["RSI_14"] = 100 - (100 / (1 + rs))

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["Signal_Line"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Histogram"] = df["MACD"] - df["Signal_Line"]

    df["Middle_Band"] = close.rolling(window=20).mean()
    std_20 = close.rolling(window=20).std()
    df["Upper_Band"] = df["Middle_Band"] + std_20 * 2
    df["Lower_Band"] = df["Middle_Band"] - std_20 * 2

    low_14 = low.rolling(window=14).min()
    high_14 = high.rolling(window=14).max()
    df["Stoch_%K"] = ((close - low_14) / (high_14 - low_14).replace(0, 1e-10)) * 100
    df["Stoch_%D"] = df["Stoch_%K"].rolling(window=3).mean()

    return df


def strategy_macd_cross(df: pd.DataFrame) -> pd.Series:
    """MACD crossover strategy: buy when MACD crosses above Signal, sell when below."""
    df = df.copy()
    df["MACD_above"] = (df["MACD"] > df["Signal_Line"]).astype(int)
    df["cross_up"] = (df["MACD_above"].diff() == 1).astype(int)
    df["cross_down"] = (df["MACD_above"].diff() == -1).astype(int)

    signal = pd.Series("hold", index=df.index)
    signal[df["cross_up"] == 1] = "buy"
    signal[df["cross_down"] == 1] = "sell"
    return signal


def strategy_rsi_reversal(df: pd.DataFrame) -> pd.Series:
    """RSI mean-reversion: buy at RSI < 30 (oversold), sell at RSI > 70 (overbought)."""
    df = df.copy()
    signal = pd.Series("hold", index=df.index)

    in_position = False
    for i in range(len(df)):
        if df["RSI_14"].iloc[i] < 30 and not in_position:
            signal.iloc[i] = "buy"
            in_position = True
        elif df["RSI_14"].iloc[i] > 70 and in_position:
            signal.iloc[i] = "sell"
            in_position = False
    return signal


def strategy_bb_breakout(df: pd.DataFrame) -> pd.Series:
    """Bollinger Band breakout: buy when price breaks above upper band, sell when below lower band."""
    df = df.copy()
    signal = pd.Series("hold", index=df.index)

    in_position = False
    for i in range(len(df)):
        close = df["close"].iloc[i]
        upper = df["Upper_Band"].iloc[i]
        lower = df["Lower_Band"].iloc[i]

        if close > upper and not in_position:
            signal.iloc[i] = "buy"
            in_position = True
        elif close < lower and in_position:
            signal.iloc[i] = "sell"
            in_position = False
    return signal


def strategy_ema_sma_momentum(df: pd.DataFrame) -> pd.Series:
    """EMA/SMA momentum: EMA_10 > SMA_10 is bullish, cross below is bearish."""
    df = df.copy()
    df["ema_above"] = (df["EMA_10"] > df["SMA_10"]).astype(int)
    df["cross_up"] = (df["ema_above"].diff() == 1).astype(int)
    df["cross_down"] = (df["ema_above"].diff() == -1).astype(int)

    signal = pd.Series("hold", index=df.index)
    signal[df["cross_up"] == 1] = "buy"
    signal[df["cross_down"] == 1] = "sell"
    return signal


STRATEGIES: Dict[str, Callable] = {
    "macd_cross": strategy_macd_cross,
    "rsi_reversal": strategy_rsi_reversal,
    "bb_breakout": strategy_bb_breakout,
    "ema_sma_momentum": strategy_ema_sma_momentum,
}


def run_historical_backtest(
    df: pd.DataFrame,
    strategy_fn: Callable,
    initial_capital: float = 1_000_000,
    fee_rate: float = 0.0005,
    position_size_pct: float = 0.30
) -> Tuple[List[float], List[Dict]]:
    """
    Simulate trading using a rule-based strategy on historical OHLCV data.

    Returns:
        equity_curve: Portfolio value at each bar
        trades: List of trade result dicts
    """
    df = df.copy()
    df = add_indicators(df)

    # Drop rows where indicators are NaN
    min_periods = 26  # MACD slow period
    df = df.iloc[min_periods:].copy()

    signals = strategy_fn(df)

    equity = initial_capital
    equity_curve = [equity]
    trades = []
    position = 0.0  # BTC held
    entry_price = 0.0
    entry_time = None

    for i in range(len(df)):
        price = df["close"].iloc[i]
        signal = signals.iloc[i]

        if signal == "buy" and position == 0:
            # Allocate position_size_pct of equity
            amount_krw = equity * position_size_pct * (1 - fee_rate)
            position = amount_krw / price
            entry_price = price
            entry_time = str(df.index[i])
            equity -= amount_krw / (1 - fee_rate)  # Deduct full amount including fee

        elif signal == "sell" and position > 0:
            # Sell entire position
            sell_value = position * price * (1 - fee_rate)
            pnl = sell_value - (position * entry_price)
            pnl_pct = pnl / (position * entry_price) if entry_price > 0 else 0
            equity += sell_value

            trades.append({
                "entry_time": entry_time,
                "exit_time": str(df.index[i]),
                "entry_price": round(entry_price, 2),
                "exit_price": round(price, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 4),
                "held_bars": i - df.index.get_loc(pd.Timestamp(entry_time)) if entry_time else 0,
            })

            position = 0.0
            entry_price = 0.0
            entry_time = None

        # Mark-to-market equity (unrealized P&L included)
        mtm_equity = equity + (position * price * (1 - fee_rate))
        equity_curve.append(mtm_equity)

    # Close any remaining position at last price
    if position > 0:
        final_price = df["close"].iloc[-1]
        sell_value = position * final_price * (1 - fee_rate)
        pnl = sell_value - (position * entry_price)
        pnl_pct = pnl / (position * entry_price) if entry_price > 0 else 0
        equity += sell_value

        trades.append({
            "entry_time": entry_time,
            "exit_time": str(df.index[-1]),
            "entry_price": round(entry_price, 2),
            "exit_price": round(final_price, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "held_bars": len(df) - df.index.get_loc(pd.Timestamp(entry_time)) if entry_time else 0,
        })

    return equity_curve, trades


# ---------------------------------------------------------------------------
# Mode 2: Live Performance from DB
# ---------------------------------------------------------------------------

def analyze_live_performance(db_path: str, current_btc_price: Optional[float] = None) -> Dict:
    """Analyze actual trading performance from SQLite trading_history."""
    if not os.path.exists(db_path):
        return {"error": f"Database not found: {db_path}"}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Get all actual trades (buy/sell pairs)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM trading_history
            WHERE decision != 'hold'
            ORDER BY timestamp ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
    except Exception as e:
        return {"error": f"Failed to read database: {e}"}

    if not rows:
        return {"error": "No trading data in database"}

    # Pair buys and sells to compute completed trades
    trades = []
    current_position = None  # track open position
    initial_equity = 0
    equity_points = []

    for row in rows:
        if row["decision"] == "buy":
            if current_position is None:
                current_position = {
                    "entry_time": row["timestamp"],
                    "entry_price": row["btc_krw_price"],
                    "krw_spent": row["krw_balance"] * (row["percentage"] / 100) if initial_equity == 0 else 0,
                }
                if initial_equity == 0:
                    initial_equity = row["krw_balance"] + row["btc_balance"] * row["btc_krw_price"]

        elif row["decision"] == "sell" and current_position is not None:
            exit_price = row["btc_krw_price"]
            entry_price = current_position["entry_price"]
            pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0
            pnl_krw = current_position.get("krw_spent", 0) * pnl_pct  # approximate

            trades.append({
                "entry_time": current_position["entry_time"],
                "exit_time": row["timestamp"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pct": round(pnl_pct, 4),
                "pnl": round(pnl_krw, 2),
            })
            current_position = None

        # Record equity snapshot
        total_equity = row["krw_balance"] + row["btc_balance"] * row["btc_krw_price"]
        equity_points.append(total_equity)

    if initial_equity == 0:
        initial_equity = equity_points[0] if equity_points else 100000

    if not equity_points:
        equity_points = [initial_equity]

    metrics = compute_metrics(equity_points, trades, trading_days=365)

    # Add live-trade-specific info
    metrics["from_database"] = {
        "db_path": db_path,
        "total_records": len(rows),
        "completed_trades": len(trades),
        "has_open_position": current_position is not None,
    }

    if current_position:
        metrics["from_database"]["open_position"] = {
            "entry_time": current_position["entry_time"],
            "entry_price": current_position["entry_price"],
        }

    return metrics


# ---------------------------------------------------------------------------
# BTC Data Fetcher
# ---------------------------------------------------------------------------

def fetch_btc_historical(start: str = "2020-01-01", end: str = None) -> pd.DataFrame:
    """Fetch BTC/KRW historical OHLCV from Upbit."""
    try:
        import pyupbit
        if end is None:
            end = datetime.now().strftime("%Y-%m-%d")

        print(f"[FETCH] BTC/KRW data from {start} to {end}...")
        df = pyupbit.get_ohlcv("KRW-BTC", interval="day", to=end)
        if df is None or df.empty:
            print("[ERROR] No data returned from Upbit")
            return pd.DataFrame()

        df = df[df.index >= start]
        df.rename(columns={"open": "open", "high": "high", "low": "low",
                          "close": "close", "volume": "volume"}, inplace=True)
        return df
    except Exception as e:
        print(f"[ERROR] Failed to fetch BTC data: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Report Formatter
# ---------------------------------------------------------------------------

def format_report(metrics: Dict, strategy_name: str = "") -> str:
    """Format metrics into a readable report string."""
    if "error" in metrics:
        return f"ERROR: {metrics['error']}"

    summary = metrics.get("summary", {})
    trade = metrics.get("trade_metrics", {})
    risk = metrics.get("risk_metrics", {})
    meta = metrics.get("metadata", {})

    lines = [
        "=" * 60,
        f"  BTC Trading Backtest Report ({strategy_name or 'Live Analysis'})",
        "=" * 60,
        "",
        "--- Performance Summary ---",
        f"  Total Return:       {summary.get('total_return_pct', 0):>+8.2f}%",
        f"  CAGR:               {summary.get('cagr_pct', 0):>8.2f}%",
        f"  Annualized Vol:     {summary.get('annualized_volatility_pct', 0):>8.2f}%",
        f"  Sharpe Ratio:       {summary.get('sharpe_ratio', 0):>8.3f}",
        f"  Sortino Ratio:      {summary.get('sortino_ratio', 0):>8.3f}",
        f"  Calmar Ratio:       {summary.get('calmar_ratio', 0):>8.3f}",
        f"  Max Drawdown:       {summary.get('max_drawdown_pct', 0):>+8.2f}%",
        f"  Max DD Duration:    {summary.get('max_drawdown_duration_days', 0):>8d} days",
        "",
        "--- Trade Statistics ---",
        f"  Total Trades:       {trade.get('total_trades', 0):>8d}",
        f"  Win Rate:           {trade.get('win_rate_pct', 0):>8.1f}%",
        f"  Profit Factor:      {trade.get('profit_factor', 0):>8.3f}",
        f"  Expectancy:         {trade.get('expectancy', 0):>+8.2f} KRW",
        f"  Avg Win:            {trade.get('avg_win', 0):>+8.2f} KRW ({trade.get('avg_win_pct', 0):>+.2%})",
        f"  Avg Loss:           {trade.get('avg_loss', 0):>+8.2f} KRW ({trade.get('avg_loss_pct', 0):>+.2%})",
        f"  Max Consec Wins:    {trade.get('max_consecutive_wins', 0):>8d}",
        f"  Max Consec Losses:  {trade.get('max_consecutive_losses', 0):>8d}",
        "",
        "--- Risk Metrics ---",
        f"  Risk-Free Rate:     {risk.get('risk_free_rate_pct', 0):>8.1f}%",
        f"  Downside Vol:       {risk.get('annualized_downside_volatility_pct', 0):>8.2f}%",
        f"  VaR (95%):          {risk.get('value_at_risk_95_pct', 0):>+8.3f}%",
        f"  CVaR (95%):         {risk.get('conditional_var_95_pct', 0):>+8.3f}%",
        "",
        "--- Metadata ---",
        f"  Period:             {meta.get('start_date', '?')} → {meta.get('end_date', '?')}",
        f"  Trading Days:       {meta.get('trading_days', '?')}",
        f"  Years:              {meta.get('n_years', '?')}",
    ]

    if "from_database" in metrics:
        db = metrics["from_database"]
        lines.append(f"\n--- Live DB ---")
        lines.append(f"  DB Records:         {db.get('total_records', 0)}")
        lines.append(f"  Completed Trades:   {db.get('completed_trades', 0)}")
        if db.get("has_open_position"):
            op = db.get("open_position", {})
            lines.append(f"  Open Position:      @ {op.get('entry_price', 0):,.0f} KRW (since {op.get('entry_time', '?')})")

    return "\n".join(lines)


def save_report(metrics: Dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    return output_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="BTC Trading Bot Backtest Engine")
    parser.add_argument("--mode", "-m", type=str, required=True,
                        choices=["rule", "live"],
                        help="Backtest mode: 'rule' for historical simulation, 'live' for DB analysis")
    parser.add_argument("--strategy", "-s", type=str, default="macd_cross",
                        choices=list(STRATEGIES.keys()),
                        help="Rule-based strategy to use (rule mode only)")
    parser.add_argument("--start", type=str, default="2025-01-01",
                        help="Start date for historical backtest (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None,
                        help="End date for historical backtest (default: today)")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="Initial capital in KRW (default: 1,000,000)")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH,
                        help="Path to trading.db for live analysis")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--plot", action="store_true", help="Print equity curve summary (text)")
    args = parser.parse_args()

    if args.mode == "rule":
        print("=" * 60)
        print(f"  BTC Backtest — {args.strategy.upper()} Strategy")
        print("=" * 60)

        df = fetch_btc_historical(args.start, args.end)
        if df.empty:
            print("[ERROR] No historical data available")
            return

        strategy_fn = STRATEGIES[args.strategy]
        equity_curve, trades = run_historical_backtest(df, strategy_fn, args.capital)

        if not trades:
            print("[WARN] No trades were generated by this strategy in the given period")
            return

        metrics = compute_metrics(equity_curve, trades)
        metrics["strategy"] = args.strategy

        output_path = args.output or os.path.join(DATA_DIR, f"backtest_{args.strategy}.json")
        save_report(metrics, output_path)

        print(format_report(metrics, args.strategy))
        print(f"\n[SAVED] {output_path}")

        if args.plot:
            print("\n--- Equity Curve (Last 20 Points) ---")
            for i, eq in enumerate(equity_curve[-20:]):
                bar = "█" * int(eq / args.capital * 40)
                print(f"  {eq:>12,.0f} KRW {bar}")

    elif args.mode == "live":
        print("=" * 60)
        print("  BTC Live Performance Analysis")
        print("=" * 60)

        metrics = analyze_live_performance(args.db_path)
        output_path = args.output or os.path.join(DATA_DIR, "backtest_live.json")
        save_report(metrics, output_path)

        print(format_report(metrics, "Live"))
        print(f"\n[SAVED] {output_path}")


if __name__ == "__main__":
    main()
