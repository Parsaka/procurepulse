"""Create an RSA key pair for a Snowflake service user (works on Windows, macOS, Linux).

    python scripts/make_keypair.py pp_ci

writes  keys/pp_ci.p8        private key (PKCS#8 PEM) -> GitHub secret SNOWFLAKE_PRIVATE_KEY
        keys/pp_ci.pub.txt   public key body, one line -> ALTER USER ... SET RSA_PUBLIC_KEY = '...'

The keys/ folder is git-ignored. Never commit or share the .p8 file.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]


def main(name: str) -> None:
    out = ROOT / "keys"
    out.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    body = "".join(line for line in public_pem.splitlines() if "-----" not in line)
    (out / f"{name}.p8").write_bytes(private_pem)
    (out / f"{name}.pub.txt").write_text(body + "\n")
    print(f"private key: {out / f'{name}.p8'}   (paste the whole file into the GitHub secret)")
    print(f"public key : {out / f'{name}.pub.txt'}")
    print(f"\nALTER USER {name.upper()} SET RSA_PUBLIC_KEY = '{body}';")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pp_ci")
