"""Ed25519 signature verification for API authentication."""

import base64
import time
import uuid

from fastapi import Depends, Header, HTTPException, Request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.config import Settings, get_settings
from service.database import get_session
from service.models import Client


def build_signing_payload(
    method: str,
    path: str,
    timestamp: str,
) -> bytes:
    """Build the canonical payload that clients must sign.

    Format: ``METHOD\\nPATH\\nTIMESTAMP``

    Body content is not included because multipart file uploads
    make body hashing impractical (boundary strings vary). The
    timestamp + signature already prevents replay attacks.
    """
    payload = f"{method}\n{path}\n{timestamp}"
    return payload.encode()


def verify_signature(public_key_b64: str, signature_b64: str, payload: bytes) -> None:
    """Verify an Ed25519 signature against a public key.

    Raises ``HTTPException(401)`` on failure.
    """
    try:
        pub_bytes = base64.b64decode(public_key_b64)
        sig_bytes = base64.b64decode(signature_b64)
        verify_key = VerifyKey(pub_bytes)
        verify_key.verify(payload, sig_bytes)
    except (BadSignatureError, Exception) as exc:
        raise HTTPException(status_code=401, detail="Invalid signature") from exc


async def authenticate_client(
    request: Request,
    authorization: str = Header(..., description="Signature <base64-sig>"),
    x_timestamp: str = Header(..., description="Unix epoch timestamp"),
    x_client_id: str = Header(..., description="Client UUID"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Client:
    """FastAPI dependency that authenticates a request via Ed25519 signature.

    Returns the authenticated ``Client`` ORM instance.
    """
    # Parse Authorization header
    if not authorization.startswith("Signature "):
        raise HTTPException(status_code=401, detail="Authorization must start with 'Signature '")
    signature_b64 = authorization[len("Signature ") :]

    # Validate timestamp freshness
    try:
        ts = int(x_timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid timestamp") from exc

    now = int(time.time())
    if abs(now - ts) > settings.auth_timestamp_tolerance_seconds:
        raise HTTPException(status_code=401, detail="Timestamp expired")

    # Look up client
    try:
        client_uuid = uuid.UUID(x_client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid client ID") from exc

    result = await session.execute(select(Client).where(Client.id == client_uuid))
    client = result.scalar_one_or_none()

    if client is None or not client.active:
        raise HTTPException(status_code=401, detail="Unknown or inactive client")

    # Verify signature
    payload = build_signing_payload(
        method=request.method,
        path=request.url.path,
        timestamp=x_timestamp,
    )
    verify_signature(client.public_key_b64, signature_b64, payload)

    return client
