#!/usr/bin/env python3
"""
Privacy Cash Pool Hourly Report

Generates chart and sends to Telegram.
Uses incremental caching to avoid re-fetching all transactions.
"""

import json
import os
import requests
import tempfile
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import argparse

# Configuration
PRIVACY_CASH_POOL = "4AV2Qzp3N4c9RfzyEbNZs2wqWfW4EwKnnxFAZCndvfGh"
# Set HELIUS_API_KEY via environment variable
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
SOLANA_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
YOUR_DEPOSIT_SOL = 782.6

# Files
DATA_DIR = Path.home() / "Documents/GitHub/claude/tools/privacy-cash"
HISTORY_FILE = DATA_DIR / "history.json"
TG_CONFIG = Path.home() / "Documents/GitHub/claude/gateway/config.yaml"
TG_TOPIC_ID = int(os.environ.get("TG_TOPIC_ID", "0"))


def load_tg_config():
    try:
        import yaml
        with open(TG_CONFIG) as f:
            config = yaml.safe_load(f)
        return {
            "token": config.get("telegram", {}).get("bot_token"),
            "chat_id": config.get("telegram", {}).get("allowed_users", [None])[0]
        }
    except Exception as e:
        print(f"Warning: Could not load TG config: {e}")
        return {"token": None, "chat_id": None}


def send_telegram_photo(image_path: str, caption: str):
    config = load_tg_config()
    if not config["token"] or not config["chat_id"]:
        print(f"TG not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{config['token']}/sendPhoto"
        with open(image_path, 'rb') as photo:
            resp = requests.post(url, data={
                "chat_id": config["chat_id"],
                "caption": caption,
                "parse_mode": "Markdown",
                "message_thread_id": TG_TOPIC_ID
            }, files={"photo": photo}, timeout=30)
        return resp.ok
    except Exception as e:
        print(f"Failed to send: {e}")
        return False


def get_sol_price() -> float:
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            timeout=10
        )
        return resp.json().get("solana", {}).get("usd", 200)
    except:
        return 200


def load_history() -> Dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"transactions": [], "last_signature": None}


def save_history(history: Dict):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)


def fetch_all_transactions(max_txs: int = 5000) -> List[Dict]:
    """Fetch all transactions using pagination."""
    all_sigs = []
    before = None

    while len(all_sigs) < max_txs:
        params = [PRIVACY_CASH_POOL, {"limit": 1000}]
        if before:
            params[1]["before"] = before

        try:
            resp = requests.post(SOLANA_RPC, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": params
            }, timeout=60)
            result = resp.json().get("result", [])
            if not result:
                break
            all_sigs.extend(result)
            before = result[-1].get("signature")
            print(f"  Fetched {len(all_sigs)} signatures...")
        except Exception as e:
            print(f"Error: {e}")
            break

    return all_sigs


def get_transaction_flow(signature: str) -> Tuple[float, float, int]:
    """Get (inflow, outflow, block_time) for a transaction."""
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        }, timeout=30)

        tx = resp.json().get("result", {})
        if not tx:
            return 0, 0, 0

        meta = tx.get("meta", {})
        if meta.get("err"):
            return 0, 0, 0

        block_time = tx.get("blockTime", 0)
        account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        pre = meta.get("preBalances", [])
        post = meta.get("postBalances", [])

        for i, key in enumerate(account_keys):
            pubkey = key.get("pubkey") if isinstance(key, dict) else key
            if pubkey == PRIVACY_CASH_POOL and i < len(pre) and i < len(post):
                diff = (post[i] - pre[i]) / 1e9
                if diff > 0.001:
                    return diff, 0, block_time
                elif diff < -0.001:
                    return 0, abs(diff), block_time
        return 0, 0, block_time
    except:
        return 0, 0, 0


def update_history(max_txs: int = 5000, batch_size: int = 200) -> Dict:
    """Update history with transactions. Processes batch_size per run."""
    history = load_history()
    existing = {t["sig"] for t in history["transactions"]}

    print(f"Current history: {len(existing)} transactions")

    # Fetch all signatures (fast)
    print("Fetching signatures...")
    all_sigs = fetch_all_transactions(max_txs=max_txs)
    print(f"Total signatures: {len(all_sigs)}")

    # Find new signatures
    new_sigs = [s for s in all_sigs if s.get("signature") not in existing]
    print(f"New signatures: {len(new_sigs)}")

    # Process only batch_size at a time (oldest first)
    to_process = list(reversed(new_sigs))[:batch_size]
    print(f"Processing batch of {len(to_process)}...")

    new_txs = []
    for i, sig_info in enumerate(to_process):
        sig = sig_info.get("signature")
        if not sig:
            continue

        inflow, outflow, block_time = get_transaction_flow(sig)
        if block_time:
            new_txs.append({
                "sig": sig,
                "inflow": inflow,
                "outflow": outflow,
                "time": block_time
            })

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(to_process)}...")

    if new_txs:
        history["transactions"].extend(new_txs)
        history["transactions"].sort(key=lambda x: x["time"])
        save_history(history)
        print(f"Added {len(new_txs)} transactions (total: {len(history['transactions'])})")

    remaining = len(new_sigs) - len(to_process)
    if remaining > 0:
        print(f"⚠️ {remaining} more transactions to process in next runs")

    return history


