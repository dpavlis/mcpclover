"""
CloverDX sub-agent helpers
==========================
Provides LLM-backed helper functions over an OpenAI-compatible chat endpoint:

    run_sub_agent(...)
        Runs a generic sub-agent that can call only a restricted MCP tool subset.

    recommend_ctl_components(...)
        Runs a focused recommender agent for CTL implementation planning.
        The internal agent can call only a fixed discovery subset of tools.

Configuration
-------------
All tunable knobs are module-level constants below. Edit directly or override
from environment:

    CLOVERDX_SUBAGENT_API_URL
    CLOVERDX_SUBAGENT_MODEL
    CLOVERDX_SUBAGENT_API_KEY
    CLOVERDX_SUBAGENT_TEMPERATURE
    CLOVERDX_SUBAGENT_MAX_TOKENS
    CLOVERDX_SUBAGENT_TIMEOUT
"""

import asyncio
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float in %s=%r; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int in %s=%r; using default %s", name, raw, default)
        return default


SUBAGENT_API_URL: str = os.getenv(
    "CLOVERDX_SUBAGENT_API_URL",
    "http://localhost:11434/v1/chat/completions",
)
SUBAGENT_MODEL: str = os.getenv("CLOVERDX_SUBAGENT_MODEL", "gpt-5.4")
SUBAGENT_API_KEY: str = os.getenv("CLOVERDX_SUBAGENT_API_KEY", "")
SUBAGENT_TEMPERATURE: float = _env_float("CLOVERDX_SUBAGENT_TEMPERATURE", 0.2)
SUBAGENT_MAX_TOKENS: int = _env_int("CLOVERDX_SUBAGENT_MAX_TOKENS", 32768)
SUBAGENT_TIMEOUT: int = _env_int("CLOVERDX_SUBAGENT_TIMEOUT", 240)

# The generic sub-agent can only use a restricted allowlist of tools.
READ_ONLY_SUBAGENT_TOOLS: frozenset[str] = frozenset(
    {
        "list_sandboxes",
        "list_files",
        "find_file",
        "grep_files",
        "list_linked_assets",
        "get_sandbox_parameters",
        "read_file",
        "list_resources",
        "read_resource",
        "get_workflow_guide",
        "validate_graph",
        "execute_graph",
        "await_graph_completion",
        "abort_graph_execution",
        "list_graph_runs",
        "get_graph_run_status",
        "get_graph_execution_log",
        "get_graph_tracking",
        "get_edge_debug_data",
        "list_components",
        "get_component_info",
        "get_component_details",
        "note_add",
        "note_read",
        "note_clear",
        "kb_search",
        "kb_read",
    }
)

# Fixed subset for component recommendation helper.
COMPONENT_RECOMMENDER_TOOLS: frozenset[str] = frozenset(
    {
        "list_components",
        "get_component_info",
        "get_component_details",
        "list_resources",
        "read_resource",
        "kb_search",
        "kb_read",
    }
)

_ALWAYS_EXCLUDED: frozenset[str] = frozenset(
    {
        "run_sub_agent",
        "validate_CTL",
        "generate_CTL",
        "recommend_ctl_components",
        "suggest_components",
    }
)

_DEFAULT_SUBAGENT_SYSTEM_PROMPT = """You are a focused CloverDX assistant running as a sub-agent.
Use tools when needed, but keep calls minimal and grounded in returned data.
You can only use the allowed tool subset; if a requested tool is unavailable, continue with the allowed subset.
Return a concise, actionable final answer.
"""

