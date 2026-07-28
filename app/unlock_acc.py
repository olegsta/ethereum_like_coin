import time

import requests as rq

from .logging import logger
from .config import config

acc_password = False


def _fetch_password_from_shkeeper():
    resp = rq.get(
        f'http://{config["SHKEEPER_HOST"]}/api/v1/{config["COIN_SYMBOL"]}/decrypt',
        headers={"X-Shkeeper-Backend-Key": config["SHKEEPER_KEY"]},
        timeout=10,
    )
    r = resp.json()
    if r.get("persistent_status") == "disabled":
        logger.warning("Encryption is disabled")
        return r.get("key")
    if r.get("persistent_status") == "pending":
        logger.warning("Have not selected encryption mode yet")
        return False
    if r.get("persistent_status") == "enabled":
        runtime_status = r.get("runtime_status")
        if runtime_status == "pending":
            logger.warning("Encryption enabled, but password is not entered yet")
            return False
        if runtime_status == "fail":
            logger.warning("Encryption enabled, but entered password is not correct")
            return False
        if runtime_status == "success":
            return r.get("key")
        logger.warning(f"Receive unexpected response from shkeeper: {resp.text}")
        return False
    logger.warning(f"Receive unexpected response from shkeeper: {resp.text}")
    return False


def get_account_password():
    global acc_password
    if acc_password:
        logger.warning("Get password from cache")
        return acc_password

    logger.warning("Get password from shkeeper")
    wait_seconds = int(config.get("SHKEEPER_UNLOCK_WAIT", 120))
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        password = _fetch_password_from_shkeeper()
        if password:
            acc_password = password
            return acc_password
        time.sleep(1)

    return False
