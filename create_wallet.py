import requests
import base64
import uuid
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization

API_KEY = "LIVE_API_KEY:fbf589e2639c3699c223ae2ed0ea414a:7425a226464621ec66b9595509cef03c"
ENTITY_SECRET = "9887a28f81996be4768a2f3521671e802c469c96e2a8fd741804cb28adcd12b1"
BASE_URL = "https://api.circle.com/v1/w3s"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def get_ciphertext():
    r = requests.get(f"{BASE_URL}/config/entity/publicKey", headers=HEADERS)
    pub_key_pem = r.json()["data"]["publicKey"]
    public_key = serialization.load_pem_public_key(pub_key_pem.encode())
    ciphertext = public_key.encrypt(
        bytes.fromhex(ENTITY_SECRET),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return base64.b64encode(ciphertext).decode()

print("Step 1: Creating Wallet Set...")
r = requests.post(f"{BASE_URL}/developer/walletSets", headers=HEADERS, json={
    "idempotencyKey": str(uuid.uuid4()),
    "entitySecretCiphertext": get_ciphertext(),
    "name": "alshumookh-main"
})
print("Status:", r.status_code)
print("Response:", r.text)

if r.status_code not in [200, 201]:
    print("Error creating wallet set")
    exit(1)

wallet_set_id = r.json()["data"]["walletSet"]["id"]
print(f"\nWallet Set ID: {wallet_set_id}")

print("\nStep 2: Creating USDC Wallet on Ethereum...")
r2 = requests.post(f"{BASE_URL}/developer/wallets", headers=HEADERS, json={
    "idempotencyKey": str(uuid.uuid4()),
    "entitySecretCiphertext": get_ciphertext(),
    "blockchains": ["ETH"],
    "count": 1,
    "walletSetId": wallet_set_id
})
print("Status:", r2.status_code)
print("Response:", r2.text)

if r2.status_code in [200, 201]:
    wallets = r2.json()["data"]["wallets"]
    for w in wallets:
        print(f"\n=== Wallet Created ===")
        print(f"Wallet ID: {w['id']}")
        print(f"Address:   {w['address']}")
        print(f"Network:   {w['blockchain']}")
        print(f"State:     {w['state']}")