_COMPONENT_RECOMMENDER_SYSTEM_PROMPT = """CloverDX component advisor. Recommend components for a data processing task.
Caller is an LLM building graphs. Thoroughness over speed — your recommendations
directly determine component selection. Output JSON only.

PROTOCOL (mandatory, sequential, never skip steps):

1. KB FIRST: kb_search() → scan catalog → kb_read(name) for relevant entries.
   KB entries contain hard-won insights: component gotchas, configuration patterns,
   corrections to wrong assumptions. KB findings take priority over general knowledge.
   If KB warns about a component you plan to recommend, surface it in kb_insights.

2. RESOURCES: list_resources() → read_resource() for relevant references
   (CTL2 ref, graph XML ref, component-specific docs when available).

3. FULL CATALOG SCAN: list_components() with NO args first — see ALL components
   before narrowing. Many tasks have a specialized component far better than the
   obvious generic choice (REFORMAT). Then targeted searches:
   list_components(search_string="<task keywords>") or by category.

4. RESEARCH EVERY CANDIDATE:
   a) get_component_info(type) for each — ports, properties, usage.
   b) get_component_details(type) for complex ones: those with [attr-cdata] XML
      properties, multiple interacting attributes, or opaque labels like
      [validatorRules], [xmlMapping], [httpConnectorInputMapping].
   c) Compare candidates against task requirements using gathered facts, not assumptions.
   Never guess port names, attribute names, or CTL signatures — get them from tools.

5. Synthesize into JSON response. Never recommend unverified components.

SELECTION RULES:
- Prefer most specialized component over REFORMAT:
  AGGREGATE>REFORMAT for aggregation; NORMALIZER>REFORMAT for 1→N; DEDUP for dedup;
  VALIDATOR for declarative validation; REST_CONNECTOR>HTTP_CONNECTOR for REST APIs;
  DATA_INTERSECTION for set comparison/SCD
- Sorted-input components: MERGE, DEDUP, EXT_MERGE_JOIN, DENORMALIZER,
  DATA_INTERSECTION — include upstream FAST_SORT in prerequisites
- Non-existent: no ROUTER(→PARTITION), no FILTER(→EXT_FILTER), no SORT(→FAST_SORT/EXT_SORT)
- Present ≥2 options when alternatives exist — caller has more task context and
  may choose the non-primary option for valid reasons
- Ambiguous task: state your interpretation in pattern_notes, recommend for most likely case
- No suitable component for part of the task: say so in pattern_notes, do not force a bad fit

OUTPUT (valid JSON, nothing else):
{"recommendations":[{"component":"TYPE","rank":1,"why":"one sentence","characteristics":["relevant point"],"configuration_notes":["attr names from get_component_info"],"prerequisites":["e.g. FAST_SORT upstream"],"considerations":["risk/constraint"],"ctl_entry_points":["e.g. function integer transform()"],"ports":{"input":"0: desc","output":"0: desc, 1: desc"}}],"alternatives_considered":[{"component":"TYPE","why_not":"reason"}],"kb_insights":[{"entry_name":"name","summary":"insight","relevance":"how it applies"}],"pattern_notes":["graph flow pattern if applicable"]}

FIELD RULES:
- recommendations: 1-3, ordered by rank (1=best fit)
- characteristics: 2-4 points from get_component_info/get_component_details
- configuration_notes: actual attribute names from tool output, not guesses
- ctl_entry_points: exact signatures; omit for attribute-only components (AGGREGATE, DEDUP)
- prerequisites/considerations: omit arrays if empty
- kb_insights: include entry_name so caller can kb_read(); always include KB warnings
  about recommended components; omit section if nothing found
- alternatives_considered: show rejected candidates with brief reason
- pattern_notes: typical graph flow; include task interpretation if ambiguous; omit if n/a
- Keep all fields concise. No filler.
"""


ToolHandler = Callable[[Dict[str, Any]], Awaitable[List[Any]]]


def _mcp_to_openai_tools(mcp_tool_list: Sequence[Any], allowed_names: Set[str]) -> List[Dict[str, Any]]:
    openai_tools: List[Dict[str, Any]] = []
    for tool in mcp_tool_list:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name or name not in allowed_names:
            continue
        description = str(getattr(tool, "description", "") or "")
        input_schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": input_schema,
                },
            }
        )
    return openai_tools


def _text_parts_from_tool_result(result_items: List[Any]) -> str:
    parts: List[str] = []
    for item in result_items:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
    return "\n".join(parts).strip()


async def _dispatch_tool(
    tool_map: Dict[str, ToolHandler],
    allowed_names: Set[str],
    name: str,
    args: Dict[str, Any],
) -> str:
    if name not in allowed_names:
        return f"ERROR: tool '{name}' is not allowed for this sub-agent"

    handler = tool_map.get(name)
    if handler is None:
        return f"ERROR: tool '{name}' is not available"

    try:
        result_items = await handler(args)
        payload = _text_parts_from_tool_result(result_items)
        return payload or ""
    except Exception as exc:
        logger.exception("Sub-agent tool dispatch failed: %s", name)
        return f"ERROR: {exc}"


def _post_chat_completion(payload: Dict[str, Any], timeout_s: int) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if SUBAGENT_API_KEY.strip():
        headers["Authorization"] = f"Bearer {SUBAGENT_API_KEY.strip()}"

    return requests.post(
        SUBAGENT_API_URL,
        json=payload,
        headers=headers,
        timeout=timeout_s,
    )


