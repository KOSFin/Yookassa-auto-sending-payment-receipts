from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'YooKassa Auto Receipt Relay'
    app_env: str = 'production'
    app_debug: bool = False

    database_url: str = 'postgresql+asyncpg://postgres:postgres@postgres:5432/yookassa_auto'
    worker_poll_interval_seconds: int = 5
    run_embedded_worker: bool = False

    webhook_ip_validation: bool = False
    proxy_base_url: str = ''


settings = Settings()
