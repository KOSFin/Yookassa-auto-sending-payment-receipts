from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'YooKassa Auto Receipt Relay'
    app_env: str = 'production'
    app_debug: bool = False

    database_url: str = 'postgresql+asyncpg://postgres:postgres@postgres:5432/yookassa_auto'
    worker_poll_interval_seconds: int = 15
    run_embedded_worker: bool = False
    
    task_retry_base_seconds: int = 60
    task_retry_max_seconds: int = 1800
    task_retry_exponential_multiplier: int = 2
    telegram_retry_notification_interval: int = 5

    panel_login: str = ''
    panel_password: str = ''
    panel_auth_cookie_name: str = 'yk_panel_session'
    panel_auth_token_ttl_seconds: int = 86400
    panel_auth_secret: str = ''
    panel_auth_cookie_secure: bool = False

    webhook_antifraud_enabled: bool = False
    webhook_ip_validation: bool = False
    yookassa_shop_id: str = ''
    yookassa_secret_key: str = ''
    proxy_base_url: str = ''


settings = Settings()
