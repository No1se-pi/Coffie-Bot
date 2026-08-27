"""PostgreSQL coverage for receipt idempotency, history, and risk flags."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.content import Venue
from app.models.enums import MediaStatus, PermissionCode, ReceiptSource, Role, UserStatus
from app.models.media import MediaFile
from app.models.receipts import Receipt, ReceiptRevision, ReceiptRiskFlag
from app.repositories.receipts import ReceiptRepository
from app.security.rbac import Actor
from app.services.receipts import (
    ReceiptCreateCommand,
    ReceiptEditCommand,
    ReceiptService,
)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _actor(user_id: UUID, staff_id: UUID) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=staff_id,
        permissions=frozenset({PermissionCode.RECEIPTS_READ, PermissionCode.RECEIPTS_MANAGE}),
    )


@pytest.mark.asyncio
async def test_receipt_create_and_edit_are_idempotent_and_append_only() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    customer_id, staff_user_id, staff_id, venue_id, media_id = (uuid4() for _ in range(5))
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    id=customer_id,
                    telegram_id=None,
                    first_name="Receipt customer",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=staff_user_id,
                    telegram_id=None,
                    first_name="Receipt staff",
                    status=UserStatus.ACTIVE,
                ),
                Venue(
                    id=venue_id,
                    slug=f"receipt-{venue_id.hex}",
                    name="Receipt venue",
                    is_active=True,
                    sort_order=0,
                ),
            ]
        )
        await session.flush()
        session.add(
            StaffMember(
                id=staff_id,
                user_id=staff_user_id,
                role=Role.STAFF,
                is_active=True,
            )
        )
        session.add(
            MediaFile(
                id=media_id,
                storage_key=f"receipt/{media_id}.jpg",
                original_filename="receipt.jpg",
                detected_mime="image/jpeg",
                byte_size=100,
                sha256="0" * 64,
                kind="receipt",
                status=MediaStatus.ACTIVE,
                uploaded_by_user_id=staff_user_id,
                attributes={},
            )
        )

    actor = _actor(staff_user_id, staff_id)
    create_key = str(uuid4())
    command = ReceiptCreateCommand(
        user_id=customer_id,
        venue_id=venue_id,
        amount_minor=6_000_000,
        image_media_id=media_id,
        source=ReceiptSource.MANUAL,
    )
    async with sessions() as session:
        service = ReceiptService(ReceiptRepository(session))
        created = await service.create(actor, command, idempotency_key=create_key)
        replay = await service.create(actor, command, idempotency_key=create_key)
        receipt_id = created.receipt.id
        assert replay.receipt.id == receipt_id
        assert replay.idempotent_replay is True
        assert created.flags == ()

    edit_key = str(uuid4())
    edit = ReceiptEditCommand(
        image_media_id=media_id,
        receipt_number="F-42",
        external_id=None,
        fiscal_data={"shift": 7},
        note="Добавлено после сверки",
    )
    async with sessions() as session:
        service = ReceiptService(ReceiptRepository(session))
        changed = await service.edit(actor, receipt_id, edit, idempotency_key=edit_key)
        replay = await service.edit(actor, receipt_id, edit, idempotency_key=edit_key)
        assert changed.receipt.current_revision == 2
        assert replay.receipt.current_revision == 2
        assert replay.idempotent_replay is True
        assert [item.revision for item in replay.revisions] == [1, 2]

    async with sessions() as session, session.begin():
        flags = list(
            await session.scalars(
                select(ReceiptRiskFlag).where(ReceiptRiskFlag.receipt_id == receipt_id)
            )
        )
        assert {flag.code for flag in flags} == {"high_amount"}
        assert (
            await session.scalar(
                select(ReceiptRevision)
                .where(ReceiptRevision.receipt_id == receipt_id)
                .order_by(ReceiptRevision.revision)
            )
            is not None
        )
        await session.execute(
            delete(ReceiptRiskFlag).where(ReceiptRiskFlag.receipt_id == receipt_id)
        )
        await session.execute(
            delete(ReceiptRevision).where(ReceiptRevision.receipt_id == receipt_id)
        )
        await session.execute(delete(AuditEvent).where(AuditEvent.object_id == receipt_id))
        await session.execute(delete(Receipt).where(Receipt.id == receipt_id))
        await session.execute(delete(MediaFile).where(MediaFile.id == media_id))
        await session.execute(delete(StaffMember).where(StaffMember.id == staff_id))
        await session.execute(delete(Venue).where(Venue.id == venue_id))
        await session.execute(delete(User).where(User.id.in_({customer_id, staff_user_id})))
    await engine.dispose()
