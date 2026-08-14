from app.services.fda import (
    account_in_scope,
    parse_store_id,
    wallet_in_scope,
)


class _Wallet:
    def __init__(self, pub_address, wallet_type, store_id=None):
        self.pub_address = pub_address
        self.type = wallet_type
        self.store_id = store_id


class _Account:
    def __init__(self, address, account_type="regular", store_id=None):
        self.address = address
        self.type = account_type
        self.store_id = store_id


def test_parse_store_id():
    assert parse_store_id(None) == 1
    assert parse_store_id("default") == 1
    assert parse_store_id(2) == 2
    assert parse_store_id("7") == 7


def test_wallet_in_scope_without_filters():
    wallet = _Wallet("0xabc", "regular")
    assert wallet_in_scope(wallet) is True


def test_wallet_in_scope_fee_deposit_by_store_id():
    wallet = _Wallet("0xfda", "fee_deposit", store_id=2)
    assert wallet_in_scope(wallet, store_id=2, scoped=True) is True
    assert wallet_in_scope(wallet, store_id=3, scoped=True) is False


def test_account_in_scope_by_store_id():
    account = _Account("0xinv", store_id=2)
    assert account_in_scope(account, store_id=2, scoped=True) is True
    assert account_in_scope(account, store_id=3, scoped=True) is False


def test_fee_deposit_account_in_scope_by_store_id():
    account = _Account("0xfda", account_type="fee_deposit", store_id=2)
    assert account_in_scope(account, store_id=2, scoped=True) is True
    assert account_in_scope(account, store_id=9, scoped=True) is False


def test_default_store_is_one():
    wallet = _Wallet("0xfda", "fee_deposit", store_id=1)
    assert wallet_in_scope(wallet, store_id=None, scoped=True) is True
    assert wallet_in_scope(wallet, store_id=1, scoped=True) is True
    assert wallet_in_scope(wallet, store_id=2, scoped=True) is False


def test_get_drain_destination_keeps_fee_deposit_as_itself():
    from unittest.mock import MagicMock, patch

    from app.services.fda import get_drain_destination

    fda = "0xStoreFda"
    with patch("app.services.fda.Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = MagicMock()
        assert get_drain_destination(fda) == fda
        wallets.query.filter_by.assert_called_with(
            pub_address=fda, type="fee_deposit"
        )


def test_create_fda_returns_existing_without_recreate():
    from unittest.mock import MagicMock, patch

    from app.services.fda import create_fda

    existing = MagicMock()
    existing.pub_address = "0xCanonicalFda"

    with patch("app.services.fda._store_wallet_query") as query:
        query.return_value.first.return_value = existing
        assert create_fda(7) == "0xCanonicalFda"


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

    with patch.object(fda_mod, "_store_wallet_query") as query, patch(
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
        assert fda_mod.create_fda(7) == "0xWinnerFda"
        rollback.assert_called()


def test_get_fda_address_does_not_create_by_default():
    from unittest.mock import patch

    from app.services import fda as fda_mod

    with patch.object(fda_mod, "_store_wallet_query") as query, patch.object(
        fda_mod, "create_fda"
    ) as create:
        query.return_value.first.return_value = None
        try:
            fda_mod.get_fda_address(store_id=2)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "not found" in str(exc)
        create.assert_not_called()


def test_get_fda_address_rejects_non_fda_from_account():
    from unittest.mock import MagicMock, patch

    from app.services import fda as fda_mod

    wallet = MagicMock()
    wallet.type = "regular"
    wallet.store_id = 1

    with patch.object(fda_mod, "Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = None
        try:
            fda_mod.get_fda_address(store_id=1, account="0xRegular")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "fee-deposit" in str(exc)


def test_get_fda_address_infers_store_from_account_when_store_id_omitted():
    from unittest.mock import MagicMock, patch

    from app.services import fda as fda_mod

    wallet = MagicMock()
    wallet.store_id = 3

    with patch.object(fda_mod, "Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = wallet
        assert fda_mod.get_fda_address(account="0xMerchantFda") == "0xMerchantFda"


def test_resolve_account_store_id_infers_from_fda_when_store_id_missing():
    from unittest.mock import MagicMock, patch

    from app.services import fda as fda_mod

    wallet = MagicMock()
    wallet.store_id = 3

    with patch.object(fda_mod, "Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = wallet
        assert (
            fda_mod.resolve_account_store_id(fee_deposit_account="0xMerchantFda") == 3
        )


def test_get_fda_address_rejects_cross_store_from_account():
    from unittest.mock import MagicMock, patch

    from app.services import fda as fda_mod

    wallet = MagicMock()
    wallet.store_id = 2

    with patch.object(fda_mod, "Wallets") as wallets:
        wallets.query.filter_by.return_value.first.return_value = wallet
        try:
            fda_mod.get_fda_address(store_id=1, account="0xOtherStoreFda")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "store_id" in str(exc)
