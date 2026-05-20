from app.chains import CHAINS, SUPPORTED_COINS, WALLET_ALIASES
from app.chains import arbitrum, ethereum


def test_supported_coins():
    assert SUPPORTED_COINS == ('ETH', 'ARBETH')


def test_wallet_alias_maps_arb_to_arbeth():
    assert WALLET_ALIASES['ARB'] == 'ARBETH'


def test_chains_registry_has_required_fields():
    for coin, module in CHAINS.items():
        assert module.COIN == coin
        assert module.DB_NAME
        assert module.FULLNODE_URL
        assert module.ENV['network']
        assert module.DEFAULTS
        assert 'main' in module.TOKENS or 'sepolia' in module.TOKENS


def test_ethereum_chain_defaults():
    assert ethereum.COIN == 'ETH'
    assert ethereum.DB_NAME == 'ethereum-shkeeper'
    assert ethereum.FULLNODE_URL == 'http://ethereum:8545'
    assert ethereum.DEFAULTS['ENABLE_INTERNAL_TX_SCAN'] is True


def test_arbitrum_chain_defaults():
    assert arbitrum.COIN == 'ARBETH'
    assert arbitrum.DB_NAME == 'arbitrum-shkeeper'
    assert arbitrum.DEFAULTS['ENABLE_INTERNAL_TX_SCAN'] is False


def test_ethereum_sepolia_has_usdt_token():
    assert 'ETH-USDT' in ethereum.TOKENS['sepolia']


def test_arbitrum_sepolia_has_usdc_token():
    assert 'ARB-USDC' in arbitrum.TOKENS['sepolia']
