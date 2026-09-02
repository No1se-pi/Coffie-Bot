"""PostgreSQL coverage for Phase 7 moderation, passes, and bulk bonus."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import MenuCategory, MenuItem, Venue
from app.models.delivery import NotificationOutbox
from app.models.engagement import (
    BulkBonusBatch,
    BulkBonusItem,
    CustomerPass,
    PassPurchase,
    PassTemplate,
    PassTemplateCategory,
    PassTemplateItem,
    PassTemplateVenue,
    PassUsage,
    PublicReview,
)
from app.models.enums import (
    CardStatus,
    LoyaltyOperationType,
    PaymentMethod,
    PermissionCode,
    ReviewStatus,
    Role,
    UserStatus,
)
from app.models.loyalty import LoyaltyOperation, PointTransaction, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.repositories.bulk_bonus import BulkBonusRepository
from app.repositories.reviews import ReviewRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.security.rbac import Actor
from app.services.bulk_bonus import BulkBonusCommand, BulkBonusService
from app.services.reviews import ReviewCreateCommand, ReviewService
from app.services.subscriptions import SubscriptionService, TemplateCreateCommand


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _actor(user_id: UUID, staff_id: UUID, role: Role) -> Actor:
    return Actor(
        user_id=user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=role,
        staff_member_id=staff_id,
        permissions=frozenset(PermissionCode),
    )


@pytest.mark.asyncio
async def test_reviews_pass_usage_race_and_bulk_bonus_are_auditable() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    customer_id, admin_user_id, admin_id, venue_id, category_id, item_id = (
        uuid4() for _ in range(6)
    )
    card_id, state_id = uuid4(), uuid4()
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    id=customer_id,
                    telegram_id=None,
                    first_name="Phase seven customer",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=admin_user_id,
                    telegram_id=None,
                    first_name="Phase seven admin",
                    status=UserStatus.ACTIVE,
                ),
                Venue(
                    id=venue_id,
                    slug=f"phase-seven-{venue_id.hex}",
                    name="Phase seven venue",
                    is_active=True,
                    sort_order=0,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                StaffMember(
                    id=admin_id,
                    user_id=admin_user_id,
                    role=Role.ADMIN,
                    is_active=True,
                ),
                UserCard(
                    id=card_id,
                    user_id=customer_id,
                    qr_token=f"phase-seven-{card_id.hex}",
                    short_code=card_id.hex[:12],
                    status=CardStatus.ACTIVE,
                ),
                UserLoyaltyState(
                    id=state_id,
                    user_id=customer_id,
                    points_balance=0,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=1,
                ),
                MenuCategory(
                    id=category_id,
                    venue_id=venue_id,
                    name="Pass category",
                    is_visible=True,
                    sort_order=0,
                ),
            ]
        )
        await session.flush()
        session.add(
            MenuItem(
                id=item_id,
                venue_id=venue_id,
                category_id=category_id,
                name="Pass coffee",
                price_minor=20_000,
                labels=[],
                is_available=True,
                is_visible=True,
                sort_order=0,
            )
        )

    customer = _actor(customer_id, admin_id, Role.CUSTOMER)
    admin = _actor(admin_user_id, admin_id, Role.ADMIN)

    async with sessions() as session:
        reviews = ReviewService(ReviewRepository(session))
        created = await reviews.create(
            customer,
            ReviewCreateCommand(venue_id=venue_id, rating=5, text="Очень хороший кофе"),
        )
        assert await reviews.list_public(venue_id=venue_id, limit=10) == []
        moderated = await reviews.moderate(
            admin,
            created.review.id,
            target_status=ReviewStatus.APPROVED,
            note="Проверено",
        )
        assert moderated.review.status is ReviewStatus.APPROVED
        assert len(await reviews.list_public(venue_id=venue_id, limit=10)) == 1
        review_id = created.review.id

    async with sessions() as session:
        subscriptions = SubscriptionService(SubscriptionRepository(session))
        template = await subscriptions.create_template(
            admin,
            TemplateCreateCommand(
                name="Один кофе",
                description="Тест конкурентного использования",
                total_uses=1,
                validity_days=30,
                price_minor=15_000,
                purchase_enabled=True,
                image_media_id=None,
                venue_ids=frozenset({venue_id}),
                category_ids=frozenset({category_id}),
                item_ids=frozenset(),
            ),
        )
        issued = await subscriptions.issue(
            admin,
            user_id=customer_id,
            template_id=template.template.id,
            idempotency_key=str(uuid4()),
        )
        pass_id, template_id = issued.value.id, template.template.id
        purchase = await subscriptions.purchase(
            customer,
            template_id=template_id,
            payment_method=PaymentMethod.CARD_ON_RECEIPT,
            idempotency_key=str(uuid4()),
        )
        confirmed_purchase = await subscriptions.confirm_purchase(admin, purchase.id)
        assert confirmed_purchase.status == "paid"
        assert confirmed_purchase.customer_pass_id is not None
        purchase_id = purchase.id
        purchased_pass_id = confirmed_purchase.customer_pass_id

    async def redeem_once() -> str:
        async with sessions() as session:
            try:
                await SubscriptionService(SubscriptionRepository(session)).use(
                    admin,
                    pass_id=pass_id,
                    venue_id=venue_id,
                    item_id=item_id,
                    idempotency_key=str(uuid4()),
                )
                return "used"
            except AppError as exc:
                return str(exc.code)

    outcomes = await asyncio.gather(redeem_once(), redeem_once())
    assert outcomes.count("used") == 1
    assert len([value for value in outcomes if value != "used"]) == 1

    bulk_key = str(uuid4())
    command = BulkBonusCommand(
        customer_ids=frozenset({customer_id}),
        points_per_user=25,
        reason="Компенсация за тест",
        venue_id=venue_id,
    )
    async with sessions() as session:
        bonuses = BulkBonusService(BulkBonusRepository(session))
        preview = await bonuses.preview(admin, command)
        first = await bonuses.confirm(
            admin,
            command,
            preview_hash=preview.preview_hash,
            idempotency_key=bulk_key,
        )
        replay = await bonuses.confirm(
            admin,
            command,
            preview_hash=preview.preview_hash,
            idempotency_key=bulk_key,
        )
        assert first.batch.id == replay.batch.id
        assert replay.replay is True
        batch_id = first.batch.id
        operation_id = first.items[0].operation_id

    async with sessions() as session, session.begin():
        state = await session.get(UserLoyaltyState, state_id)
        assert state is not None
        assert state.points_balance == 25
        operation = await session.get(LoyaltyOperation, operation_id)
        assert operation is not None
        assert operation.operation_type is LoyaltyOperationType.BULK_BONUS
        assert operation.points_delta == 25

        # Delete only synthetic rows in reverse dependency order.
        await session.execute(
            delete(NotificationOutbox).where(NotificationOutbox.user_id == customer_id)
        )
        await session.execute(
            delete(AuditEvent).where(
                (AuditEvent.actor_user_id == admin_user_id)
                | (
                    AuditEvent.object_id.in_(
                        {review_id, pass_id, template_id, batch_id, purchase_id}
                    )
                )
            )
        )
        await session.execute(delete(PassUsage).where(PassUsage.pass_id == pass_id))
        await session.execute(delete(PassPurchase).where(PassPurchase.id == purchase_id))
        await session.execute(delete(CustomerPass).where(CustomerPass.id == purchased_pass_id))
        await session.execute(delete(CustomerPass).where(CustomerPass.id == pass_id))
        await session.execute(
            delete(PassTemplateVenue).where(PassTemplateVenue.template_id == template_id)
        )
        await session.execute(
            delete(PassTemplateCategory).where(PassTemplateCategory.template_id == template_id)
        )
        await session.execute(
            delete(PassTemplateItem).where(PassTemplateItem.template_id == template_id)
        )
        await session.execute(delete(PassTemplate).where(PassTemplate.id == template_id))
        await session.execute(delete(PublicReview).where(PublicReview.id == review_id))
        await session.execute(delete(BulkBonusItem).where(BulkBonusItem.batch_id == batch_id))
        await session.execute(delete(BulkBonusBatch).where(BulkBonusBatch.id == batch_id))
        await session.execute(
            delete(PointTransaction).where(PointTransaction.operation_id == operation_id)
        )
        await session.execute(delete(PointLot).where(PointLot.source_operation_id == operation_id))
        await session.execute(delete(LoyaltyOperation).where(LoyaltyOperation.id == operation_id))
        await session.execute(delete(LoyaltyWallet).where(LoyaltyWallet.user_id == customer_id))
        await session.execute(delete(MenuItem).where(MenuItem.id == item_id))
        await session.execute(delete(MenuCategory).where(MenuCategory.id == category_id))
        await session.execute(delete(UserCard).where(UserCard.id == card_id))
        await session.execute(delete(UserLoyaltyState).where(UserLoyaltyState.id == state_id))
        await session.execute(delete(StaffMember).where(StaffMember.id == admin_id))
        await session.execute(delete(Venue).where(Venue.id == venue_id))
        await session.execute(delete(User).where(User.id.in_({customer_id, admin_user_id})))
    await engine.dispose()
