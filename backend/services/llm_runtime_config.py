"""Immutable per-request LLM execution configuration."""
from dataclasses import dataclass
from typing import Optional, Protocol

from config import settings


class ExecutionConfigLike(Protocol):
    provider: str
    model: str
    provider_id: str
    max_tokens: int


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    api_base: str
    api_key: str
    model: str
    provider_id: str
    temperature: float
    max_tokens: int

    @classmethod
    def current(cls) -> "LLMRuntimeConfig":
        return cls(
            provider=settings.llm.provider,
            api_base=settings.llm.api_base,
            api_key=settings.llm.api_key,
            model=settings.llm.model,
            provider_id=settings.llm.provider_id,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )

    @classmethod
    def from_execution(
        cls,
        execution: Optional[ExecutionConfigLike],
    ) -> "LLMRuntimeConfig":
        current = cls.current()
        if execution is None:
            return current
        return cls(
            provider=execution.provider,
            api_base=current.api_base,
            api_key=current.api_key,
            model=execution.model,
            provider_id=execution.provider_id,
            temperature=current.temperature,
            max_tokens=execution.max_tokens,
        )
