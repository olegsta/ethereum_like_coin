from collections import defaultdict
import time

import requests as rq
from web3 import Web3, HTTPProvider

from .models import Settings, db
from .config import config
from .logging import logger
from .token import Token, get_all_accounts
from .utils import chain_head


# ---------------------------------------------------------------------------
# Web3 client
# ---------------------------------------------------------------------------

w3 = Web3(
    HTTPProvider(
        config["FULLNODE_URL"],
        request_kwargs={"timeout": int(config["FULLNODE_TIMEOUT"])},
    )
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def handle_event(tx) -> None:
    logger.info(f"new transaction: {tx!r}")


def walletnotify_shkeeper(symbol: str, txid: str) -> bool:
    """Notify SHKeeper about a transaction, retrying until success."""
    logger.warning(f"Notify SHKeeper {symbol}/{txid}")

    url = f'http://{config["SHKEEPER_HOST"]}/api/v1/walletnotify/{symbol}/{txid}'
    headers = {"X-Shkeeper-Backend-Key": config["SHKEEPER_KEY"]}

    while True:
        try:
            response = rq.post(url, headers=headers).json()

            if response.get("status") == "success":
                logger.warning(f"Notify success {symbol}/{txid}")
                return True

            logger.warning(f"Notify failed: {response}")
            time.sleep(5)

        except Exception as exc:
            logger.warning(f"Notify error {symbol}/{txid}: {exc}")
            time.sleep(10)


def _should_drain(sender: str, recipient: str, accounts: set, ref_block: int) -> bool:
    """Return True if the recipient account should be drained after this transfer."""
    return (
        sender not in accounts
        and recipient in accounts
        and (chain_head(w3) - ref_block) < 40
    )


# ---------------------------------------------------------------------------
# Block processing
# ---------------------------------------------------------------------------

def process_block(block, accounts: set, last_batch_block: int) -> None:
    # Avoid early circular imports in some environments
    from .tasks import drain_account

    for tx in block.transactions:
        tx_from = tx["from"]
        tx_to   = tx["to"]

        if tx_from not in accounts and tx_to not in accounts:
            continue

        handle_event(tx)
        walletnotify_shkeeper(config["COIN_SYMBOL"], tx["hash"].hex())

        if _should_drain(tx_from, tx_to, accounts, last_batch_block):
            drain_account.delay(config["COIN_SYMBOL"], tx_to)


def process_token_transfers(
    token_names: list[str],
    accounts: set,
    start_block: int,
    end_block: int,
) -> None:
    from .tasks import drain_account

    for token_name in token_names:
        token = Token(token_name)

        for tx in token.get_all_transfers(start_block, end_block):
            from_addr = token.provider.to_checksum_address(tx["from"])
            to_addr   = token.provider.to_checksum_address(tx["to"])

            if from_addr not in accounts and to_addr not in accounts:
                continue

            handle_event(tx)
            walletnotify_shkeeper(token_name, tx["txid"])

            if _should_drain(from_addr, to_addr, accounts, end_block):
                drain_account.delay(token_name, to_addr)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _save_last_block(app, block_number: int) -> None:
    settings = Settings.query.filter_by(name="last_block").first()
    settings.value = str(block_number)
    with app.app_context():
        db.session.add(settings)
        db.session.commit()


def _init_last_block(app) -> None:
    """Persist the current chain head as the starting checkpoint (once)."""
    already_set = Settings.query.filter_by(name="last_block").first()
    locked      = config["LAST_BLOCK_LOCKED"].lower() == "true"

    if not already_set and not locked:
        with app.app_context():
            db.session.add(Settings(name="last_block", value=str(chain_head(w3))))
            db.session.commit()


# ---------------------------------------------------------------------------
# Main scanner loop
# ---------------------------------------------------------------------------

def log_loop(last_checked_block: int, check_interval: int) -> None:
    from app import create_app

    app = create_app()
    app.app_context().push()

    token_names = list(config["TOKENS"][config["CURRENT_NETWORK"]].keys())
    batch_size  = config["BLOCK_SCANNER_BATCH_SIZE"]

    while True:
        latest_block = chain_head(w3)
        accounts     = set(get_all_accounts())

        if not last_checked_block:
            last_checked_block = latest_block

        if last_checked_block > latest_block:
            logger.warning(
                "last_checked_block (%s) > chain head (%s) — skipping cycle",
                last_checked_block,
                latest_block,
            )
            time.sleep(check_interval)
            continue

        # ── Scan blocks in batches ──────────────────────────────────────────
        while last_checked_block < latest_block:
            start = last_checked_block + 1
            end   = min(last_checked_block + batch_size, latest_block)

            logger.warning(f"Scanning blocks {start} – {end}")

            with w3.batch_requests() as batch:
                for block_num in range(start, end + 1):
                    batch.add(w3.eth.get_block(block_num, True))

                for block in batch.execute():
                    process_block(block, accounts, end)

            process_token_transfers(token_names, accounts, start, end)

            last_checked_block = end
            _save_last_block(app, end)

        time.sleep(check_interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def events_listener() -> None:
    from app import create_app

    app = create_app()
    app.app_context().push()

    while True:
        accounts = set(get_all_accounts())

        if not accounts:
            logger.warning("No accounts yet — waiting 60 s...")
            time.sleep(60)
            continue

        _init_last_block(app)

        try:
            last_block = Settings.query.filter_by(name="last_block").first()
            log_loop(
                int(last_block.value),
                int(config["CHECK_NEW_BLOCK_EVERY_SECONDS"]),
            )
        except Exception as exc:
            logger.exception(f"Scanner crashed: {exc}")
            time.sleep(60)