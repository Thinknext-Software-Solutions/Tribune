"""Shared fixtures + a FakeLLM that emits deterministic structured output."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from tribune.llm import LLMClient, LLMResponse, LLMUsage


class FakeLLM(LLMClient):
    """In-memory LLM client that returns a queue of pre-built parsed objects."""

    provider_name = "fake"
    model = "fake"

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)

    def structured_call(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
    ) -> LLMResponse:
        if not self._responses:
            raise AssertionError(
                f"FakeLLM exhausted; got call for schema={schema.__name__}"
            )
        parsed = self._responses.pop(0)
        if not isinstance(parsed, schema):
            raise AssertionError(
                f"FakeLLM next response type {type(parsed).__name__} != requested schema {schema.__name__}"
            )
        return LLMResponse(
            parsed=parsed,
            raw_text="(fake)",
            usage=LLMUsage.build(
                input_tokens=10,
                output_tokens=10,
                model=self.model,
                provider=self.provider_name,
            ),
        )


@pytest.fixture
def fake_llm():
    """Provide a constructor so each test seeds its own responses."""
    return FakeLLM
