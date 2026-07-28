from app.services.fda import account_in_scope, wallet_in_scope


class _Wallet:
    def __init__(self, pub_address, wallet_type, fda_key=None):
        self.pub_address = pub_address
        self.type = wallet_type
        self.fda_key = fda_key


class _Account:
    def __init__(
        self, address, account_type="regular", sweep_target=None, fda_key=None
    ):
        self.address = address
        self.type = account_type
        self.sweep_target = sweep_target
        self.fda_key = fda_key


def test_wallet_in_scope_without_filters():
    wallet = _Wallet("0xabc", "regular")
    assert wallet_in_scope(wallet) is True


def test_wallet_in_scope_fee_deposit_by_fda_key():
    wallet = _Wallet("0xfda", "fee_deposit", fda_key="store-2-ETH")
    assert wallet_in_scope(wallet, fda_key="store-2-ETH") is True
    assert wallet_in_scope(wallet, fda_key="store-3-ETH") is False


def test_account_in_scope_by_sweep_target():
    account = _Account("0xinv", sweep_target="0xfda")
    assert account_in_scope(account, sweep_target="0xfda") is True
    assert account_in_scope(account, sweep_target="0xother") is False


def test_account_in_scope_by_fda_key():
    account = _Account("0xinv", sweep_target="0xfda", fda_key="store-2-ETH")
    assert account_in_scope(account, fda_key="store-2-ETH") is True
    assert account_in_scope(account, fda_key="store-3-ETH") is False


def test_fee_deposit_account_in_scope_by_fda_key():
    account = _Account(
        "0xfda", account_type="fee_deposit", fda_key="store-2-ETH"
    )
    assert account_in_scope(account, fda_key="store-2-ETH") is True
    assert account_in_scope(account, fda_key="store-9-ETH") is False


def test_get_sweep_target_keeps_fee_deposit_as_itself():
    from unittest.mock import MagicMock, patch

    from app.services.fda import get_sweep_target

    fda = "0xStoreFda"
    with patch("app.services.fda.Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = MagicMock()
        assert get_sweep_target(fda) == fda
        wallets.query.filter_by.assert_called_with(
            pub_address=fda, type="fee_deposit"
        )


def test_create_fda_returns_existing_without_recreate():
    from unittest.mock import MagicMock, patch

    from app.services.fda import create_fda

    existing = MagicMock()
    existing.pub_address = "0xCanonicalFda"

    with patch("app.services.fda._fda_wallet_query") as query:
        query.return_value.first.return_value = existing
        assert create_fda("store-7-ETH") == "0xCanonicalFda"


def test_create_fda_integrity_error_reuses_winner():
    from unittest.mock import MagicMock, patch

    from sqlalchemy.exc import IntegrityError

    from app.services import fda as fda_mod

    winner = MagicMock()
    winner.pub_address = "0xWinnerFda"

    provider = MagicMock()
    account = MagicMock()
    account.address = "0xRaceLoser"
    account.key.hex.return_value = "00" * 32
    provider.eth.account.create.return_value = account

    with patch.object(fda_mod, "_fda_wallet_query") as query, patch(
        "app.token.make_provider", return_value=provider
    ), patch(
        "app.config.config",
        {"COIN_SYMBOL": "ETH"},
    ), patch.object(fda_mod, "Encryption") as enc, patch.object(
        fda_mod.db.session, "add"
    ), patch.object(
        fda_mod.db.session, "commit", side_effect=IntegrityError("stmt", {}, Exception())
    ), patch.object(
        fda_mod.db.session, "rollback"
    ) as rollback:
        enc.encrypt.return_value = "enc"
        query.return_value.first.side_effect = [None, winner]
        assert fda_mod.create_fda("store-7-ETH") == "0xWinnerFda"
        rollback.assert_called()
