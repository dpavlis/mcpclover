"""
CloverDX CTL helper module
==========================
Provides two LLM-backed helpers over an OpenAI-compatible chat endpoint
(e.g. local Ollama):

    validate_CTL(code, input_metadata, output_metadata, query, timeout)
        Lints CTL2 code and reports issues.

    generate_CTL(description, input_metadata, output_metadata, timeout)
        Generates CTL code snippets or component transform code.

Configuration
-------------
All tuneable knobs are module-level constants below.  Edit them directly or
override them from the environment.

    CLOVERDX_LLM_API_URL – Overrides LLM_API_URL if defined.
    CLOVERDX_LLM_MODEL   – Overrides LLM_MODEL if defined.
    CLOVERDX_LLM_TEMPERATURE – Overrides LLM_TEMPERATURE if defined.
    CLOVERDX_LLM_TOP_P   – Overrides LLM_TOP_P if defined.
    CLOVERDX_LLM_ALLOW   – Overrides LLM_ALLOW if defined (true/false).
    LLM_ALLOW            – Alternate env name for enabling LLM-backed CTL tools.

    LLM_API_URL          – Full URL of the OpenAI-compatible /chat/completions endpoint.
                          Default: http://localhost:11434/v1/chat/completions (Ollama).
  LLM_MODEL            – Model identifier to pass in the request body.
  LLM_TEMPERATURE      – Sampling temperature (0.0–2.0).  Lower = more deterministic.
  LLM_TOP_P            – Nucleus sampling probability cutoff (0.0–1.0).
  VALIDATE_SYSTEM_PROMPT     – System prompt used by validate_CTL.
  VALIDATE_USER_PROMPT_PREPEND – User-message prefix for validate_CTL.
  GENERATE_SYSTEM_PROMPT     – System prompt used by generate_CTL.
  GENERATE_USER_PROMPT_PREPEND – User-message prefix for generate_CTL.
"""

import json
import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


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
You are an expert CloverDX CTL2 code reviewer.
Your job is to analyse CTL2 transformation code for correctness, safety and best practices.

Focus on the following issue classes:

PORT METADATA INTERPRETATION
    When CloverDX metadata context is provided, it is organized into two groups:
    Input Ports Metadata and Output Ports Metadata.
    - Input Ports Metadata applies only to $in.N.fieldName references.
    - Output Ports Metadata applies only to $out.N.fieldName references.
    - Within each group, each labeled port subsection identifies the exact port
        whose metadata follows.
    - Port labels should communicate the logical role of the port, not just the
        direction. Prefer labels such as Port 0 (master), Port 1 (slave1),
        Port 2 (slave2), Port 0 (rejected), or Port 1 (error output) instead of
        redundant labels such as Port 0 (input) or Port 0 (output).

REGEX-UNSAFE OPERATORS
  The ?= operator and the replace() function treat their right-hand operand as a
  Java regex pattern.  Any literal that contains regex meta-characters –
  { } [ ] ( ) . * + ? ^ $ | \\ – will cause a runtime PatternSyntaxException.
  Warn whenever a string literal containing these characters is used as the right
  operand of ?= or as the first (pattern) argument of replace().

FIELD REFERENCE MISMATCHES
  When CloverDX metadata XML is provided, every $in.N.fieldName and
  $out.N.fieldName reference in the code must correspond to a <Field name="...">
  element in the matching <Record>.  Report every reference that cannot be
  resolved.

UNDECLARED VARIABLES
  Flag any variable that is read before it has been declared.

SCOPE ISSUES
  CTL2 variables declared inside an if/else/for/while block are not visible
  outside that block.  Flag any use of a block-scoped variable beyond the
  closing brace.

TYPE MISMATCHES
  Flag obvious type coercion issues, e.g. assigning a string expression to an
  integer field without an explicit conversion call.

evalExpression() USAGE
  evalExpression() evaluates a CTL expression string at runtime and returns a
  variant.  It CAN access $in/$out port records and local variables in scope.
  Key concerns to flag:
  - The expression must be a single expression that returns a value — statements
    (for, if, variable declarations) are not allowed inside the expression string.
  - evalExpression() is expensive — warn if it appears inside a per-record
    transform() without justification (e.g. dynamic user-provided expressions
    from getParamValue() are a valid use case).
  - Error handling: expressions from external sources (parameters, files) should
    be wrapped in try/catch with CTLException to prevent runtime crashes from
    invalid input.

MISSING RETURN / UNREACHABLE CODE
  Warn if a transform() function has a code path that never returns, or if
  statements appear after a return.

GENERAL LOGIC ERRORS
  Flag code where the conditional logic is clearly inverted or contradictory —
  e.g. checking that a value is null and then using it in arithmetic or
  assignment, checking a condition and performing the opposite action in the
  body, or guarding a branch with a predicate that guarantees the branch body
  will always fail.

