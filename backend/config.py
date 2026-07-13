from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    anthropic_base_url: str = "https://api.anthropic.com"
    google_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    browser_use_api_key: str = ""
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./agentic_web.db"

    class Config:
        env_file = ".env"


settings = Settings()