def generate_chart(history: Dict, output_path: str) -> Dict:
    """Generate the chart."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    txs = history["transactions"]
    if not txs:
        print("No transaction data")
        return None

    sol_price = get_sol_price()

    # Build time series
    times = []
    cum_inflow = []
    cum_outflow = []
    hidden_balance = []
    large_withdrawals = []

    total_in = 0
    total_out = 0

    for tx in txs:
        dt = datetime.fromtimestamp(tx["time"])
        total_in += tx["inflow"]
        total_out += tx["outflow"]

        times.append(dt)
        cum_inflow.append(total_in)
        cum_outflow.append(total_out)
        hidden_balance.append(total_in - total_out)

        if tx["outflow"] * sol_price >= 5000:
            large_withdrawals.append((dt, total_in - total_out, tx["outflow"] * sol_price))

    current_hidden = hidden_balance[-1] if hidden_balance else 0
    your_pct = (YOUR_DEPOSIT_SOL / current_hidden * 100) if current_hidden > 0 else 0

    # Create figure
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle(f'Privacy Cash Monitor - {datetime.now().strftime("%Y-%m-%d %H:%M")}', fontsize=14)

    # Top: Cumulative flows
    ax1.plot(times, cum_inflow, 'g-', linewidth=2, label='Total Inflow')
    ax1.plot(times, cum_outflow, 'r-', linewidth=2, label='Total Outflow')
    ax1.fill_between(times, cum_inflow, cum_outflow, alpha=0.1, color='gray')

    # Hidden flows (dashed)
    hidden_in = [max(0, i - o) for i, o in zip(cum_inflow, cum_outflow)]
    hidden_out = [max(0, o - i) for i, o in zip(cum_inflow, cum_outflow)]
    ax1.plot(times, hidden_in, 'g--', linewidth=1.5, alpha=0.7, label='Hidden Inflow')
    ax1.plot(times, hidden_out, 'r--', linewidth=1.5, alpha=0.7, label='Hidden Outflow')

    ax1.set_ylabel('SOL')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

    # Bottom: Hidden balance
    ax2.fill_between(times, hidden_balance, alpha=0.3, color='orange')
    ax2.plot(times, hidden_balance, 'orange', linewidth=2, label='Hidden Net')
    ax2.axhline(y=YOUR_DEPOSIT_SOL, color='blue', linestyle=':', linewidth=2,
                label=f'Your {YOUR_DEPOSIT_SOL} SOL')

    # Mark large withdrawals
    for wt, wb, wusd in large_withdrawals:
        ax2.scatter([wt], [wb], s=100, c='red', zorder=5, edgecolors='darkred')
        ax2.annotate(f'${wusd/1000:.0f}k', (wt, wb), textcoords="offset points",
                    xytext=(0, 10), ha='center', fontsize=8, color='red')

    ax2.set_title(f'Hidden balance: {current_hidden:.0f} SOL (your {YOUR_DEPOSIT_SOL} = {your_pct:.0f}%)')
    ax2.set_ylabel('SOL')
    ax2.set_xlabel('Time')
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=0)

    if large_withdrawals:
        ax2.scatter([], [], s=100, c='red', label=f'>$5k withdrawals ({len(large_withdrawals)})')
        ax2.legend(loc='upper left')

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    # Count recent txs
    one_hour_ago = datetime.now().timestamp() - 3600
    new_txs = sum(1 for t in txs if t["time"] > one_hour_ago)

    return {
        "total_txs": len(txs),
        "new_txs": new_txs,
        "hidden_balance": current_hidden,
        "your_pct": your_pct,
        "large_withdrawals": len(large_withdrawals)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--output", type=str)
    parser.add_argument("--max-txs", type=int, default=5000)
    args = parser.parse_args()

    print(f"[{datetime.now()}] Privacy Cash Report")

    # Update history
    history = update_history(max_txs=args.max_txs)

    if not history["transactions"]:
        print("No data available")
        return

    # Generate chart
    output_path = args.output or tempfile.mktemp(suffix=".png")
    stats = generate_chart(history, output_path)

    if not stats:
        return

    print(f"Chart: {output_path}")
    print(f"Stats: {json.dumps(stats)}")

    caption = f"""📊 *Privacy Cash Monitor*
Updated: {datetime.now().strftime('%H:%M')}

New txs: {stats['new_txs']}
Total: {stats['total_txs']} txs
Hidden balance: {stats['hidden_balance']:.0f} SOL
Your {YOUR_DEPOSIT_SOL} SOL = {stats['your_pct']:.0f}%"""

    if stats['large_withdrawals'] > 0:
        caption += f"\n\n⚠️ Large withdrawals (>$5k): {stats['large_withdrawals']}"

    if not args.no_send:
        if send_telegram_photo(output_path, caption):
            print("Sent to Telegram")
        else:
            print("Failed to send")
    else:
        print(f"\nCaption:\n{caption}")


if __name__ == "__main__":
    main()
