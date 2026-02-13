from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RelayMode(StrEnum):
    FIRE_AND_FORGET = 'fire_and_forget'
    RETRY_UNTIL_200 = 'retry_until_200'


class MyTaxProvider(StrEnum):
    OFFICIAL_API = 'official_api'
    UNOFFICIAL_API = 'unofficial_api'


class TaskType(StrEnum):
    CREATE_RECEIPT = 'create_receipt'
    CANCEL_RECEIPT = 'cancel_receipt'


class TaskStatus(StrEnum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    FAILED = 'failed'
    WAITING_AUTH = 'waiting_auth'


class EventStatus(StrEnum):
    RECEIVED = 'received'
    PROCESSED = 'processed'
    FAILED = 'failed'


class ReceiptStatus(StrEnum):
    CREATED = 'created'
    CANCELED = 'canceled'


class Store(Base):
    __tablename__ = 'stores'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    webhook_path: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    description_template: Mapped[str] = mapped_column(String(512), default='Оплата заказа {{payment_id}}')
    item_name_template: Mapped[str] = mapped_column(String(512), default='Услуга {{payment_id}}')
    amount_path: Mapped[str] = mapped_column(String(255), default='object.amount.value')
    payment_id_path: Mapped[str] = mapped_column(String(255), default='object.id')
    customer_name_path: Mapped[str] = mapped_column(String(255), default='object.metadata.customer_name')

    relay_mode: Mapped[RelayMode] = mapped_column(Enum(RelayMode), default=RelayMode.RETRY_UNTIL_200)
    relay_retry_limit: Mapped[int] = mapped_column(Integer, default=5)
    include_receipt_url_in_relay: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_cancel_on_refund: Mapped[bool] = mapped_column(Boolean, default=True)

    mytax_profile_id: Mapped[int | None] = mapped_column(ForeignKey('mytax_profiles.id'), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    mytax_profile = relationship('MyTaxProfile', back_populates='stores')
    relay_targets = relationship('RelayTarget', back_populates='store', cascade='all, delete-orphan')
    telegram_channels = relationship('TelegramChannel', back_populates='store', cascade='all, delete-orphan')


class MyTaxProfile(Base):
    __tablename__ = 'mytax_profiles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[MyTaxProvider] = mapped_column(Enum(MyTaxProvider), default=MyTaxProvider.UNOFFICIAL_API)
    inn: Mapped[str] = mapped_column(String(12), nullable=True)
    password: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), nullable=True)

    access_token: Mapped[str] = mapped_column(Text, default='')
    refresh_token: Mapped[str] = mapped_column(Text, default='')
    cookie_blob: Mapped[str] = mapped_column(Text, default='')
    device_id: Mapped[str] = mapped_column(String(128), default='')

    is_authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error: Mapped[str] = mapped_column(Text, default='')
    last_auth_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stores = relationship('Store', back_populates='mytax_profile')


class RelayTarget(Base):
    __tablename__ = 'relay_targets'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    method: Mapped[str] = mapped_column(String(16), default='POST')
    headers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_template: Mapped[str] = mapped_column(Text, default='')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    store = relationship('Store', back_populates='relay_targets')


class TelegramChannel(Base):
    __tablename__ = 'telegram_channels'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    bot_token: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    include_receipt_url: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    store = relationship('Store', back_populates='telegram_channels')


class PaymentEvent(Base):
    __tablename__ = 'payment_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.RECEIVED)
    relay_status: Mapped[str] = mapped_column(String(64), default='pending')
    error_message: Mapped[str] = mapped_column(Text, default='')

    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReceiptTask(Base):
    __tablename__ = 'receipt_tasks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey('payment_events.id'), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=20)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    error_message: Mapped[str] = mapped_column(Text, default='')

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Receipt(Base):
    __tablename__ = 'receipts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey('stores.id'), nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey('receipt_tasks.id'), nullable=False)
    payment_id: Mapped[str] = mapped_column(String(128), nullable=False)

    receipt_uuid: Mapped[str] = mapped_column(String(255), default='')
    receipt_url: Mapped[str] = mapped_column(String(512), default='')
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(3), default='RUB')
    description: Mapped[str] = mapped_column(String(512), default='')

    status: Mapped[ReceiptStatus] = mapped_column(Enum(ReceiptStatus), default=ReceiptStatus.CREATED)
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppLog(Base):
    __tablename__ = 'app_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey('stores.id'), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default='info')
    event: Mapped[str] = mapped_column(String(128), default='')
    message: Mapped[str] = mapped_column(Text, default='')
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
