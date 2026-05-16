"""
CloverDX LLM-based tools module
===============================
Provides LLM-backed helpers over OpenAI-compatible chat endpoints
(e.g. local Ollama):

    validate_CTL(code, input_metadata, output_metadata, query, timeout, temperature)
        Lints CTL2 code and reports issues.

    generate_CTL(description, input_metadata, output_metadata, timeout, temperature)
        Generates CTL code snippets or component transform code.

    suggest_components(task, tool_map, mcp_tool_list)
        Suggests CloverDX components for a task using a static inner LLM agent
        configured via CLOVERDX_SUBAGENT_* settings.

Configuration
-------------
All tuneable knobs are module-level constants below. Edit them directly or
override them from the environment.

Environment variables and defaults:

    CLOVERDX_LLM_API_URL
        Default: http://xenserver-g8.javlin.eu:11434/v1/chat/completions
        Purpose: OpenAI-compatible /chat/completions endpoint used by validate_CTL and generate_CTL.

    CLOVERDX_LLM_MODEL
        Default: Qwen35_CTL:latest
        Purpose: model identifier sent in LLM requests.

    CLOVERDX_LLM_TEMPERATURE
        Default: 0.2 (module-level fallback)
        Purpose: default sampling temperature constant. Note that tool call defaults are:
            validate_CTL temperature default = 0.2
            generate_CTL temperature default = 0.4

    CLOVERDX_LLM_TOP_P
        Default: 0.9
        Purpose: nucleus sampling cutoff.

    CLOVERDX_LLM_ALLOW
        Default: false (via fallback chain)
        Purpose: enable/disable LLM-backed CTL tools.
        Fallback behavior: if unset, LLM_ALLOW is checked; if both are unset, false is used.

    LLM_ALLOW
        Default: false (only used as fallback for CLOVERDX_LLM_ALLOW)
        Purpose: alternate env name for enabling LLM-backed CTL tools.

    CLOVERDX_LOG_PATH
        Default: <project>/logs/ctl_tools.log
        Purpose: path for CTL tool file logging.
        Behavior: set to an empty string to disable CTL tool file logging.

Non-env configurable constants in this module:

    VALIDATE_SYSTEM_PROMPT
        Purpose: system prompt used by validate_CTL.

    VALIDATE_USER_PROMPT_PREPEND
        Purpose: user-message prefix used by validate_CTL.

    GENERATE_SYSTEM_PROMPT
        Purpose: system prompt used by generate_CTL.

    GENERATE_USER_PROMPT_PREPEND
        Purpose: user-message prefix used by generate_CTL.
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Sequence

import requests
from dotenv import load_dotenv
from cloverdx_sub_agent import suggest_etl_components as _suggest_components

logger = logging.getLogger(__name__)

load_dotenv()


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CTL_LOG_PATH = os.path.join(_SCRIPT_DIR, "logs", "ctl_tools.log")
CTL_TOOL_LOG_PATH = os.getenv("CLOVERDX_LOG_PATH", _DEFAULT_CTL_LOG_PATH)
_CTL_FILE_LOG_ENABLED = bool((CTL_TOOL_LOG_PATH or "").strip())
_ctl_tool_logger = logging.getLogger("cloverdx.ctl_tools")
_ctl_tool_logger.propagate = False
_ctl_logger_initialized = False
_active_ctl_tool_name = "unknown"


def _ensure_ctl_file_logger() -> None:
    global _ctl_logger_initialized
    if not _CTL_FILE_LOG_ENABLED or _ctl_logger_initialized:
        return

    log_path = CTL_TOOL_LOG_PATH.strip()
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    abs_log_path = os.path.abspath(log_path)
    for handler in _ctl_tool_logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == abs_log_path:
            _ctl_logger_initialized = True
            return

    file_handler = logging.FileHandler(abs_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s"))
    _ctl_tool_logger.addHandler(file_handler)
    _ctl_tool_logger.setLevel(logging.DEBUG)
    _ctl_logger_initialized = True


def _log_ctl_event(event: str, level: int = logging.DEBUG, **fields) -> None:
    if not _CTL_FILE_LOG_ENABLED:
        return
    _ensure_ctl_file_logger()
    payload = {"event": event, **fields}
    _ctl_tool_logger.log(level, json.dumps(payload, ensure_ascii=True, default=str))


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float in %s=%r; using default %s", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid bool in %s=%r; using default %s", name, raw, default)
    return default

# ── Configuration constants ────────────────────────────────────────────────────
# Ollama default.  Change to your OpenAI or other compatible endpoint as needed.
LLM_API_URL: str = os.getenv(
    "CLOVERDX_LLM_API_URL",
    "http://xenserver-g8.javlin.eu:11434/v1/chat/completions",
)

# Model identifier understood by the endpoint above.
LLM_MODEL: str = os.getenv("CLOVERDX_LLM_MODEL", "Qwen35_CTL:latest")

# Sampling parameters – lower temperature favours deterministic, rule-based output.
LLM_TEMPERATURE: float = _env_float("CLOVERDX_LLM_TEMPERATURE", 0.2)
LLM_TOP_P: float = _env_float("CLOVERDX_LLM_TOP_P", 0.9)
LLM_ALLOW: bool = _env_bool("CLOVERDX_LLM_ALLOW", _env_bool("LLM_ALLOW", False))

VALIDATE_SYSTEM_PROMPT: str = """\
You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean the same language.
Help users write, debug, and explain CTL2 code and related concepts. Provide working code, explanation, or both as needed.
Prefer correct, practical, minimal solutions.

