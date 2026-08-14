from sqlalchemy.exc import IntegrityError

from ..encryption import Encryption
from ..logging import logger
from ..models import Accounts, Wallets, db

DEFAULT_STORE_ID = 1


def parse_store_id(value, required=False):
    if value is None:
        if required:
            raise ValueError("store_id is required")
        return DEFAULT_STORE_ID
    if isinstance(value, bool):
        raise ValueError(f"Invalid store_id {value!r}")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"Invalid store_id {value!r}")
        return value
    raw = str(value).strip()
    if not raw:
        if required:
            raise ValueError("store_id is required")
        return DEFAULT_STORE_ID
    if raw.lower() == "default":
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


def get_fda_address(store_id=None):
    store_id = parse_store_id(store_id)
    wallet = _store_wallet_query(store_id).first()
    if wallet:
        return wallet.pub_address

    # Same as the old celery create_fee_deposit_account + set_fee_deposit_account:
    # first balance/status/address request creates the store FDA if missing.
    return create_fda(store_id)


def create_fda(store_id=None):
    """Create or return existing fee-deposit wallet for store_id (idempotent)."""
    store_id = parse_store_id(store_id, required=True)
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


def get_drain_destination(customer_address):
    """Resolve where to sweep funds from a customer/invoice address (via store_id)."""
    if customer_address and Wallets.query.filter_by(
        pub_address=customer_address, type="fee_deposit"
    ).first():
        return customer_address

    row = Accounts.query.filter_by(address=customer_address).first()
    if row is None:
        raise ValueError(
            f"Cannot resolve drain destination for {customer_address!r}: "
            "account not found"
        )
    if row.store_id is None:
        raise ValueError(
            f"Cannot resolve drain destination for {customer_address!r}: "
            "store_id is missing"
        )
    return get_fda_address(store_id=row.store_id)


def preload_accounts_by_address(store_id=None):
    query = Accounts.query
    if store_id is not None:
        query = query.filter_by(store_id=parse_store_id(store_id))
    return {row.address: row for row in query.all()}


def _row_store_id(value):
    """store_id on a DB row. None is unscoped, not store 1."""
    if value is None:
        return None
    return parse_store_id(value)


def _same_store(row_store_id, target_store_id):
    row_sid = _row_store_id(row_store_id)
    if row_sid is None:
        return False
    return row_sid == parse_store_id(target_store_id)


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
