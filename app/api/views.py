from flask import g, request
from web3 import Web3

from ..config import config
from ..models import Accounts, Settings, Wallets, db
from ..encryption import Encryption
from ..token import Token, Coin, get_all_accounts, make_provider
from ..logging import logger
from ..services.transaction_lookup import TransactionLookupService
from ..services import fda as fda_service
from . import api

w3 = make_provider()

w3l = Web3()


def _json():
    return request.get_json(silent=True) or {}


def _request_store_id(*, required=False):
    return fda_service.parse_store_id(_json().get("store_id"), required=required)


@api.post("/generate-address")
def generate_new_address():
    try:
        # Missing store_id → store 1
        store_id = _request_store_id()
        fda_service.get_fda_address(store_id=store_id)
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400

    acc = w3l.eth.account.create()
    crypto_str = str(g.symbol)
    e = Encryption
    logger.warning(f"Saving wallet {acc.address} to DB")
    try:
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
                store_id=store_id,
            )
        )
        db.session.commit()
    finally:
        db.session.remove()

    logger.info("Added new address and wallet added to DB")
    return {"status": "success", "address": acc.address}


@api.post("/create-fee-deposit-account")
def create_fee_deposit_account():
    data = _json()
    if "store_id" not in data:
        return {
            "status": "error",
            "msg": "store_id is required to create a fee-deposit account",
        }, 400
    try:
        store_id = fda_service.parse_store_id(data.get("store_id"), required=True)
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400
    address = fda_service.create_fda(store_id)
    return {
        "status": "success",
        "account": address,
        "store_id": store_id,
    }


@api.post("/balance")
def get_balance():
    crypto_str = str(g.symbol)
    try:
        store_id = _request_store_id()
        if crypto_str == config["COIN_SYMBOL"]:
            inst = Coin(config["COIN_SYMBOL"])
            balance = inst.get_fee_deposit_coin_balance(store_id=store_id)
        else:
            if crypto_str in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
                token_instance = Token(crypto_str)
                balance = token_instance.get_fee_deposit_token_balance(
                    store_id=store_id
                )
            else:
                return {"status": "error", "msg": "token is not defined in config"}
    except ValueError as exc:
        logger.warning("Balance request failed for %s: %s", crypto_str, exc)
        return {"status": "error", "msg": str(exc)}
    return {"status": "success", "balance": balance}


@api.post("/status")
def get_status():
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
    store_id = _request_store_id()
    w = Coin(config["COIN_SYMBOL"])
    return w.get_dump(store_id=store_id, scoped=True)


@api.post("/fee-deposit-account")
def get_fee_deposit_account():
    try:
        store_id = _request_store_id()
        if g.symbol == config["COIN_SYMBOL"]:
            coin_instance = Coin(g.symbol)
            account = coin_instance.get_fee_deposit_account(store_id=store_id)
            return {
                "account": account,
                "balance": coin_instance.get_fee_deposit_coin_balance(
                    store_id=store_id
                ),
            }
        elif g.symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
            token_instance = Token(g.symbol)
            account = token_instance.get_fee_deposit_account(store_id=store_id)
            return {
                "account": account,
                "balance": token_instance.get_fee_deposit_account_balance(
                    store_id=store_id
                ),
            }
        else:
            raise Exception(f"Symbol {g.symbol} cannot be processed")
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400


@api.post("/get_all_addresses")
def get_all_addresses():
    store_id = _request_store_id()
    return get_all_accounts(store_id=store_id, scoped=True)
