from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    request_timeout: float = 12
    max_retries: int = 2
    max_concurrent_requests: int = 5
    max_pages: int = 40
    user_agent: str = "SallaMigrationExtractor/1.0"
    enable_browser_fallback: bool = False
    enable_demo_fallback: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
