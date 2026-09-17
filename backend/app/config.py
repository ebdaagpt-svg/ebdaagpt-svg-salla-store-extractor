from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    request_timeout: float = 12
    max_retries: int = 3
    max_concurrent_requests: int = 2
    max_pages: int = 8
    max_sitemap_depth: int = 2
    max_products: int = 25
    extraction_timeout_seconds: float = 45
    sitemap_timeout_seconds: float = 15
    request_pacing_seconds: float = 0.35
    user_agent: str = "SallaMigrationExtractor/1.0"
    enable_browser_fallback: bool = False
    enable_scrapling: bool = True
    enable_demo_fallback: bool = True
    session_db_path: str = "data/extractions.sqlite3"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