Output format:

ISSUES:
  [severity] Description   (severity is ERROR, WARNING, or INFO)
  ...

SUGGESTIONS:
  - Optional improvement hints (omit section if none)

VERDICT: PASS | FAIL
  (FAIL if any ERROR-severity issue is found; PASS otherwise)

If no issues are found respond with just:
  ISSUES: none
  VERDICT: PASS
"""

VALIDATE_USER_PROMPT_PREPEND: str = """\
Please review the following CloverDX CTL2 code and report any issues:
"""

GENERATE_SYSTEM_PROMPT: str = """\
You are a CloverDX ETL expert specializing in transformation graphs, components, and CTL2. CTL and CTL2 mean the same language.
Help users write, debug, and explain CTL2 code and related concepts. Provide working code, explanation, or both as needed.
Prefer correct, practical, minimal solutions.
"""

GENERATE_USER_PROMPT_PREPEND: str = """\
Generate CloverDX CTL code according to the request:
"""


def _build_port_metadata_section(
    input_metadata: Optional[str] = None,
    output_metadata: Optional[str] = None,
) -> str:
    input_cleaned = (input_metadata or "").strip()
    output_cleaned = (output_metadata or "").strip()
    if not input_cleaned and not output_cleaned:
        return ""
    parts = [
        "## Component Ports Metadata",
        "Interpret the following metadata before reading the CTL2 code or request.",
        "### Input Ports Metadata"
    ]
    if input_cleaned:
        parts.append(input_cleaned)
    else:
        parts.append("No input ports metadata provided.")

    parts.extend(
        [
            "### Output Ports Metadata"
        ]
    )
    if output_cleaned:
        parts.append(output_cleaned)
    else:
        parts.append("No output ports metadata provided.")

    return "\n".join(parts)


# ── Public API ─────────────────────────────────────────────────────────────────

def _call_llm(
    user_message: str,
    system_prompt: str,
    timeout: int,
    temperature: float,
) -> str:
    tool_name = _active_ctl_tool_name
    payload = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "top_p": LLM_TOP_P,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }

    try:
        response = requests.post(
            LLM_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        _log_ctl_event(
            "llm_communication_error",
            level=logging.ERROR,
            tool=tool_name,
            error_type="ConnectionError",
            error=str(exc),
            llm_api_url=LLM_API_URL,
        )
        raise RuntimeError(
            f"Cannot connect to LLM at {LLM_API_URL}. "
            "Ensure Ollama (or another OpenAI-compatible server) is running. "
            f"Detail: {exc}"
        ) from exc
    except requests.exceptions.Timeout:
        _log_ctl_event(
            "llm_communication_error",
            level=logging.ERROR,
            tool=tool_name,
            error_type="Timeout",
            error=f"Request timed out after {timeout}s",
            llm_api_url=LLM_API_URL,
        )
        raise RuntimeError(
            f"LLM request timed out after {timeout}s. "
            "Consider increasing the timeout or using a faster/smaller model."
        )
    except requests.exceptions.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        response_text = response.text[:400] if response is not None else ""
        _log_ctl_event(
            "llm_communication_error",
            level=logging.ERROR,
            tool=tool_name,
            error_type="HTTPError",
            status_code=status_code,
            response_text=response_text,
            llm_api_url=LLM_API_URL,
        )
        raise RuntimeError(
            f"LLM returned HTTP error: {status_code} "
            f"{response_text}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        _log_ctl_event(
            "llm_communication_error",
            level=logging.ERROR,
            tool=tool_name,
            error_type="InvalidJSON",
            response_text=response.text[:1000],
            llm_api_url=LLM_API_URL,
        )
        raise RuntimeError(
            f"LLM returned a non-JSON response: {response.text[:400]}"
        ) from exc

    _log_ctl_event(
        "llm_response",
        tool=tool_name,
        status_code=response.status_code,
        response_json=data,
    )

    try:
        assistant_content = data["choices"][0]["message"]["content"]
        _log_ctl_event(
            "llm_conversation",
            tool=tool_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_content},
            ],
        )
        return assistant_content
    except (KeyError, IndexError) as exc:
        _log_ctl_event(
            "llm_communication_error",
            level=logging.ERROR,
            tool=tool_name,
            error_type="UnexpectedResponseStructure",
            response_json=data,
        )
        raise RuntimeError(
            f"Unexpected LLM response structure: {json.dumps(data)[:500]}"
        ) from exc


def validate_CTL(
    code: str,
    input_metadata: Optional[str] = None,
    output_metadata: Optional[str] = None,
    query: Optional[str] = None,
    timeout: int = 120,
    temperature: float = 0.2,
) -> str:
    """Send CTL2 code to the configured LLM for linting analysis.

    Parameters
    ----------
    code:
        CTL2 transform code to validate (plain text, not XML-escaped).
    input_metadata:
        Optional CloverDX metadata for input ports. Must be in CloverDX XML format:
        one or more ``<Metadata id="..."><Record ...><Field .../></Record></Metadata>``
        blocks, labeled by port role (e.g. ``Port 0 (master): <Metadata ...>``).
        Used only for $in.N field references.
    output_metadata:
        Optional CloverDX metadata for output ports. Must be in CloverDX XML format:
        one or more ``<Metadata id="..."><Record ...><Field .../></Record></Metadata>``
        blocks, labeled by port role (e.g. ``Port 0 (rejected): <Metadata ...>``).
        Used only for $out.N field references.
    query:
        Optional additional instruction or question appended to the user
        message, e.g. "Focus on the replace() calls in the transform function."
    timeout:
        HTTP request timeout in seconds.  Increase for large code blocks or
        slow/remote model endpoints.
    temperature:
        Optional sampling temperature for this validation call.

    Returns
    -------
    str
        Raw LLM response text (structured report as described in the system prompt).

    Raises
    ------
    RuntimeError
        On connection failure, HTTP error, timeout, or unexpected response shape.
    """
    # Build the user message
    parts: list = [VALIDATE_USER_PROMPT_PREPEND.strip()]

    if input_metadata or output_metadata:
        parts.append(
            _build_port_metadata_section(
                input_metadata=input_metadata,
                output_metadata=output_metadata,
            )
        )

    if query:
        parts.append(f"\nAdditional instruction: {query.strip()}")

    parts.append(f"\n\n## CTL2 Code\n```\n{code}\n```")

    user_message = "\n".join(parts)
    llm_payload = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "top_p": LLM_TOP_P,
        "messages": [
            {"role": "system", "content": VALIDATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }

    _log_ctl_event(
        "tool_called",
        tool="validate_CTL",
        timeout_s=timeout,
        temperature=temperature,
        code=code,
        input_metadata=input_metadata,
        output_metadata=output_metadata,
        query=query,
    )
    _log_ctl_event(
        "llm_query",
        tool="validate_CTL",
        query=(query or ""),
        user_message=user_message,
    )
    _log_ctl_event(
        "llm_request",
        tool="validate_CTL",
        llm_api_url=LLM_API_URL,
        timeout_s=timeout,
        temperature=temperature,
        payload=llm_payload,
        system_prompt=VALIDATE_SYSTEM_PROMPT,
        user_message=user_message,
    )

    logger.info(
        "validate_CTL: calling LLM at %s (model=%s, temperature=%s, code_len=%d, input_metadata=%s, output_metadata=%s, query=%s)",
        LLM_API_URL,
        LLM_MODEL,
        temperature,
        len(code),
        "yes" if input_metadata else "no",
        "yes" if output_metadata else "no",
        repr(query[:60]) if query else "none",
    )
    global _active_ctl_tool_name
    previous_tool = _active_ctl_tool_name
    _active_ctl_tool_name = "validate_CTL"
    try:
        return _call_llm(
            user_message=user_message,
            system_prompt=VALIDATE_SYSTEM_PROMPT,
            timeout=timeout,
            temperature=temperature,
        )
    finally:
        _active_ctl_tool_name = previous_tool


def generate_CTL(
    description: str,
    input_metadata: Optional[str] = None,
    output_metadata: Optional[str] = None,
    timeout: int = 120,
    temperature: float = 0.4,
) -> str:
    """Generate CTL2 code from a functional description.

    Parameters
    ----------
    description:
        What to generate: component transform code, an expression snippet,
        or other CTL functionality.
    input_metadata:
        Optional CloverDX metadata for input ports. Must be in CloverDX XML format:
        one or more ``<Metadata id="..."><Record ...><Field .../></Record></Metadata>``
        blocks, labeled by port role (e.g. ``Port 0 (master): <Metadata ...>``).
        Used only for $in.N field references.
    output_metadata:
        Optional CloverDX metadata for output ports. Must be in CloverDX XML format:
        one or more ``<Metadata id="..."><Record ...><Field .../></Record></Metadata>``
        blocks, labeled by port role (e.g. ``Port 0 (rejected): <Metadata ...>``).
        Used only for $out.N field references.
    timeout:
        HTTP request timeout in seconds.
    temperature:
        Optional sampling temperature for this generation call.
    """
    parts: list = [GENERATE_USER_PROMPT_PREPEND.strip()]
    if input_metadata or output_metadata:
        parts.append(
            _build_port_metadata_section(
                input_metadata=input_metadata,
                output_metadata=output_metadata,
            )
        )
    parts.append(f"\nRequest:\n{description.strip()}")

    user_message = "\n".join(parts)
    llm_payload = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "top_p": LLM_TOP_P,
        "messages": [
            {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    }

    _log_ctl_event(
        "tool_called",
        tool="generate_CTL",
        timeout_s=timeout,
        temperature=temperature,
        description=description,
        input_metadata=input_metadata,
        output_metadata=output_metadata,
    )
    _log_ctl_event(
        "llm_query",
        tool="generate_CTL",
        query=description,
        user_message=user_message,
    )
    _log_ctl_event(
        "llm_request",
        tool="generate_CTL",
        llm_api_url=LLM_API_URL,
        timeout_s=timeout,
        temperature=temperature,
        payload=llm_payload,
        system_prompt=GENERATE_SYSTEM_PROMPT,
        user_message=user_message,
    )

    logger.info(
        "generate_CTL: calling LLM at %s (model=%s, temperature=%s, desc_len=%d, input_metadata=%s, output_metadata=%s)",
        LLM_API_URL,
        LLM_MODEL,
        temperature,
        len(description),
        "yes" if input_metadata else "no",
        "yes" if output_metadata else "no",
    )
    global _active_ctl_tool_name
    previous_tool = _active_ctl_tool_name
    _active_ctl_tool_name = "generate_CTL"
    try:
        return _call_llm(
            user_message=user_message,
            system_prompt=GENERATE_SYSTEM_PROMPT,
            timeout=timeout,
            temperature=temperature,
        )
    finally:
        _active_ctl_tool_name = previous_tool


async def suggest_components(
    task: str,
    tool_map: Dict[str, Any],
    mcp_tool_list: Sequence[Any],
) -> str:
    """Suggest CloverDX components relevant for implementing a given task.

    This helper delegates to the static component recommender agent that uses
    CLOVERDX_SUBAGENT_* settings and a fixed read-only tool subset.
    """
    normalized_task = (task or "").strip()
    if not normalized_task:
        raise RuntimeError("'task' is required")

    return await _suggest_components(
        task_description=normalized_task,
        tool_map=tool_map,
        mcp_tool_list=mcp_tool_list,
    )
