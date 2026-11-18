"""Operator admin UI (SQLAdmin) at /admin. Login: any username, password = ADMIN_TOKEN."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from fastapi import FastAPI
from sqladmin import Admin, ModelView, action
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.container import Container
from app.core.errors import AppError
from app.core.security import constant_time_equals
from app.db.models import (
    Case,
    CasePhoto,
    ChatMessage,
    ChatSession,
    Lead,
    LeadStatusHistory,
    Operator,
    OutboxMessage,
    PriceBrand,
    PriceVehicleType,
    PriceWorkType,
    Review,
    Service,
    Setting,
)
from app.domain.statuses import STATUS_LABELS, LeadStatus
from app.services.lead_status import change_status
from app.services.notifications import Routing


class TokenAuth(AuthenticationBackend):
    def __init__(self, secret_key: str, admin_token: str | None) -> None:
        super().__init__(secret_key=secret_key)
        self.admin_token = admin_token

    async def login(self, request: Request) -> bool:
        form = await request.form()
        password = form.get("password")
        if isinstance(password, str) and constant_time_equals(password, self.admin_token):
            request.session.update({"admin": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(self.admin_token) and bool(request.session.get("admin"))


class _ContainerAware:
    container: ClassVar[Container]


class LeadAdmin(ModelView, _ContainerAware, model=Lead):
    name, name_plural, icon = "Заявка", "Заявки", "fa-solid fa-truck"
    can_create = False
    column_list: ClassVar[list[Any]] = [
        Lead.number,
        Lead.type,
        Lead.status,
        Lead.name,
        Lead.phone,
        Lead.vehicle_brand,
        Lead.source,
        Lead.assignee_name,
        Lead.created_at,
    ]
    column_searchable_list: ClassVar[list[Any]] = [Lead.number, Lead.phone, Lead.name]
    column_sortable_list: ClassVar[list[Any]] = [Lead.created_at, Lead.status, Lead.number]
    column_default_sort: ClassVar[list[Any]] = [(Lead.created_at, True)]
    column_details_exclude_list: ClassVar[list[Any]] = [Lead.public_token, Lead.ip_hash]
    # Status changes only through actions → the status service (history + notifications).
    form_excluded_columns: ClassVar[list[Any]] = [
        Lead.status,
        Lead.status_changed_at,
        Lead.public_token,
        Lead.number,
        Lead.history,
        Lead.channels,
        Lead.attachments,
        Lead.estimate,
        Lead.created_at,
        Lead.updated_at,
        Lead.ip_hash,
        Lead.consent_at,
        Lead.consent_given,
        Lead.consent_version,
        Lead.chat_session_id,
        Lead.assigned_operator,
        Lead.assigned_operator_id,
        Lead.assignee_name,
    ]

    async def _change(self, request: Request, target: LeadStatus) -> Response:
        errors = []
        async with self.container.session_factory() as db:
            for pk in filter(None, request.query_params.get("pks", "").split(",")):
                try:
                    await change_status(
                        db,
                        uuid.UUID(pk),
                        target.value,
                        actor="admin:ui",
                        routing=Routing.from_settings(self.container.settings),
                    )
                except (AppError, ValueError) as exc:
                    errors.append(str(exc))
            await db.commit()
        self.container.outbox.kick()
        url = request.url_for("admin:list", identity=self.identity)
        return RedirectResponse(str(url) + (f"?search=&error={len(errors)}" if errors else ""), status_code=302)

    @action(name="accept", label=STATUS_LABELS[LeadStatus.ACCEPTED], add_in_detail=True, add_in_list=True)
    async def accept(self, request: Request) -> Response:
        return await self._change(request, LeadStatus.ACCEPTED)

    @action(name="on_the_way", label=STATUS_LABELS[LeadStatus.ON_THE_WAY], add_in_detail=True, add_in_list=True)
    async def on_the_way(self, request: Request) -> Response:
        return await self._change(request, LeadStatus.ON_THE_WAY)

    @action(name="in_progress", label=STATUS_LABELS[LeadStatus.IN_PROGRESS], add_in_detail=True, add_in_list=True)
    async def in_progress(self, request: Request) -> Response:
        return await self._change(request, LeadStatus.IN_PROGRESS)

    @action(name="completed", label=STATUS_LABELS[LeadStatus.COMPLETED], add_in_detail=True, add_in_list=True)
    async def completed(self, request: Request) -> Response:
        return await self._change(request, LeadStatus.COMPLETED)

    @action(
        name="cancel", label="Отменить", confirmation_message="Отменить заявку?", add_in_detail=True, add_in_list=True
    )
    async def cancel(self, request: Request) -> Response:
        return await self._change(request, LeadStatus.CANCELLED)


class OperatorAdmin(ModelView, model=Operator):
    """Operators register themselves in the bot (/operator <code>); here you can switch them off or edit names."""

    name, name_plural, icon = "Оператор", "Операторы", "fa-solid fa-headset"
    can_create = False
    column_list: ClassVar[list[Any]] = [
        Operator.name,
        Operator.username,
        Operator.on_shift,
        Operator.is_active,
        Operator.created_at,
    ]
    form_columns: ClassVar[list[Any]] = [Operator.name, Operator.on_shift, Operator.is_active]


class HistoryAdmin(ModelView, model=LeadStatusHistory):
    name, name_plural, icon = "Смена статуса", "История статусов", "fa-solid fa-clock-rotate-left"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[list[Any]] = [
        LeadStatusHistory.lead,
        LeadStatusHistory.from_status,
        LeadStatusHistory.to_status,
        LeadStatusHistory.actor,
        LeadStatusHistory.created_at,
    ]
    column_default_sort: ClassVar[list[Any]] = [(LeadStatusHistory.id, True)]


class _InvalidatesBootstrap(ModelView, _ContainerAware):
    async def after_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        self.container.bootstrap.invalidate()

    async def after_model_delete(self, model: Any, request: Request) -> None:
        self.container.bootstrap.invalidate()


class ServiceAdmin(_InvalidatesBootstrap, model=Service):
    name, name_plural, icon = "Услуга", "Услуги", "fa-solid fa-screwdriver-wrench"
    column_list: ClassVar[list[Any]] = [
        Service.sort_order,
        Service.slug,
        Service.title,
        Service.form_type,
        Service.is_active,
    ]
    column_default_sort: ClassVar[list[Any]] = [(Service.sort_order, False)]


class WorkTypeAdmin(ModelView, model=PriceWorkType):
    name, name_plural, icon = "Тип работ", "Цены: типы работ", "fa-solid fa-ruble-sign"
    column_list: ClassVar[list[Any]] = [
        PriceWorkType.slug,
        PriceWorkType.title,
        PriceWorkType.base_price,
        PriceWorkType.is_onsite_service,
    ]


class BrandAdmin(_InvalidatesBootstrap, model=PriceBrand):
    name, name_plural, icon = "Марка", "Цены: марки", "fa-solid fa-industry"
    column_list: ClassVar[list[Any]] = [PriceBrand.slug, PriceBrand.title, PriceBrand.origin, PriceBrand.coefficient]


class VehicleTypeAdmin(ModelView, model=PriceVehicleType):
    name, name_plural, icon = "Тип техники", "Цены: типы техники", "fa-solid fa-truck-pickup"
    column_list: ClassVar[list[Any]] = [PriceVehicleType.slug, PriceVehicleType.title, PriceVehicleType.coefficient]


class ReviewAdmin(_InvalidatesBootstrap, model=Review):
    name, name_plural, icon = "Отзыв", "Отзывы", "fa-solid fa-star"
    column_list: ClassVar[list[Any]] = [
        Review.author,
        Review.rating,
        Review.source,
        Review.review_date,
        Review.is_published,
        Review.is_demo,
    ]


class CaseAdmin(ModelView, model=Case):
    name, name_plural, icon = "Кейс", "Кейсы до/после", "fa-solid fa-images"
    column_list: ClassVar[list[Any]] = [Case.title, Case.vehicle_brand, Case.completed_on, Case.is_demo]


class CasePhotoAdmin(ModelView, model=CasePhoto):
    name, name_plural, icon = "Фото кейса", "Фото кейсов", "fa-solid fa-image"
    column_list: ClassVar[list[Any]] = [CasePhoto.case, CasePhoto.kind, CasePhoto.caption, CasePhoto.original_key]


class SettingAdmin(_InvalidatesBootstrap, model=Setting):
    name, name_plural, icon = "Настройка", "Настройки сайта", "fa-solid fa-gear"
    can_create = can_delete = False
    column_list: ClassVar[list[Any]] = [Setting.key, Setting.description, Setting.updated_at]
    form_excluded_columns: ClassVar[list[Any]] = [Setting.updated_at]


class OutboxAdmin(ModelView, model=OutboxMessage):
    name, name_plural, icon = "Уведомление", "Очередь уведомлений", "fa-solid fa-paper-plane"
    can_create = can_edit = False
    column_list: ClassVar[list[Any]] = [
        OutboxMessage.id,
        OutboxMessage.kind,
        OutboxMessage.channel,
        OutboxMessage.status,
        OutboxMessage.attempts,
        OutboxMessage.last_error,
        OutboxMessage.created_at,
    ]
    column_default_sort: ClassVar[list[Any]] = [(OutboxMessage.id, True)]


class ChatSessionAdmin(ModelView, model=ChatSession):
    name, name_plural, icon = "Диалог", "Чат: диалоги", "fa-solid fa-comments"
    can_create = can_edit = False
    column_list: ClassVar[list[Any]] = [
        ChatSession.created_at,
        ChatSession.status,
        ChatSession.topic,
        ChatSession.user_message_count,
        ChatSession.lead_id,
    ]
    column_default_sort: ClassVar[list[Any]] = [(ChatSession.created_at, True)]


class ChatMessageAdmin(ModelView, model=ChatMessage):
    name, name_plural, icon = "Сообщение", "Чат: сообщения", "fa-solid fa-message"
    can_create = can_edit = False
    column_list: ClassVar[list[Any]] = [ChatMessage.created_at, ChatMessage.role, ChatMessage.mode, ChatMessage.content]
    column_default_sort: ClassVar[list[Any]] = [(ChatMessage.id, True)]


def setup_admin(app: FastAPI, container: Container) -> Admin:
    token = container.settings.admin_token.get_secret_value() if container.settings.admin_token else None
    admin = Admin(
        app,
        engine=container.engine,
        title="ГРУЗСПЕЦСЕРВИС — операторская",
        authentication_backend=TokenAuth(container.settings.secret_key.get_secret_value(), token),
    )
    _ContainerAware.container = container
    for view in (
        LeadAdmin,
        OperatorAdmin,
        HistoryAdmin,
        ServiceAdmin,
        WorkTypeAdmin,
        BrandAdmin,
        VehicleTypeAdmin,
        ReviewAdmin,
        CaseAdmin,
        CasePhotoAdmin,
        SettingAdmin,
        OutboxAdmin,
        ChatSessionAdmin,
        ChatMessageAdmin,
    ):
        admin.add_view(view)
    return admin
