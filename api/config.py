"""
Configuration management for FastAPI service.

Uses Pydantic BaseSettings to read environment variables with type validation
and default values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field

# Import BaseSettings - try pydantic-settings first (Pydantic v2), then fallback
try:
    from pydantic_settings import BaseSettings
except ImportError:
    # For Pydantic v1 or if pydantic-settings not installed
    # Check if BaseSettings exists in pydantic (v1) or needs fallback
    try:
        import pydantic
        # In Pydantic v2, BaseSettings was moved, so this will fail
        # Try to detect version
        if hasattr(pydantic, 'BaseSettings'):
            from pydantic import BaseSettings
        else:
            raise ImportError("BaseSettings not in pydantic")
    except (ImportError, AttributeError):
        # Fallback: create a simple BaseSettings-like class
        from pydantic import BaseModel
        import os
        from typing import Any
        
        class BaseSettings(BaseModel):
            """Fallback BaseSettings for environments without pydantic-settings."""
            class Config:
                env_file = ".env"
                env_file_encoding = "utf-8"
                case_sensitive = False
                extra = "ignore"
            
            def __init__(self, **kwargs: Any):
                # Load from environment variables
                for field_name, field_info in self.__fields__.items():
                    env_name = field_info.field_info.extra.get('env', field_name.upper())
                    if field_name not in kwargs:
                        env_value = os.getenv(env_name)
                        if env_value is not None:
                            kwargs[field_name] = env_value
                super().__init__(**kwargs)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden via environment variables or .env file.
    """

    # Ollama configuration
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama API host URL",
        env="OLLAMA_HOST",
    )
    ollama_model: str = Field(
        default="llama3",
        description="Default Ollama model name",
        env="OLLAMA_MODEL",
    )

    # Directory configuration
    runs_dir: str = Field(
        default="runs",
        description="Directory for storing job records (JobStore)",
        env="RUNS_DIR",
    )
    logs_dir: Optional[str] = Field(
        default=None,
        description="Directory for log files (optional, defaults to current directory)",
        env="LOGS_DIR",
    )
    chroma_dir: Optional[str] = Field(
        default=None,
        description="Directory for ChromaDB vector store (optional, defaults to output/indexes)",
        env="CHROMA_DIR",
    )

    # API configuration
    api_host: str = Field(
        default="0.0.0.0",
        description="API server host",
        env="API_HOST",
    )
    api_port: int = Field(
        default=8000,
        description="API server port",
        env="API_PORT",
    )

    # Timeout configuration
    ollama_timeout_sec: int = Field(
        default=60,
        description="Timeout for Ollama HTTP requests in seconds",
        env="OLLAMA_TIMEOUT_SEC",
    )
    embeddings_timeout_sec: int = Field(
        default=120,
        description="Timeout for embedding generation in seconds",
        env="EMBEDDINGS_TIMEOUT_SEC",
    )
    pipeline_max_runtime_sec: int = Field(
        default=600,
        description="Maximum runtime for entire pipeline in seconds (10 minutes)",
        env="PIPELINE_MAX_RUNTIME_SEC",
    )

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()


def get_runs_dir() -> str:
    """
    Get runs directory path, creating it if needed.

    Returns:
        Absolute path to runs directory.
    """
    runs_path = Path(settings.runs_dir).resolve()
    runs_path.mkdir(parents=True, exist_ok=True)
    return str(runs_path)


def get_logs_dir() -> Optional[str]:
    """
    Get logs directory path if configured.

    Returns:
        Absolute path to logs directory, or None if not configured.
    """
    if settings.logs_dir:
        logs_path = Path(settings.logs_dir).resolve()
        logs_path.mkdir(parents=True, exist_ok=True)
        return str(logs_path)
    return None


def get_chroma_dir() -> Optional[str]:
    """
    Get ChromaDB directory path if configured.

    Returns:
        Absolute path to ChromaDB directory, or None if not configured.
    """
    if settings.chroma_dir:
        chroma_path = Path(settings.chroma_dir).resolve()
        chroma_path.mkdir(parents=True, exist_ok=True)
        return str(chroma_path)
    return None
