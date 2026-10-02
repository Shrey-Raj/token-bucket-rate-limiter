from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Rate Limiter Service"
    DEBUG: bool = False
    
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: float = 0.5
    REDIS_CONNECT_TIMEOUT: float = 1.0
    
        
    CB_FAILURE_THRESHOLD: int = 3    
    CB_RECOVERY_TIMEOUT: float = 5.0
    
    DEFAULT_CAPACITY: int = 100
    DEFAULT_REFILL_RATE: float = 10
    
    FAIL_OPEN: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
settings = Settings()