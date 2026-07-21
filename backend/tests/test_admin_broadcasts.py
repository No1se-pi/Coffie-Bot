from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.models.enums import BroadcastStatus, Role
from app.repositories.admin_broadcasts import BroadcastRecord, CreateBroadcastRecord
from app.schemas.broadcasts import BroadcastAudience, BroadcastDraftRequest
from app.security.rbac import Actor
from app.services.admin_broadcasts import (
    AdminBroadcastService,
    BroadcastDraft,
    BroadcastRequestMetadata,
)


def _broadcast(*, title: str = "Новость") -> BroadcastRecord:
    now = datetime.now(UTC)
    return BroadcastRecord(
        id=uuid4(),
        title=title,
        message="Открылись раньше обычного",
        image_media_id=None,
        button_label=None,
        button_url=None,
        audience_filter={"mode": "all_active", "user_ids": []},
        status=BroadcastStatus.DRAFT,
        success_count=0,
        failure_count=0,
        skipped_count=0,
        created_at=now,
        updated_at=now,
        confirmed_at=None,
        started_at=None,
        completed_at=None,
    )


class FakeRepository:
    def __init__(self, result: CreateBroadcastRecord) -> None:
        self.result = result

    async def count_audience(self, audience_filter: dict[str, object]) -> int:
        return 3

    async def create_draft(self, **kwargs: object) -> CreateBroadcastRecord:
        return self.result


def _actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=1,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=uuid4(),
        permissions=frozenset(),
    )


def _draft(*, title: str = "Новость") -> BroadcastDraft:
    return BroadcastDraft(
        title=title,
        message="Открылись раньше обычного",
        image_media_id=None,
        button_label=None,
        button_url=None,
        audience_filter={"mode": "all_active", "user_ids": []},
    )


def test_selected_audience_requires_users() -> None:
    with pytest.raises(ValidationError, match="user_ids"):
        BroadcastAudience(mode="selected")


@pytest.mark.parametrize(
    "values",
    [
        {"button_label": "Подробнее"},
        {"button_url": "https://coffee.example"},
        {"button_label": "Подробнее", "button_url": "http://coffee.example"},
    ],
)
def test_broadcast_button_requires_complete_https_pair(values: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="button"):
        BroadcastDraftRequest(title="Новость", message="Текст", **values)


@pytest.mark.asyncio
async def test_idempotent_replay_returns_existing_broadcast() -> None:
    existing = _broadcast()
    service = AdminBroadcastService(
        FakeRepository(CreateBroadcastRecord(broadcast=existing, created=False))  # type: ignore[arg-type]
    )

    result = await service.create(
        _actor(),
        draft=_draft(),
        idempotency_key=str(uuid4()),
        metadata=BroadcastRequestMetadata(),
    )

    assert result.id == existing.id


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_other_payload_is_rejected() -> None:
    service = AdminBroadcastService(
        FakeRepository(CreateBroadcastRecord(broadcast=_broadcast(), created=False))  # type: ignore[arg-type]
    )

    with pytest.raises(AppError) as error:
        await service.create(
            _actor(),
            draft=_draft(title="Другая новость"),
            idempotency_key=str(uuid4()),
            metadata=BroadcastRequestMetadata(),
        )

    assert error.value.status_code == 409
