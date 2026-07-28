from flask import g
from web3 import Web3

from ..config import config
from ..models import Accounts, Settings, Wallets, db
from ..encryption import Encryption
from ..token import Token, Coin, get_all_accounts, make_provider
from ..logging import logger
from ..services.transaction_lookup import TransactionLookupService
from ..services import fda as fda_service
from . import api
from app import create_app

w3 = make_provider()

w3l = Web3()

app = create_app()
app.app_context().push()


def _payout_source():
    return fda_service.request_json_field("from_account", "account") or None


def _fda_key():
    return fda_service.request_json_field("fda_key") or None


@api.post("/generate-address")
def generate_new_address():
    sweep_target = fda_service.request_json_field(
        "fee_deposit_account", "sweep_target"
    )
    fda_key = _fda_key()
    if not sweep_target:
        # Optional for backward compatibility: fall back to default / requested FDA.
        try:
            sweep_target = fda_service.get_fda_address(fda_key=fda_key)
        except Exception as exc:
            return {
                "status": "error",
                "msg": f"fee_deposit_account (sweep_target) is required: {exc}",
            }, 400
    else:
        fda_key = fda_key or fda_service.resolve_fda_key_for_address(sweep_target)

    acc = w3l.eth.account.create()
    crypto_str = str(g.symbol)
    e = Encryption
    logger.warning(f"Saving wallet {acc.address} to DB")
    try:
        with app.app_context():
            db.session.add(
                Wallets(
                    pub_address=acc.address,
                    priv_key=e.encrypt(acc.key.hex()),
                    type="regular",
                )
            )
            db.session.add(
                Accounts(
                    address=acc.address,
                    crypto=crypto_str,
                    amount=0,
                    sweep_target=sweep_target,
                    fda_key=fda_key,
                )
            )
            db.session.commit()
            db.session.close()
            db.engine.dispose()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    logger.info("Added new address and wallet added to DB")
    return {"status": "success", "address": acc.address}


@api.post("/create-fee-deposit-account")
def create_fee_deposit_account():
    fda_key = fda_service.request_json_field("fda_key")
    address = fda_service.create_fda(fda_key)
    return {"status": "success", "account": address, "fda_key": fda_key or fda_service.DEFAULT_FDA_KEY}


@api.post("/balance")
def get_balance():
    crypto_str = str(g.symbol)
    from_account = _payout_source()
    fda_key = _fda_key()
    try:
        if crypto_str == config["COIN_SYMBOL"]:
            inst = Coin(config["COIN_SYMBOL"])
            balance = inst.get_fee_deposit_coin_balance(
                account=from_account, fda_key=fda_key
            )
        else:
            if crypto_str in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
                token_instance = Token(crypto_str)
                balance = token_instance.get_fee_deposit_token_balance(
                    account=from_account, fda_key=fda_key
                )
            else:
                return {"status": "error", "msg": "token is not defined in config"}
    except ValueError as exc:
        logger.warning("Balance request failed for %s: %s", crypto_str, exc)
        return {"status": "error", "msg": str(exc)}
    return {"status": "success", "balance": balance}


@api.post("/status")
def get_status():
    with app.app_context():
        pd = Settings.query.filter_by(name="last_block").first()

    last_checked_block_number = int(pd.value)
    block = w3.eth.get_block(w3.to_hex(last_checked_block_number))
    return {"status": "success", "last_block_timestamp": block["timestamp"]}


@api.post("/transaction/<txid>")
def get_transaction(txid):
    result = TransactionLookupService(w3).lookup(g.symbol, txid)
    logger.warning(result)
    return result


@api.post("/dump")
def dump():
    fda_key = _fda_key()
    sweep_target = fda_service.request_json_field("sweep_target")
    w = Coin(config["COIN_SYMBOL"])
    all_wallets = w.get_dump(fda_key=fda_key, sweep_target=sweep_target)
    return all_wallets


@api.post("/fee-deposit-account")
def get_fee_deposit_account():
    from_account = _payout_source()
    fda_key = _fda_key()
    if g.symbol == config["COIN_SYMBOL"]:
        coin_instance = Coin(g.symbol)
        account = coin_instance.get_fee_deposit_account(
            fda_key=fda_key, account=from_account
        )
        return {
            "account": account,
            "balance": coin_instance.get_fee_deposit_coin_balance(
                account=account, fda_key=fda_key
            ),
        }
    elif g.symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
        token_instance = Token(g.symbol)
        account = token_instance.get_fee_deposit_account(
            fda_key=fda_key, account=from_account
        )
        return {
            "account": account,
            "balance": token_instance.get_fee_deposit_account_balance(
                account=account, fda_key=fda_key
            ),
        }
    else:
        raise Exception(f"Symbol {g.symbol} cannot be processed")


@api.post("/get_all_addresses")
def get_all_addresses():
    fda_key = _fda_key()
    sweep_target = fda_service.request_json_field("sweep_target")
    all_addresses_list = get_all_accounts(
        fda_key=fda_key, sweep_target=sweep_target
    )
    return all_addresses_list
