"""Real transactions cover monthly limits, concurrent spends and API roles."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.main import create_app
from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import MenuCategory, MenuItem, Venue
from app.models.delivery import NotificationOutbox
from app.models.enums import PointLotSourceType, Role, UserStatus
from app.models.loyalty import LoyaltyOperation, Reward, RewardTemplate, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.models.staff_benefits import StaffBenefitGrant, StaffBenefitOperation, StaffBenefitPolicy
from app.repositories.loyalty import LoyaltyRepository
from app.repositories.staff_benefits import StaffBenefitRepository
from app.security.rbac import Actor, get_current_actor, resolve_permissions
from app.services.loyalty import LoyaltyService
from app.services.staff_benefits import StaffBenefitService


@pytest.fixture
async def benefit_data():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL required")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner_uid, owner_id, uid, staff_id, venue, category, item, other = (uuid4() for _ in range(8))
    async with sessions() as session, session.begin():
        session.add_all(
            [
                User(id=owner_uid, first_name="Benefits owner", status=UserStatus.ACTIVE),
                User(id=uid, first_name="Benefits employee", status=UserStatus.ACTIVE),
                Venue(
                    id=venue, slug=f"benefits-{venue.hex}", name="Benefits venue", is_active=True
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                StaffMember(id=owner_id, user_id=owner_uid, role=Role.OWNER, is_active=True),
                StaffMember(id=staff_id, user_id=uid, role=Role.STAFF, is_active=True),
                UserLoyaltyState(user_id=uid, points_balance=555),
                UserCard(user_id=uid, qr_token=uuid4().hex, short_code=uuid4().hex[:12]),
                MenuCategory(id=category, venue_id=venue, name="Coffee", is_visible=True),
            ]
        )
        await session.flush()
        wallet = LoyaltyWallet(id=uuid4(), user_id=uid, balance_points=555)
        session.add(wallet)
        await session.flush()
        session.add(
            PointLot(
                wallet_id=wallet.id,
                source_type=PointLotSourceType.OPENING_BALANCE,
                initial_points=555,
                remaining_points=555,
                earned_at=datetime.now(UTC),
            )
        )
        session.add_all(
            [
                MenuItem(
                    id=value,
                    venue_id=venue,
                    category_id=category,
                    name="Coffee",
                    price_minor=200000,
                    is_visible=True,
                    is_available=True,
                )
                for value in [item, other]
            ]
        )
    owner = Actor(
        user_id=owner_uid,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.OWNER,
        staff_member_id=owner_id,
        permissions=resolve_permissions(Role.OWNER),
    )
    employee = Actor(
        user_id=uid,
        telegram_id=2,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=staff_id,
        permissions=resolve_permissions(Role.STAFF),
    )
    async with sessions() as session:
        await StaffBenefitService(StaffBenefitRepository(session)).configure(
            owner, staff_id, enabled=True, monthly_points=3000, all_items=True, item_ids=[]
        )
    try:
        yield sessions, owner, employee, item, other, engine
    finally:
        # These UUID-scoped records belong solely to this disposable integration fixture.
        async with sessions() as session, session.begin():
            rewards = list(
                (await session.scalars(select(Reward).where(Reward.user_id == uid))).all()
            )
            templates = [reward.template_id for reward in rewards]
            await session.execute(
                delete(StaffBenefitOperation).where(StaffBenefitOperation.staff_id == staff_id)
            )
            await session.execute(
                delete(StaffBenefitGrant).where(StaffBenefitGrant.staff_id == staff_id)
            )
            await session.execute(
                delete(StaffBenefitPolicy).where(StaffBenefitPolicy.staff_id == staff_id)
            )
            await session.execute(
                delete(NotificationOutbox).where(NotificationOutbox.user_id == uid)
            )
            await session.execute(delete(Reward).where(Reward.user_id == uid))
            await session.execute(delete(LoyaltyOperation).where(LoyaltyOperation.user_id == uid))
            await session.execute(delete(RewardTemplate).where(RewardTemplate.id.in_(templates)))
            await session.execute(delete(AuditEvent).where(AuditEvent.subject_user_id == uid))
            wallet_ids = select(LoyaltyWallet.id).where(LoyaltyWallet.user_id == uid)
            await session.execute(delete(PointLot).where(PointLot.wallet_id.in_(wallet_ids)))
            await session.execute(delete(LoyaltyWallet).where(LoyaltyWallet.user_id == uid))
            await session.execute(delete(UserLoyaltyState).where(UserLoyaltyState.user_id == uid))
            await session.execute(delete(UserCard).where(UserCard.user_id == uid))
            await session.execute(delete(MenuItem).where(MenuItem.id.in_([item, other])))
            await session.execute(delete(MenuCategory).where(MenuCategory.id == category))
            await session.execute(delete(Venue).where(Venue.id == venue))
            await session.execute(
                delete(StaffMember).where(StaffMember.id.in_([owner_id, staff_id]))
            )
            await session.execute(delete(User).where(User.id.in_([owner_uid, uid])))
        await engine.dispose()


async def buy(sessions, actor, item_id, key):
    async with sessions() as session:
        return await StaffBenefitService(StaffBenefitRepository(session)).purchase(
            actor, item_id=item_id, modifiers=(), key=key
        )


@pytest.mark.asyncio
async def test_employee_purchase_qr_is_redeemed_through_the_existing_staff_flow(benefit_data):
    sessions, owner, employee, item, _, _ = benefit_data
    purchase = await buy(sessions, employee, item, str(uuid4()))
    async with sessions() as session:
        service = LoyaltyService(LoyaltyRepository(session))
        lookup = await service.lookup_reward_qr(owner, qr_payload=purchase["qr_payload"])
        assert str(lookup.reward_id) == purchase["reward_id"]
    from uuid import UUID

    async with sessions() as session:
        await LoyaltyService(LoyaltyRepository(session)).redeem_reward(
            owner, reward_id=UUID(purchase["reward_id"]), idempotency_key=str(uuid4())
        )
    async with sessions() as session:
        reward = await session.get(Reward, UUID(purchase["reward_id"]))
        assert reward.status.value == "redeemed"


@pytest.mark.asyncio
async def test_concurrent_purchases_cannot_overspend_and_customer_points_stay_separate(
    benefit_data,
):
    sessions, _, employee, item, _, _ = benefit_data
    results = await asyncio.gather(
        buy(sessions, employee, item, str(uuid4())),
        buy(sessions, employee, item, str(uuid4())),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    failures = [result for result in results if isinstance(result, AppError)]
    assert len(failures) == 1
    assert failures[0].code == "insufficient_staff_bonus"
    async with sessions() as session:
        state = await session.scalar(
            select(UserLoyaltyState).where(UserLoyaltyState.user_id == employee.user_id)
        )
        assert state.points_balance == 555
        view = await StaffBenefitService(StaffBenefitRepository(session)).view(
            employee.staff_member_id
        )
        assert view["balance_points"] == 1000


@pytest.mark.asyncio
async def test_concurrent_retry_reuses_one_reward_and_changed_payload_conflicts(benefit_data):
    sessions, _, employee, item, other, _ = benefit_data
    key = str(uuid4())
    results = await asyncio.gather(
        buy(sessions, employee, item, key), buy(sessions, employee, item, key)
    )
    assert results[0]["reward_id"] == results[1]["reward_id"]
    assert sorted(result["idempotent_replay"] for result in results) == [False, True]
    with pytest.raises(AppError, match="Ключ уже использован"):
        await buy(sessions, employee, other, key)


@pytest.mark.asyncio
async def test_expiry_is_journalled_and_next_month_grants_only_once(benefit_data):
    sessions, _, employee, _, _, _ = benefit_data
    async with sessions() as session:
        first = await session.scalar(
            select(StaffBenefitGrant).where(StaffBenefitGrant.staff_id == employee.staff_member_id)
        )
        future = first.expires_at + timedelta(seconds=1)
    for _ in range(2):
        async with sessions() as session:
            view = await StaffBenefitService(StaffBenefitRepository(session)).view(
                employee.staff_member_id, now=future
            )
            assert view["balance_points"] == 3000
    async with sessions() as session:
        operations = list(
            (
                await session.scalars(
                    select(StaffBenefitOperation).where(
                        StaffBenefitOperation.staff_id == employee.staff_member_id
                    )
                )
            ).all()
        )
        assert sorted(op.kind for op in operations) == ["expire", "grant", "grant"]
        assert sum(op.delta for op in operations) == 3000


@pytest.mark.asyncio
async def test_item_restrictions_and_disabled_staff_are_rechecked(benefit_data):
    sessions, owner, employee, item, other, _ = benefit_data
    async with sessions() as session:
        await StaffBenefitService(StaffBenefitRepository(session)).configure(
            owner,
            employee.staff_member_id,
            enabled=True,
            monthly_points=3000,
            all_items=False,
            item_ids=[item],
        )
    with pytest.raises(AppError, match="не входит"):
        await buy(sessions, employee, other, str(uuid4()))
    async with sessions() as session, session.begin():
        staff = await session.get(StaffMember, employee.staff_member_id)
        staff.is_active = False
    with pytest.raises(AppError, match="отключён"):
        await buy(sessions, employee, item, str(uuid4()))


@pytest.mark.asyncio
async def test_api_owner_settings_and_self_only_employee_balance(benefit_data):
    sessions, owner, employee, item, _, engine = benefit_data
    app = create_app(
        settings=Settings(app_env="test", database_url=str(engine.url)),
        database=Database(engine, sessions),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/me/staff-benefits")).status_code == 401
        app.dependency_overrides[get_current_actor] = lambda: employee
        denied = await client.put(
            f"/api/v1/admin/staff/{employee.staff_member_id}/benefits",
            json={"enabled": True, "monthly_points": 9999, "all_items": True},
        )
        assert denied.status_code == 403
        view = await client.get("/api/v1/me/staff-benefits")
        assert view.status_code == 200
        assert view.json()["staff_id"] == str(employee.staff_member_id)
        purchase = await client.post(
            "/api/v1/me/staff-benefits/purchases",
            headers={"Idempotency-Key": str(uuid4())},
            json={"item_id": str(item), "modifiers": []},
        )
        assert purchase.status_code == 200
        assert purchase.json()["balance_after"] == 1000
        app.dependency_overrides[get_current_actor] = lambda: owner
        response = await client.put(
            f"/api/v1/admin/staff/{employee.staff_member_id}/benefits",
            json={"enabled": True, "monthly_points": 4000, "all_items": True},
        )
        assert response.status_code == 200
        assert response.json()["monthly_points"] == 4000
        assert response.json()["balance_points"] == 1000
