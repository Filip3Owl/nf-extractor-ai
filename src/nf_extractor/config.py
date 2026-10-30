"""Application settings, read from environment variables and an optional ``.env`` file."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nf_extractor.extractors.claude import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    Effort,
)


class Settings(BaseSettings):
    """Runtime configuration. See ``.env.example`` for the available variables."""

    model_config = SettingsConfigDict(
        env_prefix="NF_EXTRACTOR_", env_file=".env", extra="ignore", populate_by_name=True
    )

    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    model: str = DEFAULT_MODEL
    effort: Effort = DEFAULT_EFFORT
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, gt=0)