Output format — use this exact structure:

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
Please review the following CloverDX CTL2 code and report any issues.\
"""

GENERATE_SYSTEM_PROMPT: str = """\
You are an expert CloverDX CTL2 author.
Generate correct, runnable CTL2 code based on the requested functionality.

Rules:
- Output only CTL2 code enclosed in ```ctl fences, with no prose before or after the fenced block.
- Prefer clear, defensive code and explicit conversions where relevant.
- When metadata is provided, it is grouped into Input Ports Metadata and Output
    Ports Metadata sections. Use input-ports metadata only for $in.N references
    and output-ports metadata only for $out.N references.
- Port subsection labels should describe the logical role of the port where
    possible, e.g. Port 0 (master) and Port 1 (slave1), not just input/output.
- When metadata is provided, reference field names exactly as defined.
- If the request is for an expression snippet, return only that expression/snippet.
- If the request is for a component transform, return a full CTL2 block suitable
    for CloverDX attr transform usage.
"""

GENERATE_USER_PROMPT_PREPEND: str = """\
Generate CloverDX CTL2 code according to the request below. Enclose the generated code in ```ctl ticks.\
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
        "### Input Ports Metadata",
        "Use this group only for $in.N.* references.",
    ]
    if input_cleaned:
        parts.append(input_cleaned)
    else:
        parts.append("No input ports metadata provided.")

    parts.extend(
        [
            "### Output Ports Metadata",
            "Use this group only for $out.N.* references.",
        ]
    )
    if output_cleaned:
        parts.append(output_cleaned)
    else:
        parts.append("No output ports metadata provided.")

    return "\n".join(parts)


# ── Public API ─────────────────────────────────────────────────────────────────

def _call_llm(user_message: str, system_prompt: str, timeout: int) -> str:
    payload = {
        "model": LLM_MODEL,
        "temperature": LLM_TEMPERATURE,
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
        raise RuntimeError(
            f"Cannot connect to LLM at {LLM_API_URL}. "
            "Ensure Ollama (or another OpenAI-compatible server) is running. "
            f"Detail: {exc}"
        ) from exc
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"LLM request timed out after {timeout}s. "
            "Consider increasing the timeout or using a faster/smaller model."
        )
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(
            f"LLM returned HTTP error: {exc.response.status_code} "
            f"{exc.response.text[:400]}"
        ) from exc

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(
            f"Unexpected LLM response structure: {json.dumps(data)[:500]}"
        ) from exc


def validate_CTL(
    code: str,
    input_metadata: Optional[str] = None,
    output_metadata: Optional[str] = None,
    query: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Send CTL2 code to the configured LLM for linting analysis.

    Parameters
    ----------
    code:
        CTL2 transform code to validate (plain text, not XML-escaped).
    input_metadata:
        Optional CloverDX metadata for input ports in XML serialization format.
        This metadata is used only for $in.N field references.
    output_metadata:
        Optional CloverDX metadata for output ports in XML serialization format.
        This metadata is used only for $out.N field references.
    query:
        Optional additional instruction or question appended to the user
        message, e.g. "Focus on the replace() calls in the transform function."
    timeout:
        HTTP request timeout in seconds.  Increase for large code blocks or
        slow/remote model endpoints.

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

    logger.info(
        "validate_CTL: calling LLM at %s (model=%s, code_len=%d, input_metadata=%s, output_metadata=%s, query=%s)",
        LLM_API_URL,
        LLM_MODEL,
        len(code),
        "yes" if input_metadata else "no",
        "yes" if output_metadata else "no",
        repr(query[:60]) if query else "none",
    )
    return _call_llm(user_message=user_message, system_prompt=VALIDATE_SYSTEM_PROMPT, timeout=timeout)


def generate_CTL(
    description: str,
    input_metadata: Optional[str] = None,
    output_metadata: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Generate CTL2 code from a functional description.

    Parameters
    ----------
    description:
        What to generate: component transform code, an expression snippet,
        or other CTL functionality.
    input_metadata:
        Optional CloverDX metadata for input ports in XML serialization format.
        This metadata is used only for $in.N field references.
    output_metadata:
        Optional CloverDX metadata for output ports in XML serialization format.
        This metadata is used only for $out.N field references.
    timeout:
        HTTP request timeout in seconds.
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

    logger.info(
        "generate_CTL: calling LLM at %s (model=%s, desc_len=%d, input_metadata=%s, output_metadata=%s)",
        LLM_API_URL,
        LLM_MODEL,
        len(description),
        "yes" if input_metadata else "no",
        "yes" if output_metadata else "no",
    )
    return _call_llm(user_message=user_message, system_prompt=GENERATE_SYSTEM_PROMPT, timeout=timeout)
