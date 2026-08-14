from sqlalchemy.exc import IntegrityError

from ..encryption import Encryption
from ..logging import logger
from ..models import Accounts, Wallets, db

DEFAULT_STORE_ID = 1


def parse_store_id(value):
    if value is None:
        return DEFAULT_STORE_ID
    if isinstance(value, bool):
        raise ValueError(f"Invalid store_id {value!r}")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"Invalid store_id {value!r}")
        return value
    raw = str(value).strip()
    if not raw or raw.lower() in ("default", "none", "null"):
        return DEFAULT_STORE_ID
    try:
        store_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid store_id {value!r}") from exc
    if store_id <= 0:
        raise ValueError(f"Invalid store_id {value!r}")
    return store_id


def _store_wallet_query(store_id):
    store_id = parse_store_id(store_id)
    return (
        Wallets.query.filter_by(type="fee_deposit", store_id=store_id)
        .order_by(Wallets.id.asc())
    )


def get_fda_address(store_id=None, account=None):
    if account:
        # A concrete FDA address identifies the store. Do not coerce a missing
        # store_id to 1 — that rejects merchant FDAs during payout/balance.
        resolve_account_store_id(store_id=store_id, fee_deposit_account=account)
        return account

    store_id = parse_store_id(store_id)
    wallet = _store_wallet_query(store_id).first()
    if wallet:
        return wallet.pub_address

    raise ValueError(f"Fee-deposit account not found for store_id={store_id!r}")


def create_fda(store_id=None):
    """Create or return existing fee-deposit wallet for store_id (idempotent)."""
    store_id = parse_store_id(store_id)
    existing = _store_wallet_query(store_id).first()
    if existing:
        return existing.pub_address

    from ..config import config
    from ..token import make_provider

    provider = make_provider()
    acc = provider.eth.account.create()
    crypto_str = config["COIN_SYMBOL"]
    e = Encryption

    logger.warning(
        "Creating fee-deposit account for store_id=%s: %s", store_id, acc.address
    )
    try:
        db.session.add(
            Wallets(
                pub_address=acc.address,
                priv_key=e.encrypt(acc.key.hex()),
                type="fee_deposit",
                store_id=store_id,
            )
        )
        db.session.add(
            Accounts(
                address=acc.address,
                crypto=crypto_str,
                amount=0,
                type="fee_deposit",
                store_id=store_id,
            )
        )
        db.session.commit()
    except IntegrityError:
        # Concurrent create for the same store_id — keep the winner.
        db.session.rollback()
        existing = _store_wallet_query(store_id).first()
        if existing:
            logger.warning(
                "Concurrent FDA create for store_id=%s; reusing %s",
                store_id,
                existing.pub_address,
            )
            return existing.pub_address
        raise

    logger.info(
        "Created fee-deposit account %s for store_id=%s", acc.address, store_id
    )
    return acc.address


def resolve_account_store_id(store_id=None, fee_deposit_account=None):
    """Resolve store_id from request and/or a known fee-deposit address."""
    requested = parse_store_id(store_id) if store_id is not None else None
    if fee_deposit_account:
        wallet = Wallets.query.filter_by(
            pub_address=fee_deposit_account, type="fee_deposit"
        ).first()
        if not wallet:
            raise ValueError(
                f"fee_deposit_account {fee_deposit_account!r} is not a known fee-deposit wallet"
            )
        wallet_store_id = parse_store_id(wallet.store_id)
        if store_id is not None and str(store_id).strip() != "":
            if requested != wallet_store_id:
                raise ValueError(
                    f"store_id {requested!r} does not match fee_deposit_account "
                    f"{fee_deposit_account!r} (expected {wallet_store_id!r})"
                )
            return requested
        return wallet_store_id
    return requested if requested is not None else DEFAULT_STORE_ID


def get_drain_destination(customer_address):
    """Resolve where to sweep funds from a customer/invoice address (via store_id)."""
    if customer_address and Wallets.query.filter_by(
        pub_address=customer_address, type="fee_deposit"
    ).first():
        return customer_address

    row = Accounts.query.filter_by(address=customer_address).first()
    if row is not None:
        return get_fda_address(store_id=row.store_id)
    return get_fda_address(store_id=DEFAULT_STORE_ID)


def request_json_field(*names):
    from flask import request

    data = request.get_json(silent=True) or {}
    for name in names:
        if name not in data:
            continue
        value = data.get(name)
        if value is None or value == "":
            continue
        return value
    return None


def preload_accounts_by_address():
    return {row.address: row for row in Accounts.query.all()}


def _same_store(left, right):
    return parse_store_id(left) == parse_store_id(right)


def wallet_in_scope(wallet, store_id=None, accounts_by_address=None, scoped=False):
    if not scoped:
        return True
    target = parse_store_id(store_id)
    if wallet.type == "fee_deposit":
        return _same_store(wallet.store_id, target)

    if wallet.type == "regular":
        if accounts_by_address is not None:
            row = accounts_by_address.get(wallet.pub_address)
        else:
            row = Accounts.query.filter_by(address=wallet.pub_address).first()
        return bool(row and _same_store(row.store_id, target))
    return False


def account_in_scope(account, store_id=None, scoped=False):
    if not scoped:
        return True
    return _same_store(getattr(account, "store_id", None), store_id)
