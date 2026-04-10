"""
CloverDX CTL helper module
==========================
Provides two LLM-backed helpers over an OpenAI-compatible chat endpoint
(e.g. local Ollama):

    validate_CTL(code, metadata_context, query, timeout)
        Lints CTL2 code and reports issues.

    generate_CTL(description, metadata, timeout)
        Generates CTL code snippets or component transform code.

Configuration
-------------
All tuneable knobs are module-level constants below.  Edit them directly or
override them from the environment.

    CLOVERDX_LLM_API_URL – Overrides LLM_API_URL if defined.
    CLOVERDX_LLM_MODEL   – Overrides LLM_MODEL if defined.
    CLOVERDX_LLM_TEMPERATURE – Overrides LLM_TEMPERATURE if defined.
    CLOVERDX_LLM_TOP_P   – Overrides LLM_TOP_P if defined.

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

VALIDATE_SYSTEM_PROMPT: str = """\
You are an expert CloverDX CTL2 code reviewer.
Your job is to analyse CTL2 transformation code for correctness, safety and best practices.

Focus on the following issue classes:

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
  evalExpression() has no port context; it cannot access $in or $out records.
  Warn if the code passed to evalExpression() contains field references.

MISSING RETURN / UNREACHABLE CODE
  Warn if a transform() function has a code path that never returns, or if
  statements appear after a return.

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
- Output only CTL2 code (no markdown fences, no prose before/after code).
- Prefer clear, defensive code and explicit conversions where relevant.
- When metadata is provided, reference field names exactly as defined.
- If the request is for an expression snippet, return only that expression/snippet.
- If the request is for a component transform, return a full CTL2 block suitable
    for CloverDX attr transform usage.
"""

GENERATE_USER_PROMPT_PREPEND: str = """\
Generate CloverDX CTL2 code according to the request below.\
"""


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
    metadata_context: Optional[str] = None,
    query: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Send CTL2 code to the configured LLM for linting analysis.

    Parameters
    ----------
    code:
        CTL2 transform code to validate (plain text, not XML-escaped).
    metadata_context:
        Optional CloverDX metadata in the standard XML serialization format
        (<Record name="..."><Field name="..." type="..." .../> ... </Record>).
        When supplied the LLM will verify field references against it.
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

    if query:
        parts.append(f"\nAdditional instruction: {query.strip()}")

    parts.append(f"\n\n## CTL2 Code\n```\n{code}\n```")

    if metadata_context:
        parts.append(
            f"\n## CloverDX Metadata (XML)\n```xml\n{metadata_context}\n```"
        )

    user_message = "\n".join(parts)

    logger.info(
        "validate_CTL: calling LLM at %s (model=%s, code_len=%d, metadata=%s, query=%s)",
        LLM_API_URL,
        LLM_MODEL,
        len(code),
        "yes" if metadata_context else "no",
        repr(query[:60]) if query else "none",
    )
    return _call_llm(user_message=user_message, system_prompt=VALIDATE_SYSTEM_PROMPT, timeout=timeout)


def generate_CTL(
    description: str,
    metadata: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """Generate CTL2 code from a functional description.

    Parameters
    ----------
    description:
        What to generate: component transform code, an expression snippet,
        or other CTL functionality.
    metadata:
        Optional CloverDX metadata XML context. For component-level generation
        this should be provided so field names/types can be used correctly.
    timeout:
        HTTP request timeout in seconds.
    """
    parts: list = [GENERATE_USER_PROMPT_PREPEND.strip()]
    parts.append(f"\nRequest:\n{description.strip()}")
    if metadata:
        parts.append(f"\n\n## CloverDX Metadata (XML)\n```xml\n{metadata}\n```")

    user_message = "\n".join(parts)

    logger.info(
        "generate_CTL: calling LLM at %s (model=%s, desc_len=%d, metadata=%s)",
        LLM_API_URL,
        LLM_MODEL,
        len(description),
        "yes" if metadata else "no",
    )
    return _call_llm(user_message=user_message, system_prompt=GENERATE_SYSTEM_PROMPT, timeout=timeout)
