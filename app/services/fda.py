import time

from sqlalchemy.exc import IntegrityError

from ..encryption import Encryption
from ..logging import logger
from ..models import Accounts, Wallets, db

DEFAULT_FDA_KEY = "default"


def _normalize_fda_key(fda_key):
    if fda_key is None:
        return DEFAULT_FDA_KEY
    key = str(fda_key).strip()
    return key or DEFAULT_FDA_KEY


def _fda_wallet_query(fda_key):
    fda_key = _normalize_fda_key(fda_key)
    return Wallets.query.filter_by(type="fee_deposit", fda_key=fda_key).order_by(
        Wallets.id.asc()
    )


def _legacy_fda_wallet():
    return Wallets.query.filter_by(type="fee_deposit").filter(
        (Wallets.fda_key == None) | (Wallets.fda_key == DEFAULT_FDA_KEY)  # noqa: E711
    ).order_by(Wallets.id.asc())


def get_fda_address(fda_key=None, account=None):
    if account:
        wallet = Wallets.query.filter_by(pub_address=account).first()
        if not wallet:
            raise ValueError(f"Unknown from_account {account!r}")
        return account

    fda_key = _normalize_fda_key(fda_key)
    wallet = _fda_wallet_query(fda_key).first()
    if not wallet and fda_key == DEFAULT_FDA_KEY:
        wallet = _legacy_fda_wallet().first()

    if not wallet:
        from ..tasks import create_fee_deposit_account

        create_fee_deposit_account.delay(fda_key)
        time.sleep(10)
        wallet = _fda_wallet_query(fda_key).first()
        if not wallet and fda_key == DEFAULT_FDA_KEY:
            wallet = _legacy_fda_wallet().first()

    if not wallet:
        raise ValueError(f"Fee-deposit account not found for key {fda_key!r}")

    return wallet.pub_address


def create_fda(fda_key):
    """Create or return existing fee-deposit wallet for fda_key (idempotent)."""
    fda_key = _normalize_fda_key(fda_key)
    existing = _fda_wallet_query(fda_key).first()
    if existing:
        return existing.pub_address

    if fda_key == DEFAULT_FDA_KEY:
        legacy = _legacy_fda_wallet().first()
        if legacy:
            if not legacy.fda_key:
                legacy.fda_key = DEFAULT_FDA_KEY
                db.session.commit()
            return legacy.pub_address

    from ..config import config
    from ..token import make_provider

    provider = make_provider()
    acc = provider.eth.account.create()
    crypto_str = config["COIN_SYMBOL"]
    e = Encryption

    logger.warning("Creating fee-deposit account for key %s: %s", fda_key, acc.address)
    try:
        db.session.add(
            Wallets(
                pub_address=acc.address,
                priv_key=e.encrypt(acc.key.hex()),
                type="fee_deposit",
                fda_key=fda_key,
            )
        )
        db.session.add(
            Accounts(
                address=acc.address,
                crypto=crypto_str,
                amount=0,
                type="fee_deposit",
                fda_key=fda_key,
            )
        )
        db.session.commit()
    except IntegrityError:
        # Concurrent create for the same fda_key — keep the winner.
        db.session.rollback()
        existing = _fda_wallet_query(fda_key).first()
        if existing:
            logger.warning(
                "Concurrent FDA create for key %s; reusing %s",
                fda_key,
                existing.pub_address,
            )
            return existing.pub_address
        raise

    logger.info("Created fee-deposit account %s for key %s", acc.address, fda_key)
    return acc.address


def resolve_fda_key_for_address(address):
    if not address:
        return None
    wallet = Wallets.query.filter_by(
        pub_address=address, type="fee_deposit"
    ).first()
    return wallet.fda_key if wallet else None


def get_sweep_target(customer_address):
    if customer_address and Wallets.query.filter_by(
        pub_address=customer_address, type="fee_deposit"
    ).first():
        return customer_address

    row = Accounts.query.filter_by(address=customer_address).first()
    if row and row.sweep_target:
        return row.sweep_target
    if row and getattr(row, "fda_key", None):
        return get_fda_address(fda_key=row.fda_key)
    return get_fda_address()


def set_account_sweep_target(address, sweep_target, crypto, fda_key=None):
    row = Accounts.query.filter_by(address=address, crypto=crypto).first()
    resolved_key = fda_key or resolve_fda_key_for_address(sweep_target)
    if row:
        row.sweep_target = sweep_target
        if resolved_key:
            row.fda_key = resolved_key
    else:
        row = Accounts(
            address=address,
            crypto=crypto,
            amount=0,
            sweep_target=sweep_target,
            fda_key=resolved_key,
        )
        db.session.add(row)
    db.session.commit()
    return row


def request_json_field(*names):
    from flask import request

    data = request.get_json(silent=True) or {}
    for name in names:
        value = data.get(name)
        if value:
            return value
    return None


def preload_scope_lookups():
    accounts_by_address = {row.address: row for row in Accounts.query.all()}
    fda_wallets_by_address = {
        wallet.pub_address: wallet
        for wallet in Wallets.query.filter_by(type="fee_deposit").all()
    }
    return accounts_by_address, fda_wallets_by_address


def wallet_in_scope(
    wallet, fda_key=None, sweep_target=None, accounts_by_address=None
):
    if not fda_key and not sweep_target:
        return True
    normalized_key = _normalize_fda_key(fda_key) if fda_key else None
    if wallet.type == "fee_deposit":
        return bool(normalized_key and wallet.fda_key == normalized_key)

    if wallet.type == "regular" and (sweep_target or normalized_key):
        if accounts_by_address is not None:
            row = accounts_by_address.get(wallet.pub_address)
        else:
            row = Accounts.query.filter_by(address=wallet.pub_address).first()
        if sweep_target:
            return bool(row and row.sweep_target == sweep_target)
        return bool(row and row.fda_key == normalized_key)
    return False


def account_in_scope(
    account, fda_key=None, sweep_target=None, fda_wallets_by_address=None
):
    if not fda_key and not sweep_target:
        return True
    normalized_key = _normalize_fda_key(fda_key) if fda_key else None
    if account.type == "fee_deposit":
        if getattr(account, "fda_key", None):
            return bool(normalized_key and account.fda_key == normalized_key)
        if fda_wallets_by_address is not None:
            wallet = fda_wallets_by_address.get(account.address)
        else:
            wallet = Wallets.query.filter_by(
                pub_address=account.address, type="fee_deposit"
            ).first()
        return bool(wallet and normalized_key and wallet.fda_key == normalized_key)
    if sweep_target and account.sweep_target == sweep_target:
        return True
    if normalized_key and getattr(account, "fda_key", None) == normalized_key:
        return True
    return False
