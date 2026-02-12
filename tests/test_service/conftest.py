"""Shared fixtures for service tests."""

from __future__ import annotations

import base64
import time
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from nacl.signing import SigningKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.config import Settings, get_settings
from service.database import get_session
from service.models import Base, Client

# Use SQLite for tests (in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _test_settings() -> Settings:
    """Settings override for tests — uses temp paths and dummy URLs."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        redis_url="redis://localhost:6379",
        data_dir="/tmp/pdf2md_test_data",
        upload_dir="/tmp/pdf2md_test_data/uploads",
    )


@pytest.fixture()
def signing_key() -> SigningKey:
    """Generate an Ed25519 signing key for test authentication."""
    return SigningKey.generate()


@pytest.fixture()
def client_id() -> uuid.UUID:
    """Fixed UUID for the test client."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture()
async def db_engine():
    """Create an in-memory SQLite engine with all tables."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session bound to the test engine."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture()
async def test_client_record(
    db_session: AsyncSession,
    signing_key: SigningKey,
    client_id: uuid.UUID,
) -> Client:
    """Insert a test client into the database and return the ORM object."""
    public_b64 = base64.b64encode(bytes(signing_key.verify_key)).decode()
    client = Client(
        id=client_id,
        name="test-client",
        public_key_b64=public_b64,
        active=True,
    )
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    return client


@pytest_asyncio.fixture()
async def app_client(
    db_engine,
    test_client_record: Client,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the FastAPI app with test overrides."""
    from service.app import create_app

    app = create_app()

    # Override session dependency to use test engine
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = _test_settings

    # Mock arq pool on startup
    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)
    mock_pool.close = AsyncMock()
    app.state.arq_pool = mock_pool

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def sign_request(
    signing_key: SigningKey,
    method: str,
    path: str,
) -> dict[str, str]:
    """Build signed auth headers for a test request.

    Returns a dict with Authorization, X-Timestamp, X-Client-Id headers.
    """
    timestamp = str(int(time.time()))
    payload = f"{method}\n{path}\n{timestamp}".encode()
    signature = signing_key.sign(payload).signature
    sig_b64 = base64.b64encode(signature).decode()

    return {
        "Authorization": f"Signature {sig_b64}",
        "X-Timestamp": timestamp,
        "X-Client-Id": "00000000-0000-0000-0000-000000000001",
    }
