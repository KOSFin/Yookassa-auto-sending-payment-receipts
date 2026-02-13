from datetime import datetime

from pydantic import BaseModel, Field

from app.models import MyTaxProvider, RelayMode, TaskStatus


class StoreBase(BaseModel):
    name: str
    webhook_path: str
    is_active: bool = True
    description_template: str = 'Оплата заказа {{payment_id}}'
    item_name_template: str = 'Услуга {{payment_id}}'
    amount_path: str = 'object.amount.value'
    payment_id_path: str = 'object.id'
    customer_name_path: str = 'object.metadata.customer_name'
    relay_mode: RelayMode = RelayMode.RETRY_UNTIL_200
    relay_retry_limit: int = 5
    include_receipt_url_in_relay: bool = False
    auto_cancel_on_refund: bool = True
    mytax_profile_id: int | None = None


class StoreCreate(StoreBase):
    pass


class StoreUpdate(StoreBase):
    pass


class StoreOut(StoreBase):
    id: int

    class Config:
        from_attributes = True


class MyTaxProfileBase(BaseModel):
    name: str
    provider: MyTaxProvider = MyTaxProvider.UNOFFICIAL_API
    inn: str | None = None
    password: str | None = None
    phone: str | None = None
    device_id: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    cookie_blob: str | None = None


class MyTaxProfileCreate(MyTaxProfileBase):
    pass


class MyTaxProfileOut(BaseModel):
    id: int
    name: str
    provider: MyTaxProvider
    inn: str | None = None
    phone: str | None = None
    is_authenticated: bool
    last_error: str
    last_auth_at: datetime | None = None

    class Config:
        from_attributes = True


class RelayTargetBase(BaseModel):
    store_id: int
    name: str
    url: str
    method: str = 'POST'
    headers_json: dict = Field(default_factory=dict)
    payload_template: str = ''
    is_active: bool = True


class RelayTargetCreate(RelayTargetBase):
    pass


class RelayTargetOut(RelayTargetBase):
    id: int

    class Config:
        from_attributes = True


class TelegramChannelBase(BaseModel):
    store_id: int
    name: str
    bot_token: str
    chat_id: str
    topic_id: int | None = None
    events_json: list[str] = Field(default_factory=list)
    include_receipt_url: bool = True
    is_active: bool = True


class TelegramChannelCreate(TelegramChannelBase):
    pass


class TelegramChannelOut(TelegramChannelBase):
    id: int

    class Config:
        from_attributes = True


class PaymentEventOut(BaseModel):
    id: int
    store_id: int
    event_type: str
    payment_id: str
    status: str
    relay_status: str
    error_message: str
    received_at: datetime
    processed_at: datetime | None

    class Config:
        from_attributes = True


class ReceiptTaskOut(BaseModel):
    id: int
    store_id: int
    event_id: int
    payment_id: str
    task_type: str
    status: TaskStatus
    attempts: int
    max_attempts: int
    next_retry_at: datetime
    error_message: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReceiptOut(BaseModel):
    id: int
    store_id: int
    payment_id: str
    receipt_uuid: str
    receipt_url: str
    amount: float
    currency: str
    description: str
    status: str
    created_at: datetime
    canceled_at: datetime | None

    class Config:
        from_attributes = True


class QueueRetryIn(BaseModel):
    task_id: int


class LoginProfileIn(BaseModel):
    force: bool = False


class StatsOut(BaseModel):
    total_events: int
    success_tasks: int
    failed_tasks: int
    waiting_auth_tasks: int
    pending_tasks: int
    total_receipts: int


class AppLogOut(BaseModel):
    id: int
    store_id: int | None
    level: str
    event: str
    message: str
    context: dict
    created_at: datetime

    class Config:
        from_attributes = True
