#!/usr/bin/env python3
"""
Privacy Cash Withdrawal Monitor

Monitors the Privacy Cash (Light Protocol) pool for large withdrawals
and sends alerts to Telegram.

Usage:
    python3 privacy-cash-monitor.py [--threshold 10000] [--interval 60]
"""

import json
import os
import time
import argparse
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# Configuration
PRIVACY_CASH_PROGRAM = "9fhQBbumKEFuXtMBDw8AaQyAjCorLGJQiS3skWZdQyQD"
PRIVACY_CASH_POOL = "4AV2Qzp3N4c9RfzyEbNZs2wqWfW4EwKnnxFAZCndvfGh"
# Set HELIUS_API_KEY via environment variable
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")
SOLANA_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

# State file to track processed transactions
STATE_FILE = Path.home() / "Documents/GitHub/claude/tools/privacy-cash/state.json"

# Telegram config (uses existing gateway config)
TG_CONFIG = Path.home() / "Documents/GitHub/claude/gateway/config.yaml"


def load_tg_config():
    """Load Telegram bot config from gateway config."""
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


def send_telegram_alert(message: str):
    """Send alert to Telegram."""
    config = load_tg_config()
    if not config["token"] or not config["chat_id"]:
        print(f"TG not configured. Message: {message}")
        return False

    try:
        url = f"https://api.telegram.org/bot{config['token']}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": config["chat_id"],
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"Failed to send TG alert: {e}")
        return False


def load_state() -> dict:
    """Load processed transaction signatures."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed": [], "last_check": None}


def save_state(state: dict):
    """Save state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_pool_transactions(limit: int = 50) -> list:
    """Get recent transactions involving the Privacy Cash pool."""
    try:
        # Get signatures for the pool address
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [PRIVACY_CASH_POOL, {"limit": limit}]
        }, timeout=30)

        data = resp.json()
        if "result" in data:
            return data["result"]
        return []
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []


def get_transaction_details(signature: str) -> dict:
    """Get full transaction details."""
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        }, timeout=30)

        data = resp.json()
        return data.get("result", {})
    except Exception as e:
        print(f"Error fetching tx {signature}: {e}")
        return {}


def analyze_transaction(tx: dict) -> Optional[Dict]:
    """
    Analyze a transaction to detect Privacy Cash withdrawals.
    Returns withdrawal info if detected, None otherwise.
    """
    if not tx:
        return None

    meta = tx.get("meta", {})
    if meta.get("err"):
        return None  # Failed transaction

    # Look for transfers FROM the pool (withdrawals)
    inner_instructions = meta.get("innerInstructions", [])

    for inner in inner_instructions:
        for ix in inner.get("instructions", []):
            parsed = ix.get("parsed", {})
            if parsed.get("type") == "transfer":
                info = parsed.get("info", {})
                source = info.get("source")
                dest = info.get("destination")
                lamports = info.get("lamports", 0)

                # Check if this is an outgoing transfer from the pool
                if source == PRIVACY_CASH_POOL and dest != PRIVACY_CASH_POOL:
                    sol_amount = lamports / 1e9
                    return {
                        "type": "withdrawal",
                        "destination": dest,
                        "amount_sol": sol_amount,
                        "amount_usd": sol_amount * get_sol_price(),
                        "signature": tx.get("transaction", {}).get("signatures", [None])[0],
                        "block_time": tx.get("blockTime")
                    }

    # Also check pre/post balance changes for the pool
    account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    pre_balances = meta.get("preBalances", [])
    post_balances = meta.get("postBalances", [])

    for i, key in enumerate(account_keys):
        pubkey = key.get("pubkey") if isinstance(key, dict) else key
        if pubkey == PRIVACY_CASH_POOL and i < len(pre_balances) and i < len(post_balances):
            diff = pre_balances[i] - post_balances[i]
            if diff > 1e9:  # More than 1 SOL withdrawn
                sol_amount = diff / 1e9

                # Find likely destination (account with largest positive diff)
                max_gain = 0
                dest = None
                for j, k in enumerate(account_keys):
                    pk = k.get("pubkey") if isinstance(k, dict) else k
                    if j < len(pre_balances) and j < len(post_balances):
                        gain = post_balances[j] - pre_balances[j]
                        if gain > max_gain and pk != PRIVACY_CASH_POOL:
                            max_gain = gain
                            dest = pk

                return {
                    "type": "withdrawal",
                    "destination": dest,
                    "amount_sol": sol_amount,
                    "amount_usd": sol_amount * get_sol_price(),
                    "signature": tx.get("transaction", {}).get("signatures", [None])[0],
                    "block_time": tx.get("blockTime")
                }

    return None


