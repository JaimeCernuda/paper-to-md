"""Generate an Ed25519 keypair for API client authentication.

Usage:
    uv run python scripts/generate_keypair.py

Outputs the private key (keep secret, give to client) and
the base64-encoded public key (register in the clients table).
"""

import base64

from nacl.signing import SigningKey


def main() -> None:
    """Generate and print an Ed25519 keypair."""
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key

    private_b64 = base64.b64encode(bytes(signing_key)).decode()
    public_b64 = base64.b64encode(bytes(verify_key)).decode()

    print("=== Ed25519 Keypair ===")  # noqa: T201
    print()  # noqa: T201
    print(f"Private key (client keeps this secret):\n  {private_b64}")  # noqa: T201
    print()  # noqa: T201
    print(f"Public key (register in DB clients table):\n  {public_b64}")  # noqa: T201
    print()  # noqa: T201
    print("-- SQL to register client --")  # noqa: T201
    print(  # noqa: T201
        f"INSERT INTO clients (id, name, public_key_b64, active) VALUES "
        f"(gen_random_uuid(), 'my-client', '{public_b64}', true);"
    )


if __name__ == "__main__":
    main()
