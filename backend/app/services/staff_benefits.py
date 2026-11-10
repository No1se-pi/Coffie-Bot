"""Employee allowances are separate from customer loyalty and expire by monthly lot."""

import hashlib
import json
import secrets
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.core.errors import AppError
from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.enums import LoyaltyProgram, RewardStatus, RewardType, Role, UserStatus
from app.models.loyalty import Reward, RewardTemplate
from app.models.staff_benefits import StaffBenefitGrant, StaffBenefitOperation, StaffBenefitPolicy
from app.repositories.pricing import PricingRepository
from app.repositories.staff_benefits import StaffBenefitRepository
from app.security.rbac import Actor
from app.services.pricing import CartPricingService, RequestedModifier


def month_bounds(now: datetime, timezone: str) -> tuple[date, datetime]:
    local = now.astimezone(ZoneInfo(timezone))
    period = date(local.year, local.month, 1)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return period, datetime(year, month, 1, tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def bonus_cost(minor_units: int, minor_units_per_point: int = 100) -> int:
    if minor_units <= 0:
        raise AppError(
            code="staff_benefit_zero_price", message="Позиция недоступна за бонусы", status_code=409
        )
    if minor_units_per_point <= 0:
        raise ValueError("Point value must be positive")
    return (minor_units + minor_units_per_point - 1) // minor_units_per_point


def eligible(user: User, staff: StaffMember) -> bool:
    return (
        user.status == UserStatus.ACTIVE
        and staff.is_active
        and staff.archived_at is None
        and staff.role in {Role.STAFF, Role.ADMIN, Role.OWNER}
    )


class StaffBenefitService:
    def __init__(self, repository: StaffBenefitRepository) -> None:
        self.repo = repository

    def audit(
        self, staff: StaffMember, event: str, data: dict[str, Any], actor: Actor | None = None
    ) -> None:
        self.repo.add(
            AuditEvent(
                id=uuid4(),
                event_type=event,
                actor_user_id=actor.user_id if actor else None,
                actor_staff_id=actor.staff_member_id if actor else None,
                subject_user_id=staff.user_id,
                object_type="staff_benefit",
                object_id=staff.id,
                event_metadata=data,
            )
        )

    async def settle(
        self, user: User, staff: StaffMember, policy: StaffBenefitPolicy | None, now: datetime
    ) -> StaffBenefitGrant | None:
        period, expires = month_bounds(now, await self.repo.timezone())
        grants = await self.repo.grants(staff.id)
        for lot in grants:
            if lot.remaining_points and lot.expires_at <= now:
                amount = lot.remaining_points
                lot.remaining_points = 0
                self.repo.add(
                    StaffBenefitOperation(
                        id=uuid4(),
                        staff_id=staff.id,
                        grant_id=lot.id,
                        kind="expire",
                        delta=-amount,
                        balance_after=0,
                        idempotency_key=f"expire:{lot.period}",
                        request_hash="expiry",
                        snapshot={"period": str(lot.period)},
                        created_at=now,
                    )
                )
                self.audit(
                    staff, "staff_benefit.expired", {"points": amount, "period": str(lot.period)}
                )
        current = next((lot for lot in grants if lot.period == period), None)
        if policy is None or not policy.enabled or not eligible(user, staff):
            return None
        if current is None:
            current = StaffBenefitGrant(
                id=uuid4(),
                staff_id=staff.id,
                period=period,
                initial_points=policy.monthly_points,
                remaining_points=policy.monthly_points,
                earned_at=now,
                expires_at=expires,
            )
            self.repo.add(current)
            await self.repo.flush()
            self.repo.add(
                StaffBenefitOperation(
                    id=uuid4(),
                    staff_id=staff.id,
                    grant_id=current.id,
                    kind="grant",
                    delta=current.initial_points,
                    balance_after=current.initial_points,
                    idempotency_key=f"grant:{period}",
                    request_hash="monthly",
                    snapshot={"period": str(period)},
                    created_at=now,
                )
            )
            self.audit(
                staff,
                "staff_benefit.granted",
                {"points": current.initial_points, "period": str(period)},
            )
        return current

    async def view(self, staff_id: UUID, *, now: datetime | None = None) -> dict[str, Any]:
        current_time = now or datetime.now(UTC)
        async with self.repo.transaction():
            pair = await self.repo.lock_staff(staff_id)
            if pair is None:
                raise AppError(
                    code="staff_not_found", message="Сотрудник не найден", status_code=404
                )
            user, staff = pair
            policy = await self.repo.policy(staff_id)
            lot = await self.settle(user, staff, policy, current_time)
            await self.repo.flush()
            return {
                "staff_id": staff_id,
                "enabled": lot is not None,
                "monthly_points": policy.monthly_points if policy else 3000,
                "all_items": policy.all_items if policy else True,
                "item_ids": policy.item_ids if policy else [],
                "balance_points": lot.remaining_points if lot else 0,
                "expires_at": lot.expires_at if lot else None,
            }

    async def configure(
        self,
        actor: Actor,
        staff_id: UUID,
        *,
        enabled: bool,
        monthly_points: int,
        all_items: bool,
        item_ids: list[UUID],
    ) -> dict[str, Any]:
        if actor.role != Role.OWNER:
            raise AppError(
                code="forbidden", message="Настройка доступна владельцу", status_code=403
            )
        if monthly_points <= 0 or monthly_points > 1_000_000:
            raise AppError(
                code="invalid_amount", message="Укажите от 1 до 1000000 бонусов", status_code=422
            )
        async with self.repo.transaction():
            pair = await self.repo.lock_staff(staff_id)
            if pair is None or pair[1].role == Role.COURIER:
                raise AppError(
                    code="staff_not_found", message="Сотрудник не найден", status_code=404
                )
            user, staff = pair
            if not all_items and set(item_ids) != await self.repo.available_ids(set(item_ids)):
                raise AppError(
                    code="invalid_items", message="Позиции меню не найдены", status_code=422
                )
            policy = await self.repo.policy(staff_id)
            if policy is None:
                policy = StaffBenefitPolicy(id=uuid4(), staff_id=staff_id)
                self.repo.add(policy)
            policy.enabled, policy.monthly_points, policy.all_items = (
                enabled,
                monthly_points,
                all_items,
            )
            policy.item_ids = [] if all_items else sorted({str(item) for item in item_ids})
            self.audit(
                staff,
                "staff_benefit.configured",
                {
                    "enabled": enabled,
                    "monthly_points": monthly_points,
                    "all_items": all_items,
                    "item_ids": policy.item_ids,
                },
                actor,
            )
            await self.repo.flush()
            await self.settle(user, staff, policy, datetime.now(UTC))
            await self.repo.flush()
        return await self.view(staff_id)

    async def purchase(
        self,
        actor: Actor,
        *,
        item_id: UUID,
        modifiers: tuple[RequestedModifier, ...],
        key: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or datetime.now(UTC)
        if actor.staff_member_id is None or actor.role == Role.COURIER:
            raise AppError(code="forbidden", message="Бонусы доступны сотрудникам", status_code=403)
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "item": str(item_id),
                    "modifiers": sorted((str(m.option_id), m.quantity) for m in modifiers),
                }
            ).encode()
        ).hexdigest()
        async with self.repo.transaction():
            pair = await self.repo.lock_staff(actor.staff_member_id)
            if pair is None or pair[0].id != actor.user_id or not eligible(*pair):
                raise AppError(
                    code="forbidden", message="Доступ сотрудника отключён", status_code=403
                )
            user, staff = pair
            existing = await self.repo.operation(staff.id, "purchase:" + key)
            if existing:
                if existing.request_hash != request_hash:
                    raise AppError(
                        code="idempotency_conflict",
                        message="Ключ уже использован для другой покупки",
                        status_code=409,
                    )
                return {
                    **{
                        k: v
                        for k, v in existing.snapshot.items()
                        if k not in {"price_minor", "modifiers"}
                    },
                    "idempotent_replay": True,
                }
            policy = await self.repo.policy(staff.id)
            lot = await self.settle(user, staff, policy, current_time)
            if lot is None or policy is None:
                raise AppError(
                    code="benefit_disabled",
                    message="Бонусы сотрудника не подключены",
                    status_code=409,
                )
            if not policy.all_items and str(item_id) not in policy.item_ids:
                raise AppError(
                    code="item_not_eligible",
                    message="Позиция не входит в программу сотрудника",
                    status_code=409,
                )
            item = await self.repo.item(item_id)
            if item is None or item.archived_at or not item.is_visible or not item.is_available:
                raise AppError(
                    code="item_unavailable", message="Позиция недоступна", status_code=409
                )
            price = await CartPricingService(PricingRepository(self.repo.session)).preview(
                user_id=user.id,
                lines=((uuid4(), item_id, 1, modifiers),),
                fulfillment_mode="pickup",
                now=current_time,
            )
            # Pay catalogue prices including modifiers; customer promotions do not stack.
            points = bonus_cost(price.subtotal_minor, policy.minor_units_per_point)
            if lot.remaining_points < points:
                raise AppError(
                    code="insufficient_staff_bonus",
                    message="Недостаточно бонусов сотрудника",
                    status_code=409,
                )
            selected = price.venues[0].lines[0].modifiers
            description = "Бонусы сотрудника. " + "; ".join(m.name for m in selected)
            template = RewardTemplate(
                id=uuid4(),
                name=item.name,
                description=description,
                reward_type=RewardType.FREE_PRODUCT,
                source_program=LoyaltyProgram.MANUAL,
                source_menu_item_id=item.id,
                image_media_id=item.image_media_id,
                is_active=False,
            )
            self.repo.add(template)
            await self.repo.flush()
            reward = Reward(
                id=uuid4(),
                user_id=user.id,
                template_id=template.id,
                name=item.name,
                description=description,
                reward_type=RewardType.FREE_PRODUCT,
                status=RewardStatus.ACTIVE,
                expires_at=lot.expires_at,
                qr_payload=f"coffee-reward:v1:{secrets.token_urlsafe(32)}",
                created_at=current_time,
            )
            self.repo.add(reward)
            await self.repo.flush()
            lot.remaining_points -= points
            operation_id = uuid4()
            result = {
                "operation_id": str(operation_id),
                "reward_id": str(reward.id),
                "item_id": str(item.id),
                "item_name": item.name,
                "points_spent": points,
                "balance_after": lot.remaining_points,
                "qr_payload": reward.qr_payload,
                "expires_at": lot.expires_at.isoformat(),
                "idempotent_replay": False,
            }
            self.repo.add(
                StaffBenefitOperation(
                    id=operation_id,
                    staff_id=staff.id,
                    grant_id=lot.id,
                    kind="spend",
                    delta=-points,
                    balance_after=lot.remaining_points,
                    idempotency_key="purchase:" + key,
                    request_hash=request_hash,
                    snapshot={
                        **result,
                        "price_minor": price.subtotal_minor,
                        "modifiers": [
                            {"name": m.name, "price_minor": m.total_price_delta_minor}
                            for m in selected
                        ],
                    },
                    reward_id=reward.id,
                    created_at=current_time,
                )
            )
            self.audit(
                staff,
                "staff_benefit.purchased",
                {"item_id": str(item.id), "points": points, "reward_id": str(reward.id)},
                actor,
            )
            await self.repo.flush()
            return result

    async def process_batch(self, limit: int = 50) -> int:
        now = datetime.now(UTC)
        period, _ = month_bounds(now, await self.repo.timezone())
        ids = await self.repo.due_staff(period, now, limit)
        for staff_id in ids:
            await self.view(staff_id, now=now)
        return len(ids)
