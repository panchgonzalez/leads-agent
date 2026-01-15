from __future__ import annotations

from functools import lru_cache
from typing import Callable

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from .config import Settings
from .models import LeadClassification

SYSTEM_PROMPT = """\
You classify inbound leads from a consulting company contact form.

Definitions:
- spam: irrelevant, automated, SEO, crypto, junk
- solicitation: vendors, sales pitches, recruiters, partnerships
- promising: genuine inquiry about services or collaboration

Rules:
- Be conservative
- If unclear, choose spam
- Provide a short reason
"""


@lru_cache(maxsize=8)
def agent_factory(
    llm_base_url: str, llm_model_name: str, instructions: str = SYSTEM_PROMPT, extra_tools: list[Callable] | None = None
) -> Agent[None, LeadClassification]:
    provider = OpenAIProvider(base_url=llm_base_url, api_key="local")
    model = OpenAIChatModel(model_name=llm_model_name, provider=provider)

    tools = [] + (extra_tools or [])

    return Agent(
        model=model,
        output_type=LeadClassification,
        instructions=instructions,
        retries=2,
        end_strategy="early",
        model_settings=OpenAIChatModelSettings(temperature=0.0, max_tokens=5000),
        tools=tools,
    )


def classify_message(settings: Settings, text: str) -> LeadClassification:
    agent = agent_factory(settings.llm_base_url, settings.llm_model_name)
    result = agent.run_sync(text)
    return result.data
