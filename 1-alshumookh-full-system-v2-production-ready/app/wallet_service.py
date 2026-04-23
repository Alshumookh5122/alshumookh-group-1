from decimal import Decimal
from tronpy import Tron
from web3 import Web3

from app.alchemy_service import alchemy_rpc_url
from app.config import get_settings
from app.models import Network
from app.schemas import TreasuryBalanceResponse

settings = get_settings()


def evm_client() -> Web3:
    return Web3(Web3.HTTPProvider(alchemy_rpc_url()))


def tron_client() -> Tron:
    return Tron(provider={'api_key': settings.tron_api_key, 'conf': {'full_node': settings.tron_api_url}})


async def get_treasury_balance(network: Network) -> TreasuryBalanceResponse:
    if network == Network.ETHEREUM:
        client = evm_client()
        wei = client.eth.get_balance(settings.eth_treasury_address)
        native = str(Web3.from_wei(wei, 'ether'))
        return TreasuryBalanceResponse(
            network=network,
            address=settings.eth_treasury_address,
            native_balance=native,
            token_symbol='USDT',
            token_balance='not_implemented'
        )

    client = tron_client()
    account = client.get_account(settings.tron_treasury_address)
    trx_sun = account.get('balance', 0)
    trx = Decimal(trx_sun) / Decimal(1_000_000)
    return TreasuryBalanceResponse(
        network=network,
        address=settings.tron_treasury_address,
        native_balance=str(trx),
        token_symbol='USDT',
        token_balance='not_implemented'
    )
