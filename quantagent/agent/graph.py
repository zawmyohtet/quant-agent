"""Agent graph factory — create_quant_agent()."""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware import SkillsMiddleware
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
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

# Root used by the agent's main FilesystemBackend (its own read/write workspace).
# Skill sources use their own separate, unrestricted backend — see create_quant_agent.
BACKEND_ROOT = Path.home() / ".quantagent"

# Where resolved skill folders are staged for deepagents to scan — see
# _stage_resolved_skills().
_SKILLS_STAGING_DIR = BACKEND_ROOT / ".resolved-skills"


def _stage_resolved_skills(skill_dirs: list[str]) -> Path:
    """Materialize resolved skill directories as symlinks under one staging root.

    deepagents' ``SkillsMiddleware`` expects each ``sources`` entry to be a
    directory *containing* skill subdirectories (each with its own SKILL.md) —
    not an individual skill's own directory. ``SkillResolver.resolve()`` already
    computes the final, precedence-resolved list of *individual* skill folders
    (built-in -> user -> extra, last wins, disabled skills excluded), so handing
    that list straight to ``sources=`` doesn't match deepagents' expected shape:
    deepagents would ``ls()`` each individual skill folder looking for
    sub-subdirectories, find none, and silently report zero skills.

    This stages the already-resolved folders as symlinks under one directory,
    rebuilt on every call, so deepagents can scan it the way it expects without
    reimplementing SkillResolver's merge/filter logic in deepagents-native terms.

    Args:
        skill_dirs: Resolved, precedence-ordered individual skill directory
            paths (``ResolvedSkills.skill_dirs``).

    Returns:
        Path to the staging directory, ready to pass as a single ``sources``
        entry to ``SkillsMiddleware``.
    """
    if _SKILLS_STAGING_DIR.exists():
        shutil.rmtree(_SKILLS_STAGING_DIR)
    _SKILLS_STAGING_DIR.mkdir(parents=True, exist_ok=True)

    for skill_dir in skill_dirs:
        source = Path(skill_dir)
        (_SKILLS_STAGING_DIR / source.name).symlink_to(source, target_is_directory=True)

    return _SKILLS_STAGING_DIR


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

    # Main backend for the agent's own file tools, sandboxed under BACKEND_ROOT.
    # virtual_mode=False is explicit and deliberate — deepagents' own reference CLI
    # (deepagents-code) uses the same setting for its main working-directory backend;
    # virtual_mode is intended for virtual path semantics (e.g. CompositeBackend), not
    # as a sandbox for a trusted local-dev tool like this one.
    backend = FilesystemBackend(root_dir=str(BACKEND_ROOT), virtual_mode=False)

    # Skills get a dedicated, separate backend instance rather than sharing `backend`
    # (mirrors deepagents-code's PluginSkillsMiddleware wiring). Skill sources are
    # absolute paths from unrelated roots (built-in package dir, ~/.quantagent/skills,
    # extra dirs) — a different trust model from the agent's own writable workspace,
    # so they shouldn't be constrained by the main backend's root_dir/virtual_mode.
    skills_root = _stage_resolved_skills(resolved.skill_dirs)
    skills_middleware = SkillsMiddleware(
        backend=FilesystemBackend(virtual_mode=False),
        sources=[str(skills_root)],
    )

    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        TodoListMiddleware(),  # not auto-injected by create_deep_agent since 0.7.0
        skills_middleware,
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
        checkpointer=checkpointer,
        middleware=middleware,
    )
