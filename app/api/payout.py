from decimal import Decimal

from flask import g, request

from .. import celery
from ..tasks import make_multipayout
from . import api
from ..services import fda as fda_service

from ..token import Token, Coin, make_provider
from ..config import config


def _start_multipayout(payout_list, store_id):
    tokens = config["TOKENS"][config["CURRENT_NETWORK"]]
    if g.symbol != config["COIN_SYMBOL"] and g.symbol not in tokens:
        raise Exception(f"{g.symbol} is not defined in config, cannot make payout")
    coin_inst = Coin(config["COIN_SYMBOL"])
    coin_inst.get_fee_deposit_account(store_id=store_id)
    max_fee = coin_inst.get_max_priority_fee()
    task = make_multipayout.s(
        g.symbol, payout_list, max_fee, store_id
    ).apply_async()
    return {"task_id": task.id}


@api.post("/calc-tx-fee/<decimal:amount>")
def calc_tx_fee(amount):
    data = request.get_json(silent=True) or {}
    try:
        store_id = fda_service.parse_store_id(data.get("store_id"))
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400

    if g.symbol == config["COIN_SYMBOL"]:
        coin_inst = Coin(config["COIN_SYMBOL"])
        fee = coin_inst.get_transaction_price(store_id=store_id)
        return {"accounts_num": 1, "fee": float(fee)}

    elif g.symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
        token_instance = Token(g.symbol)
        need_crypto = token_instance.get_coin_transaction_fee(store_id=store_id)
        return {
            "accounts_num": 1,
            "fee": float(need_crypto),
        }
    else:
        return {"status": "error", "msg": "unknown crypto"}


@api.post("/multipayout")
def multipayout():
    w3 = make_provider()

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        raise Exception(f"Bad JSON in payout list: {e}")

    if isinstance(payload, dict):
        payout_list = payload.get("payouts") or payload.get("payout_list") or []
    else:
        payout_list = payload

    if not payout_list:
        raise Exception("Payout list is empty!")

    for transfer in payout_list:
        try:
            is_address = w3.is_address(transfer["dest"])
        except Exception as e:
            raise Exception(f"Bad destination address in {transfer}: {e}")
        if not is_address:
            raise Exception(f"Bad destination address in {transfer}")
        try:
            transfer["amount"] = Decimal(transfer["amount"])
        except Exception as e:
            raise Exception(f"Bad amount in {transfer}: {e}")

        if transfer["amount"] <= 0:
            raise Exception(f"Payout amount should be a positive number: {transfer}")

    try:
        store_id = fda_service.parse_store_id(
            payload.get("store_id") if isinstance(payload, dict) else None
        )
        return _start_multipayout(payout_list, store_id)
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400


@api.post("/payout/<to>/<decimal:amount>")
def payout(to, amount):
    data = request.get_json(silent=True) or {}
    try:
        return _start_multipayout(
            [{"dest": to, "amount": amount}],
            fda_service.parse_store_id(data.get("store_id")),
        )
    except ValueError as exc:
        return {"status": "error", "msg": str(exc)}, 400


@api.post("/task/<id>")
def get_task(id):
    task = celery.AsyncResult(id)
    if isinstance(task.result, Exception):
        return {"status": task.status, "result": str(task.result)}
    return {"status": task.status, "result": task.result}