def _parse_tool_args(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        raw = raw_args.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {"_parse_error": f"Invalid JSON arguments: {exc}"}
        if isinstance(parsed, dict):
            return parsed
        return {"_parse_error": "Tool arguments must decode to a JSON object."}
    return {"_parse_error": "Unsupported tool arguments format."}


async def _run_llm_tool_loop(
    *,
    task: str,
    tool_map: Dict[str, ToolHandler],
    mcp_tool_list: Sequence[Any],
    allowed_tool_names: Iterable[str],
    denied_tool_names: Optional[Iterable[str]],
    system_prompt: str,
    max_iterations: int,
    context: Optional[str],
    timeout: Optional[int],
) -> str:
    denied_set = {str(name).strip() for name in (denied_tool_names or []) if str(name).strip()}
    allowed_set = {
        name
        for name in allowed_tool_names
        if name not in _ALWAYS_EXCLUDED and name not in denied_set
    }
    openai_tools = _mcp_to_openai_tools(mcp_tool_list, allowed_set)

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if context and context.strip():
        messages.append({"role": "user", "content": f"Context:\n{context.strip()}"})
    messages.append({"role": "user", "content": task})

    timeout_s = int(timeout or SUBAGENT_TIMEOUT)
    last_content = ""

    for _ in range(max(1, int(max_iterations))):
        payload: Dict[str, Any] = {
            "model": SUBAGENT_MODEL,
            "temperature": SUBAGENT_TEMPERATURE,
            "max_completion_tokens": SUBAGENT_MAX_TOKENS,
            "messages": messages,
            "tools": openai_tools,
            "tool_choice": "auto",
        }

        try:
            response = await asyncio.to_thread(_post_chat_completion, payload, timeout_s)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            return f"ERROR: Sub-agent LLM request timed out after {timeout_s}s"
        except requests.exceptions.ConnectionError as exc:
            return f"ERROR: Cannot connect to sub-agent LLM at {SUBAGENT_API_URL}: {exc}"
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            body = exc.response.text[:400] if exc.response is not None else ""
            return f"ERROR: Sub-agent LLM HTTP error {status}: {body}"
        except Exception as exc:
            return f"ERROR: Sub-agent LLM call failed: {exc}"

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
        except Exception as exc:
            return f"ERROR: Unexpected sub-agent LLM response: {exc}"

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            last_content = content.strip()

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return last_content or ""

        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )

        for call in tool_calls:
            call_id = str(call.get("id") or "")
            fn = call.get("function") or {}
            tool_name = str(fn.get("name") or "")
            tool_args = _parse_tool_args(fn.get("arguments"))

            if "_parse_error" in tool_args:
                tool_result = f"ERROR: {tool_args['_parse_error']}"
            else:
                tool_result = await _dispatch_tool(tool_map, allowed_set, tool_name, tool_args)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": tool_result,
                }
            )

    if last_content:
        return f"MAX ITERATIONS REACHED: {last_content}"
    return "MAX ITERATIONS REACHED"


async def run_sub_agent(
    *,
    task: str,
    tool_map: Dict[str, ToolHandler],
    mcp_tool_list: Sequence[Any],
    allowed_tools: Optional[Sequence[str]] = None,
    system_prompt: Optional[str] = None,
    max_iterations: int = 10,
    context: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    requested = set(str(name).strip() for name in (allowed_tools or []) if str(name).strip())
    if requested:
        effective = requested.intersection(READ_ONLY_SUBAGENT_TOOLS)
    else:
        effective = set(READ_ONLY_SUBAGENT_TOOLS)

    return await _run_llm_tool_loop(
        task=task,
        tool_map=tool_map,
        mcp_tool_list=mcp_tool_list,
        allowed_tool_names=effective,
        denied_tool_names={"run_sub_agent"},
        system_prompt=(system_prompt or _DEFAULT_SUBAGENT_SYSTEM_PROMPT).strip(),
        max_iterations=max_iterations,
        context=context,
        timeout=timeout,
    )


async def suggest_etl_components(
    *,
    task_description: str,
    tool_map: Dict[str, ToolHandler],
    mcp_tool_list: Sequence[Any],
    max_iterations: int = 8,
    context: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    return await _run_llm_tool_loop(
        task=task_description,
        tool_map=tool_map,
        mcp_tool_list=mcp_tool_list,
        allowed_tool_names=COMPONENT_RECOMMENDER_TOOLS,
        denied_tool_names={"suggest_etl_components", "run_sub_agent"},
        system_prompt=_COMPONENT_RECOMMENDER_SYSTEM_PROMPT.strip(),
        max_iterations=max_iterations,
        context=context,
        timeout=timeout,
    )
