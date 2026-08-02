import requests
import base64
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization

API_KEY = "LIVE_API_KEY:fbf589e2639c3699c223ae2ed0ea414a:7425a226464621ec66b9595509cef03c"
ENTITY_SECRET = "9887a28f81996be4768a2f3521671e802c469c96e2a8fd741804cb28adcd12b1"

print("Fetching Circle public key...")
r = requests.get(
    "https://api.circle.com/v1/w3s/config/entity/publicKey",
    headers={"Authorization": f"Bearer {API_KEY}"}
)

if r.status_code != 200:
    print("Error:", r.status_code, r.text)
    exit(1)

pub_key_pem = r.json()["data"]["publicKey"]
public_key = serialization.load_pem_public_key(pub_key_pem.encode())

ciphertext = public_key.encrypt(
    bytes.fromhex(ENTITY_SECRET),
    padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None
    )
)

result = base64.b64encode(ciphertext).decode()
print("\n=== Ciphertext (انسخ هذا ===")
print(result)
print("\n=== انتهى ===")
