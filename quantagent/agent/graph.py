"""Agent graph factory — create_quant_agent()."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.chat_models import init_chat_model

from quantagent.agent.middleware.approval import ApprovalMiddleware
from quantagent.agent.middleware.error_logging import ErrorLoggingMiddleware
from quantagent.agent.middleware.progress import ToolProgressMiddleware
from quantagent.agent.middleware.summarization import SummarizationMiddleware
from quantagent.agent.prompts import BASE_SYSTEM_PROMPT
from quantagent.agent.skills import SkillResolver
from quantagent.agent.tools_registry import build_tool_registry
from quantagent.tui.config import QuantAgentConfig

logger = logging.getLogger(__name__)

# Root used by FilesystemBackend — skills paths are resolved relative to this
BACKEND_ROOT = Path.home() / ".quantagent"


def _parse_model_string(model: str) -> tuple[str, str | None]:
    """Parse 'provider:model_name' into (model_name, provider).

    Examples:
        anthropic:claude-sonnet-4-6 -> ("claude-sonnet-4-6", "anthropic")
        openai:gpt-4o -> ("gpt-4o", "openai")
        openrouter:anthropic/claude-sonnet-4-6 -> ("anthropic/claude-sonnet-4-6", "openrouter")
        gpt-4o -> ("gpt-4o", None)
    """
    if ":" in model:
        provider, name = model.split(":", 1)
        return name, provider
    return model, None


def _create_chat_model(config: QuantAgentConfig) -> Any:
    """Create a chat model from a ``provider:model`` string.

    ``zai`` and ``opencode`` are OpenAI-compatible gateways reached through
    langchain-openai with a custom base_url — not native langchain providers.
    """
    model_name, model_provider = _parse_model_string(config.model)

    openai_compatible_gateways = {
        "zai": (config.zai_api_key, config.zai_api_base),
        "opencode": (config.opencode_api_key, config.opencode_api_base),
    }
    if model_provider in openai_compatible_gateways:
        api_key, base_url = openai_compatible_gateways[model_provider]
        return init_chat_model(
            model=model_name,
            model_provider="openai",
            api_key=api_key,
            base_url=base_url,
        )

    return init_chat_model(model_name, model_provider=model_provider)


def create_quant_agent(
    config: QuantAgentConfig,
    checkpointer: Any,
    approval_callback: Callable | None = None,
) -> Any:
    """Build and return a compiled LangGraph agent configured for quant analysis.

    Skills are loaded from disk via FilesystemBackend using progressive disclosure:
    the agent reads each SKILL.md's description at startup and fetches the full
    file on demand when a user prompt matches. No skills content is pre-loaded
    into the system prompt — the agent decides what to read based on the task.

    Skill source precedence (last wins for same-named skills):
      1. Built-in skills  (<package>/skills/)
      2. User skills      (~/.quantagent/skills/)
      3. Extra dirs       (config.extra_skill_dirs)
    """
    model = _create_chat_model(config)

    tools = build_tool_registry(config)

    resolver = SkillResolver(
        extra_skill_dirs=[Path(d) for d in getattr(config, "extra_skill_dirs", [])],
        disabled_skills=getattr(config, "disabled_skills", []),
    )
    resolved = resolver.resolve()

    # FilesystemBackend makes skill files accessible to the agent as readable paths.
    backend = FilesystemBackend(root_dir=str(BACKEND_ROOT))

    middleware = [
        ErrorLoggingMiddleware(),
        ToolProgressMiddleware(),
        SummarizationMiddleware(token_threshold=80_000, model=model),
    ]

    if config.approval_required:
        middleware.append(
            ApprovalMiddleware(
                tools_requiring_approval=config.approval_required,
                approval_callback=approval_callback,
            )
        )

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=BASE_SYSTEM_PROMPT,
        backend=backend,
        skills=resolved.skill_dirs,   # ordered list — last wins for same name
        checkpointer=checkpointer,
        middleware=middleware,
    )
