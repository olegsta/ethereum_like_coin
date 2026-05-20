import os
from unittest.mock import MagicMock, patch

import pytest

# Required before importing app.config (COIN is resolved at import time).
os.environ.setdefault('WALLET', 'ETH')

# Load config module before app package shadows it with the config dict.
import app.config  # noqa: F401, E402

# views.py calls create_app() at import time; avoid real DB/Web3 during tests.
_mock_flask_app = MagicMock()
patch('app.create_app', return_value=_mock_flask_app).start()
patch('app.api.views.create_app', return_value=_mock_flask_app).start()
patch('app.api.views.Web3', return_value=MagicMock()).start()
patch('app.tasks.Web3', return_value=MagicMock()).start()

import app  # noqa: F401, E402


@pytest.fixture(autouse=True)
def reset_encryption_key():
    from app.encryption import Encryption

    Encryption.key = None
    yield
    Encryption.key = None


@pytest.fixture(autouse=True)
def reset_unlock_acc_cache():
    import app.unlock_acc as unlock_acc

    unlock_acc.acc_password = False
    yield
    unlock_acc.acc_password = False


@pytest.fixture
def ethereum_chain():
    from app.chains import CHAINS

    return CHAINS['ETH']


@pytest.fixture
def arbitrum_chain():
    from app.chains import CHAINS

    return CHAINS['ARBETH']
