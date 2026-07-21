from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import Session
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.delivery import NotificationOutbox
from app.models.loyalty import LoyaltyOperation, PointTransaction, UserLoyaltyState
from app.repositories.identity import IdentityRepository
from app.security.sessions import issue_session_token

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.batches = 0

    def add_all(self, instances: Iterable[object]) -> None:
        self.batches += 1
        self.added.extend(instances)

    def add(self, instance: object) -> None:
        self.added.append(instance)


def _repository(session: RecordingSession) -> IdentityRepository:
    return IdentityRepository(cast(AsyncSession, session))


def test_first_registration_stages_complete_aggregate_in_one_batch() -> None:
    session = RecordingSession()
    repository = _repository(session)
    user_id = uuid4()

    repository.initialize_customer(
        user_id=user_id,
        qr_token="opaque-qr-token",
        short_code="BEAN2026",
        welcome_bonus_points=25,
        now=NOW,
        ip_address="127.0.0.1",
        user_agent="test-client",
    )

    assert session.batches == 1
    assert {type(item) for item in session.added} == {
        UserLoyaltyState,
        UserCard,
        LoyaltyOperation,
        PointTransaction,
        AuditEvent,
        NotificationOutbox,
    }

    state = next(item for item in session.added if isinstance(item, UserLoyaltyState))
    card = next(item for item in session.added if isinstance(item, UserCard))
    operation = next(item for item in session.added if isinstance(item, LoyaltyOperation))
    transaction = next(item for item in session.added if isinstance(item, PointTransaction))
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    notification = next(item for item in session.added if isinstance(item, NotificationOutbox))

    assert state.points_balance == 25
    assert card.qr_token == "opaque-qr-token"
    assert card.short_code == "BEAN2026"
    assert operation.idempotency_key == f"welcome:{user_id}"
    assert operation.balance_before == 0
    assert operation.balance_after == 25
    assert transaction.operation_id == operation.id
    assert audit.event_type == "user.registered"
    assert audit.event_metadata == {"welcome_bonus_points": 25}
    assert notification.event_type == "user.registered"
    assert notification.idempotency_key == f"registration:{user_id}"


def test_session_persistence_receives_only_the_opaque_token_hash() -> None:
    session = RecordingSession()
    repository = _repository(session)
    issued = issue_session_token(
        ttl=timedelta(minutes=15),
        pepper="test-pepper",
        now=NOW,
    )

    repository.create_session(
        user_id=uuid4(),
        issued=issued,
        ip_address="127.0.0.1",
        user_agent="test-client",
    )

    stored = session.added[0]
    assert isinstance(stored, Session)
    assert stored.token_hash == issued.token_hash
    assert stored.token_hash != issued.raw_token
    assert not hasattr(stored, "raw_token")