def get_sol_price() -> float:
    """Get current SOL price in USD."""
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            timeout=10
        )
        return resp.json().get("solana", {}).get("usd", 150)  # Default to $150 if API fails
    except:
        return 150


def format_alert(withdrawal: dict) -> str:
    """Format withdrawal info as Telegram alert."""
    ts = datetime.fromtimestamp(withdrawal["block_time"]) if withdrawal.get("block_time") else datetime.now()

    return f"""🚨 *Privacy Cash Withdrawal Detected*

💰 *Amount:* {withdrawal['amount_sol']:.2f} SOL (~${withdrawal['amount_usd']:,.0f})
📍 *Destination:* `{withdrawal['destination']}`
🔗 *TX:* [View on Solscan](https://solscan.io/tx/{withdrawal['signature']})
⏰ *Time:* {ts.strftime('%Y-%m-%d %H:%M:%S')} UTC

Check destination wallet for further activity."""


def monitor_once(threshold_usd: float) -> list:
    """Run one monitoring cycle. Returns list of alerts sent."""
    state = load_state()
    processed = set(state.get("processed", []))
    alerts = []

    print(f"[{datetime.now()}] Checking Privacy Cash pool...")

    txs = get_pool_transactions(limit=50)
    print(f"  Found {len(txs)} recent transactions")

    new_processed = []
    for tx_info in txs:
        sig = tx_info.get("signature")
        if not sig or sig in processed:
            continue

        new_processed.append(sig)

        # Get full transaction details
        tx = get_transaction_details(sig)
        withdrawal = analyze_transaction(tx)

        if withdrawal and withdrawal.get("amount_usd", 0) >= threshold_usd:
            print(f"  🚨 Large withdrawal: ${withdrawal['amount_usd']:,.0f} to {withdrawal['destination'][:16]}...")
            alert_msg = format_alert(withdrawal)
            if send_telegram_alert(alert_msg):
                alerts.append(withdrawal)
            else:
                print(f"  Failed to send alert")

    # Update state (keep last 500 signatures)
    all_processed = list(processed) + new_processed
    state["processed"] = all_processed[-500:]
    state["last_check"] = datetime.now().isoformat()
    save_state(state)

    print(f"  Processed {len(new_processed)} new transactions, {len(alerts)} alerts sent")
    return alerts


def main():
    parser = argparse.ArgumentParser(description="Monitor Privacy Cash for large withdrawals")
    parser.add_argument("--threshold", type=float, default=10000,
                        help="USD threshold for alerts (default: 10000)")
    parser.add_argument("--interval", type=int, default=60,
                        help="Check interval in seconds (default: 60)")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit")
    args = parser.parse_args()

    print(f"Privacy Cash Monitor")
    print(f"  Pool: {PRIVACY_CASH_POOL}")
    print(f"  Threshold: ${args.threshold:,.0f}")
    print(f"  Interval: {args.interval}s")
    print()

    if args.once:
        monitor_once(args.threshold)
        return

    # Continuous monitoring
    while True:
        try:
            monitor_once(args.threshold)
        except Exception as e:
            print(f"Error in monitoring cycle: {e}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
