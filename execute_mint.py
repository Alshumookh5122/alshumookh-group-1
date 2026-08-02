"""
ALSHUMOOKH — M1 Token Mint Executor
Run this script on Render Shell to execute the mint transaction on Ethereum Mainnet.
It reads ETH_PRIVATE_KEY and ALCHEMY_ETHEREUM_RPC_URL from environment variables.
"""

import os
import sys
from decimal import Decimal

def main():
    # ── Read config from environment ──
    rpc_url      = os.environ.get("ALCHEMY_ETHEREUM_RPC_URL") or os.environ.get("ALCHEMY_ETH_RPC_URL")
    private_key  = os.environ.get("ETH_PRIVATE_KEY")
    contract_addr = os.environ.get("M1_TOKEN_CONTRACT_ADDRESS", "0xa358cEca82cE32Cb19ee907DEc3f960896bC16c4")
    mint_to      = os.environ.get("TREASURY_WALLET", "0xBD682cfD8382a90adfDd6745780D3D7959c4d939")
    decimals     = int(os.environ.get("M1_TOKEN_DECIMALS", "18"))

    # ── Amount to mint ──
    MINT_AMOUNT = Decimal("26633164.50")

    # ── Validate ──
    if not rpc_url:
        print("ERROR: ALCHEMY_ETHEREUM_RPC_URL not set in environment")
        sys.exit(1)
    if not private_key:
        print("ERROR: ETH_PRIVATE_KEY not set in environment")
        sys.exit(1)

    try:
        from web3 import Web3
    except ImportError:
        print("Installing web3...")
        os.system("pip install web3 --break-system-packages -q")
        from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))

    if not w3.is_connected():
        print("ERROR: Cannot connect to Ethereum mainnet. Check RPC URL.")
        sys.exit(1)

    chain_id = w3.eth.chain_id
    print(f"Connected to chain ID: {chain_id}")
    if chain_id \!= 1:
        print(f"WARNING: Expected mainnet (1) but got chain {chain_id}")
        print("If this is Sepolia (11155111), set ENABLE_TESTNET=false on Render.com first")
        sys.exit(1)

    account = w3.eth.account.from_key(private_key)
    print(f"Wallet: {account.address}")

    eth_balance = w3.eth.get_balance(account.address)
    eth_value = w3.from_wei(eth_balance, "ether")
    print(f"ETH Balance: {eth_value:.6f} ETH")

    if eth_value < Decimal("0.001"):
        print("ERROR: Insufficient ETH for gas fees (need at least 0.001 ETH)")
        sys.exit(1)

    # ── M1 Token Contract ABI (minimal — mint function only) ──
    MINT_ABI = [
        {
            "inputs": [
                {"internalType": "address", "name": "to",     "type": "address"},
                {"internalType": "uint256", "name": "amount", "type": "uint256"}
            ],
            "name": "mint",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [],
            "name": "totalSupply",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_addr),
        abi=MINT_ABI
    )

    # Current supply
    try:
        supply = contract.functions.totalSupply().call()
        print(f"Current M1 totalSupply: {Decimal(supply) / (10**decimals):.2f} M1")
    except Exception as e:
        print(f"Could not read totalSupply: {e}")

    # ── Build transaction ──
    amount_wei = int(MINT_AMOUNT * (Decimal(10) ** decimals))
    nonce      = w3.eth.get_transaction_count(account.address)
    gas_price  = w3.eth.gas_price
    mint_to_checksum = Web3.to_checksum_address(mint_to)

    print(f"\nMinting: {MINT_AMOUNT} M1F")
    print(f"To:      {mint_to_checksum}")
    print(f"Contract:{contract_addr}")
    print(f"Gas Price: {w3.from_wei(gas_price, 'gwei'):.2f} Gwei")

    try:
        tx = contract.functions.mint(
            mint_to_checksum,
            amount_wei
        ).build_transaction({
            "from":     account.address,
            "nonce":    nonce,
            "gasPrice": gas_price,
            "gas":      250000,
            "chainId":  1
        })
    except Exception as e:
        print(f"\nERROR building transaction: {e}")
        print("Possible cause: wallet does not have MINTER_ROLE on the contract")
        sys.exit(1)

    # ── Sign and send ──
    signed   = account.sign_transaction(tx)
    tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
    tx_hex   = tx_hash.hex()

    print(f"\n{'='*60}")
    print(f"SUCCESS\! Transaction sent to mainnet.")
    print(f"TX Hash: {tx_hex}")
    print(f"View on Etherscan: https://etherscan.io/tx/{tx_hex}")
    print(f"{'='*60}")
    print(f"\nCopy this TX Hash and paste it into the Mint Confirmation form.")

    # ── Wait for receipt ──
    print("\nWaiting for confirmation (this may take 30-60 seconds)...")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            print(f"CONFIRMED in block: {receipt.blockNumber}")
            print(f"Block Number for form: {receipt.blockNumber}")
        else:
            print("Transaction REVERTED. The mint was rejected by the contract.")
            print("Check that the wallet has MINTER_ROLE.")
    except Exception as e:
        print(f"Timeout waiting for receipt: {e}")
        print(f"TX is still pending — check: https://etherscan.io/tx/{tx_hex}")

if __name__ == "__main__":
    main()
