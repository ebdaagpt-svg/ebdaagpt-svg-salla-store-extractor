from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    request_timeout: float = 12
    max_retries: int = 3
    max_concurrent_requests: int = 2
    max_pages: int = 100
    max_sitemap_depth: int = 5
    quick_max_pages: int = 8
    quick_sitemap_depth: int = 2
    quick_products: int = 30
    extraction_timeout_seconds: float = 45
    full_extraction_timeout_seconds: float = 1800
    extraction_batch_size: int = 25
    sitemap_timeout_seconds: float = 15
    request_pacing_min_seconds: float = 0.3
    request_pacing_max_seconds: float = 0.8
    rate_limit_backoff_min_seconds: float = 3
    rate_limit_backoff_max_seconds: float = 5
    user_agent: str = "SallaMigrationExtractor/1.4 (+public-catalog-migration)"
    enable_browser_fallback: bool = False
    enable_scrapling: bool = True
    enable_demo_fallback: bool = True
    session_db_path: str = "data/extractions.sqlite3"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
