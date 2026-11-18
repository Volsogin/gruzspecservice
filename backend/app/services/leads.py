"""Lead intake: validation pipeline → photos → one DB transaction (lead + history + outbox) → 201."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import Conflict, ValidationFailed
from app.core.ratelimit import RateLimiter
from app.core.security import FormTokenError, FormTokenSigner, hash_ip, new_public_token
from app.db.base import utcnow
from app.db.models import (
    ClientChannel,
    Counter,
    Estimate,
    IdempotencyRecord,
    Lead,
    LeadAttachment,
    LeadStatusHistory,
    Service,
)
from app.domain.dispatch import check_point
from app.domain.forms import form_for_lead_type
from app.domain.phone import mask_phone
from app.domain.statuses import DISPATCH_TYPES, LEAD_TYPE_LABELS, LeadStatus, LeadType, status_label
from app.domain.validation import LeadValidator, ValidatedLead
from app.services.notifications import Routing, enqueue_lead_created
from app.services.photos import PhotoService, StoredPhoto, UploadedFile
from app.services.site_settings import SiteSettings, load_settings

logger = logging.getLogger(__name__)

LEAD_COUNTER = "lead"
FIRST_NUMBER = 1001


@dataclass(frozen=True)
class RequestContext:
    ip: str | None = None
    user_agent: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class LeadCreated:
    body: dict[str, Any]
    replayed: bool = False


async def next_lead_number(session: AsyncSession) -> str:
    """Readable sequential number: GS-1001, GS-1002, … (row lock serialises concurrent writers)."""
    result = await session.execute(
        update(Counter).where(Counter.name == LEAD_COUNTER).values(value=Counter.value + 1).returning(Counter.value)
    )
    value = result.scalar_one_or_none()
    if value is None:
        session.add(Counter(name=LEAD_COUNTER, value=FIRST_NUMBER))
        await session.flush()
        value = FIRST_NUMBER
    return f"GS-{value}"


def lead_summary(lead: Lead) -> dict[str, Any]:
    return {
        "type": lead.type,
        "type_label": LEAD_TYPE_LABELS[LeadType(lead.type)],
        "service_slug": lead.service_slug,
        "name": lead.name,
        "phone_masked": mask_phone(lead.phone),
        "vehicle_brand": lead.vehicle_brand,
        "vehicle_type": lead.vehicle_type,
        "address": lead.address,
        "photos_count": len(lead.attachments),
        "created_at": lead.created_at.isoformat(),
    }


def created_response(lead: Lead, settings: Settings) -> dict[str, Any]:
    form = form_for_lead_type(LeadType(lead.type))
    return {
        "id": str(lead.id),
        "number": lead.number,
        "public_token": lead.public_token,
        "tracking_url": settings.tracking_url(lead.public_token),
        "status": lead.status,
        "status_label": status_label(lead.status),
        "summary": lead_summary(lead),
        "callback_eta_minutes": form.callback_eta_minutes,
        "message": form.success_message,
        "telegram_bind_url": settings.telegram_bind_url(lead.public_token),
        "max_bind_url": settings.max_bind_url(lead.public_token),
    }


def _request_hash(data: Mapping[str, Any], files: list[UploadedFile]) -> str:
    stable = {k: v for k, v in data.items() if k not in ("form_token",)}
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, default=str, ensure_ascii=False).encode())
    for f in files:
        digest.update(hashlib.sha256(f.data).digest())
    return digest.hexdigest()


class LeadService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        photos: PhotoService,
        limiter: RateLimiter,
        signer: FormTokenSigner,
        on_commit: Callable[[], None] = lambda: None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.photos = photos
        self.limiter = limiter
        self.signer = signer
        self.on_commit = on_commit
        self.routing = Routing.from_settings(settings)

    async def create_from_form(
        self, data: Mapping[str, Any], files: list[UploadedFile], ctx: RequestContext
    ) -> LeadCreated:
        """Full intake pipeline for `POST /leads`."""
        ip_key = hash_ip(ctx.ip, self.settings.secret_key.get_secret_value()) or "unknown"
        self.limiter.hit(f"lead:ip:{ip_key}", self.settings.leads_per_ip_per_hour, 3600)

        async with self.session_factory() as session:
            site = await load_settings(session)
            validated = LeadValidator(site.timezone).validate(data)
            self._check_form_token(validated)
            self.photos.check_limits(files)

            idem_key = self._idempotency_key(ctx.idempotency_key)
            request_hash = _request_hash(data, files)
            if idem_key and (replay := await self._replay(session, idem_key, request_hash)):
                return replay

            self.limiter.hit(
                f"lead:phone:{validated.columns['phone']}",
                self.settings.leads_per_phone_per_hour,
                3600,
                "С этого номера уже отправлено несколько заявок. Мы скоро перезвоним!",
            )
            await self._check_references(session, validated)

            lead_id = uuid.uuid4()
            stored = await self.photos.store(f"leads/{lead_id.hex}", files) if files else []
            try:
                lead = await self._persist(
                    session, site, validated, lead_id, stored, ip_key, ctx.user_agent, idem_key, request_hash
                )
            except IntegrityError:
                await session.rollback()
                await self.photos.discard(stored)
                if idem_key and (replay := await self._replay(session, idem_key, request_hash)):
                    return replay
                raise
            except Exception:
                await self.photos.discard(stored)
                raise
        self.on_commit()
        logger.info("lead_created", extra={"lead_number": lead.number, "lead_type": lead.type, "photos": len(stored)})
        return LeadCreated(created_response(lead, self.settings))

    # --- pipeline steps -----------------------------------------------------------------------------
    def _check_form_token(self, validated: ValidatedLead) -> None:
        token = validated.form_token
        if not token:
            if self.settings.form_token_required and validated.source == "form":
                raise FormTokenError("Обновите страницу и отправьте форму ещё раз", code="form_token_missing")
            return
        self.signer.verify(
            token,
            validated.lead_type.value,
            min_age=self.settings.form_min_fill_seconds,
            max_age=self.settings.form_token_max_age_seconds,
        )

    @staticmethod
    def _idempotency_key(raw: str | None) -> str | None:
        if raw is None:
            return None
        key = raw.strip()
        if not 8 <= len(key) <= 100 or not key.isascii():
            raise ValidationFailed(
                "Неверный Idempotency-Key", fields={"Idempotency-Key": "8–100 символов ASCII, например UUID"}
            )
        return "lead:" + hashlib.sha256(key.encode()).hexdigest()

    async def _replay(self, session: AsyncSession, key: str, request_hash: str) -> LeadCreated | None:
        record = await session.get(IdempotencyRecord, key)
        if record is None:
            return None
        if record.request_hash != request_hash:
            raise Conflict("Этот Idempotency-Key уже использован для другой заявки", code="idempotency_conflict")
        lead = await session.scalar(
            select(Lead).where(Lead.id == record.lead_id).options(selectinload(Lead.attachments))
        )
        if lead is None:
            return None
        return LeadCreated(created_response(lead, self.settings), replayed=True)

    async def _check_references(self, session: AsyncSession, v: ValidatedLead) -> None:
        errors: dict[str, str] = {}
        estimate_id = v.columns.get("estimate_id")
        if estimate_id is not None and await session.get(Estimate, estimate_id) is None:
            errors["estimate_id"] = "Расчёт не найден — пересчитайте стоимость"
        slug = v.columns.get("service_slug")
        if slug and await session.scalar(select(Service.id).where(Service.slug == slug)) is None:
            errors["service_slug"] = "Неизвестная услуга"
        if errors:
            raise ValidationFailed("Проверьте правильность заполнения полей", fields=errors)
        if estimate_id is not None and v.source == "form":
            v.source = "calculator"

    async def _persist(
        self,
        session: AsyncSession,
        site: SiteSettings,
        v: ValidatedLead,
        lead_id: uuid.UUID,
        photos: list[StoredPhoto],
        ip_hash: str | None,
        user_agent: str | None,
        idem_key: str | None,
        request_hash: str,
    ) -> Lead:
        now = utcnow()
        lead = Lead(
            id=lead_id,
            number=await next_lead_number(session),
            public_token=new_public_token(),
            type=v.lead_type.value,
            source=v.source,
            status=LeadStatus.NEW.value,
            status_changed_at=now,
            details=v.details,
            consent_given=v.consent,
            consent_at=now if v.consent else None,
            consent_version=site.consent_version if v.consent else None,
            ip_hash=ip_hash,
            user_agent=(user_agent or "")[:300] or None,
            created_at=now,
            **v.columns,
        )
        if lead.lat is not None and lead.lon is not None and v.lead_type in DISPATCH_TYPES:
            lead.dispatch_zone = check_point(site.dispatch_config(), lead.lat, lead.lon).zone.value
        lead.attachments = [
            LeadAttachment(
                id=p.id,
                original_key=p.original_key,
                preview_key=p.preview_key,
                content_type=p.content_type,
                size_bytes=p.size_bytes,
                width=p.width,
                height=p.height,
                sha256=p.sha256,
                created_at=now,
            )
            for p in photos
        ]
        lead.history = [
            LeadStatusHistory(from_status=None, to_status=LeadStatus.NEW.value, actor="client", created_at=now)
        ]
        if lead.email:
            lead.channels = [ClientChannel(kind="email", address=lead.email)]
        session.add(lead)
        if idem_key:
            session.add(IdempotencyRecord(key=idem_key, request_hash=request_hash, lead_id=lead_id))
        await session.flush()
        await session.refresh(lead, ["estimate"])
        await enqueue_lead_created(session, lead, self.routing)
        await session.commit()
        return lead

    async def create_chat_handoff(
        self,
        session: AsyncSession,
        *,
        chat_session_id: uuid.UUID,
        phone: str,
        name: str | None,
        transcript: str,
        topic: str,
        consent_at: Any,
        consent_version: str | None,
    ) -> Lead:
        """Lead of type `chat_handoff` created by the assistant. Caller commits."""
        now = utcnow()
        lead = Lead(
            id=uuid.uuid4(),
            number=await next_lead_number(session),
            public_token=new_public_token(),
            type=LeadType.CHAT_HANDOFF.value,
            source="chatbot",
            status=LeadStatus.NEW.value,
            status_changed_at=now,
            name=name,
            phone=phone,
            description=f"Клиент попросил оператора в чате (тема: {topic})",
            details={"transcript": transcript, "topic": topic},
            chat_session_id=chat_session_id,
            consent_given=consent_at is not None,
            consent_at=consent_at,
            consent_version=consent_version,
            created_at=now,
        )
        lead.history = [
            LeadStatusHistory(from_status=None, to_status=LeadStatus.NEW.value, actor="chatbot", created_at=now)
        ]
        session.add(lead)
        await session.flush()
        await session.refresh(lead, ["estimate", "attachments"])
        await enqueue_lead_created(session, lead, self.routing)
        return lead
