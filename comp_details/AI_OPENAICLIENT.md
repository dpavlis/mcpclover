# CloverDX AI_OPENAICLIENT — LLM Reference

## What it does
Sends queries to remote AI language models and processes responses, one query cycle per input record. Supports multi-turn conversation loops — `processResponse()` can return `CONTINUE` to send a follow-up query in the same conversation before accepting a response or moving to the next record.

Supported providers: **OpenAI**, **Anthropic** (Claude), **Azure OpenAI**, **Google Gemini**, and any OpenAI-compatible API endpoint via `baseURL` override (e.g. Ollama for local models).

Also known as **AIClient** (display name, renamed from *OpenAIClient* in 7.3.0).
Component type string: `AI_OPENAICLIENT`.

## Ports
- Input 0: required — one record per AI query (any metadata)
- Output 0: required — at least one `string` or `variant` field (receives response)

**Auto-propagated metadata:** input metadata propagated to output.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `connection` | yes | — | Provider config inline string — see Connection section |
| `systemMessage` [attr-cdata] | no | — | Inline system prompt text sent to model as context |
| `systemMessageURL` | no | — | Path/URL to external `.txt` or `.md` file containing the system prompt. Used for longer prompts. Takes precedence over `systemMessage` if both set. |
| `transform` [attr-cdata] | yes | — | CTL2 query/response processor — see CTL interface section |
| `requestTimeout` | no | `1m` | How long to wait for a response before failing. Supports time units: `30s`, `5m`, `10m`. |
| `retryCount` | no | `0` | Number of retry attempts on failure before calling `sendRequestOnError()`. |
| `retryDelay` | no | `0` | Comma-separated seconds between retries: e.g. `2` (fixed), `2, 5, 10` (escalating). Last value repeats for subsequent retries. |
| `rateLimitTimeInterval` | no | `1s` | Time window for rate limiting: `1s`, `1m`, `1h`, `1d` |
| `rateLimitRequestsPerInterval` | no | unlimited | Max requests per rate-limit window. When reached, component waits for the window to reset. |

## Connection String

The `connection` attribute is a multi-line key=value string (newline-separated, XML-encoded as `&#10;`).

### OpenAI
```
provider=OPEN_AI
apiKey=${OPENAI_KEY}
modelName=gpt-5.1
```

### OpenAI-compatible endpoint (e.g. Ollama for local models)
```
provider=OPEN_AI
apiKey=ollama
modelName=ministral-3-128k
baseURL=http://myserver.somewhere.com:11434/v1
```
`baseURL` overrides the default `https://api.openai.com/v1`. Note: `:` in URLs must be escaped as `\:` in the inline string (e.g. `http\://host\:11434/v1`).

### Anthropic (Claude)
```
provider=ANTHROPIC
apiKey=${ANTHROPIC_KEY}
modelName=claude-opus-4-5
```

### Azure OpenAI
```
provider=AZURE_OPEN_AI
apiKey=${AZURE_KEY}
endpoint=https://my-resource.openai.azure.com/
deploymentName=my-deployment
```

### Google Gemini
```
provider=GEMINI
apiKey=${GEMINI_KEY}
modelName=gemini-2.0-flash
```

### Connection in XML source
In the `.grf` file, newlines in the connection string are encoded as `&#10;` and `:` in URLs as `\:`:
```xml
<Node connection="provider=OPEN_AI&#10;apiKey=${OPENAI_KEY}&#10;modelName=gpt-5.1&#10;"
      type="AI_OPENAICLIENT" .../>

<!-- Ollama with custom baseURL -->
<Node connection="provider=OPEN_AI&#10;apiKey=ollama&#10;modelName=qwen3-coder:latest&#10;baseURL=http\://xenserver-g8.javlin.eu\:11434/v1/&#10;"
      type="AI_OPENAICLIENT" .../>
```

## System Message

Two ways to provide the system prompt:

```xml
<!-- Inline — for short prompts -->
<attr name="systemMessage"><![CDATA[You are an expert in finding PII in texts. Output JSON only.]]></attr>

<!-- External file — for long prompts (reference docs, CTL manuals, etc.) -->
<Node systemMessageURL="${DATAIN_DIR}/CTL2_Reference_for_LLM.md" .../>
```

`systemMessageURL` is the dominant pattern in the Sandbox examples — all production use cases load a reference document as the system prompt.

## CTL Interface

Three mandatory functions. Others are optional error handlers.

```ctl
//#CTL2

const integer CONTINUE = -3;   // return from processResponse() to loop

const string ROLE_ASSISTANT = "ASSISTANT";
const string ROLE_SYSTEM    = "SYSTEM";
const string ROLE_USER      = "USER";

// Called once per input record.
// Return true to reset chat history (start fresh conversation).
// Return false to continue previous conversation context.
// Most use cases return true (independent query per record).
function boolean newChat() {
    return true;
}

// Called once per loop iteration, before sending to AI.
// iterationIndex = 0 for first call per record, increments on CONTINUE.
// Return the user message string to send.
// Return null to add nothing (manually modify chatContext instead).
// $in.0 accessible here.
function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex) {
    return $in.0.text;
}

// Called when AI response arrives.
// assistantResponse = the response text (also at end of chatContext).
// $in.0 and $out.0 accessible here.
// Returns:
//   OK       — write output record, move to next input record
//   CONTINUE — no output, call prepareQuery() again with iterationIndex+1
//   SKIP     — discard response, move to next input record
//   STOP     — stop all processing, throw exception
function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse) {
    $out.0.result = assistantResponse;
    return OK;
}
```

### Function signatures summary

| Function | Required | When called | Returns |
|---|---|---|---|
| `newChat()` | ✓ | Once per input record | `true` = reset / `false` = preserve chat |
| `prepareQuery(chatContext, iterationIndex)` | ✓ | Before each AI request | `string` user message, or `null` |
| `processResponse(chatContext, iterationIndex, assistantResponse)` | ✓ | When AI responds | `OK` / `CONTINUE` / `SKIP` / `STOP` |
| `newChatOnError(errorMessage, stackTrace)` | no | If `newChat()` throws | `true`/`false` |
| `prepareQueryOnError(errorMessage, stackTrace, chatContext, iterationIndex)` | no | If `prepareQuery()` throws | `string` fallback message |
| `sendRequestOnError(errorMessage, stackTrace, chatContext, iterationIndex)` | no | After all retries exhausted | `OK`/`CONTINUE`/`SKIP`/`STOP` |
| `processResponseOnError(errorMessage, stackTrace, chatContext, iterationIndex)` | no | If `processResponse()` throws | `OK`/`CONTINUE`/`SKIP`/`STOP` |

### $in.0 / $out.0 access

| Function | `$in.0` | `$out.0` |
|---|---|---|
| `newChat()` | ✗ | ✗ |
| `prepareQuery()` | ✓ | ✗ |
| `prepareQueryOnError()` | ✓ | ✗ |
| `sendRequestOnError()` | ✓ | ✗ |
| `processResponse()` | ✓ | ✓ |
| `processResponseOnError()` | ✓ | ✓ |

### ChatMessage type

Used in `chatContext` and to manually build messages:
```ctl
ChatMessage msg;
msg.role    = "USER";        // "USER", "ASSISTANT", or "SYSTEM"
msg.content = "Try again, return valid JSON only.";
push(chatContext, msg);
return CONTINUE;             // triggers prepareQuery() with next iterationIndex
```

## Real Sandbox Examples

### Anonymization_library — PII detection, inline system message, Ollama
```xml
<Node connection="provider=OPEN_AI&#10;apiKey=ollama&#10;modelName=ministral-3-128k&#10;baseURL=http\://xenserver-g8.javlin.eu\:11434/v1&#10;"
      guiName="AIClient" id="AICLIENT"
      requestTimeout="5m" retryCount="1" retryDelay="5"
      type="AI_OPENAICLIENT">
    <attr name="systemMessage"><![CDATA[You are expert in finding PII (Personally Identifiable Information) in texts.
For each PII piece, provide the identified text, type, and character offset.
Output all identified PIIs as a JSON array only.
]]></attr>
    <attr name="transform"><![CDATA[//#CTL2
const integer CONTINUE = -3;

function boolean newChat() { return true; }

function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex) {
    return $in.0.text;
}

function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse) {
    $out.0.classes = assistantResponse;
    return OK;
}
]]></attr>
</Node>
```

### fixExamples / reworkExamples — CTL2 example generation, external system prompt, OpenAI
```xml
<Node connection="provider=OPEN_AI&#10;apiKey=${OPENAI_KEY}&#10;modelName=gpt-5.1&#10;"
      guiName="VerifyExample" id="VERIFY_EXAMPLE"
      requestTimeout="10m" retryCount="2" retryDelay="2"
      systemMessageURL="${DATAIN_DIR}/CTL2_Reference_for_LLM.md"
      type="AI_OPENAICLIENT">
    <attr name="transform"><![CDATA[//#CTL2
const integer CONTINUE = -3;

function boolean newChat() { return true; }

function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex) {
    // Build prompt using input record fields
    string msg = replacePlaceholder(MSG_TEMPLATE, "{USER_QUERY}", $in.0.user);
    msg = replacePlaceholder(msg, "{CODE_TO_REVIEW}", $in.0.assistant);
    return msg;
}

function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse) {
    $out.0.* = $in.0.*;
    $out.0.old_asisstant = $in.0.assistant;
    $out.0.assistant = assistantResponse;
    return OK;
}
]]></attr>
</Node>
```

### Multi-turn with retry loop — validate JSON response, loop until valid
```ctl
//#CTL2
const integer CONTINUE = -3;

function boolean newChat() { return true; }

function string prepareQuery(list[ChatMessage] chatContext, integer iterationIndex) {
    if (iterationIndex == 0) {
        return $in.0.message;
    } else {
        return "Answer with a valid JSON.";    // retry instruction
    }
}

function integer processResponse(list[ChatMessage] chatContext, integer iterationIndex, string assistantResponse) {
    try {
        $out.0.response = parseJson(assistantResponse);   // validate by parsing
        return OK;
    } catch (CTLException e) {
        if (iterationIndex < 3) {
            ChatMessage msg;
            msg.role = "USER";
            msg.content = "Answer with a valid JSON.";
            push(chatContext, msg);
            return CONTINUE;    // loop back to prepareQuery() with iterationIndex+1
        } else {
            return SKIP;        // give up after 3 retries
        }
    }
}
```

### reworkSimpleExamples — A/B testing with disabled Ollama fallback
```xml
<!-- Primary: OpenAI -->
<Node connection="provider=OPEN_AI&#10;apiKey=${OPENAI_KEY}&#10;modelName=gpt-5.1&#10;"
      id="CHANGE_EXAMPLE" requestTimeout="10m" retryCount="2" retryDelay="2"
      systemMessageURL="${DATAIN_DIR}/CTL2_Reference_for_LLM.md"
      type="AI_OPENAICLIENT">...</Node>

<!-- Fallback: local Ollama (disabled) -->
<Node connection="provider=OPEN_AI&#10;apiKey=ollama&#10;modelName=gpt-oss-128k:latest&#10;baseURL=http\://xenserver-g8.javlin.eu\:11434/v1/&#10;"
      enabled="disabled" id="CHANGE_EXAMPLE1" requestTimeout="10m" retryCount="2" retryDelay="2"
      systemMessageURL="${DATAIN_DIR}/CTL2_Reference_for_LLM.md"
      type="AI_OPENAICLIENT">...</Node>
```
Pattern: `enabled="disabled"` to keep an alternative provider node in the graph but inactive.

## Execution Flow

For each input record:
```
newChat()
  ↓
prepareQuery(chatContext, 0)  →  send to AI  →  processResponse(chatContext, 0, response)
                                                         ↓ CONTINUE
                                               prepareQuery(chatContext, 1)  →  send to AI  →  processResponse(chatContext, 1, response)
                                                                                                         ↓ OK → emit output record, next input
```

On `CONTINUE`, `prepareQuery()` is called again with `iterationIndex` incremented. The `chatContext` retains full history including previous responses — the model sees the full conversation.

## Decision Guide

| Need | Approach |
|---|---|
| Single query per record, write response to field | `prepareQuery` returns input field; `processResponse` assigns to output; return `OK` |
| Validate/retry until response is parseable | Return `CONTINUE` from `processResponse`; add correction message to `chatContext`; cap with `iterationIndex < N` guard |
| Long system prompt (reference doc, manual) | `systemMessageURL` pointing to external `.md` or `.txt` file |
| Build prompt from multiple input fields | `prepareQuery` constructs string from `$in.0.*` fields |
| Pass all input fields through + add response | `$out.0.* = $in.0.*;` in `processResponse` before writing response field |
| Use local model (Ollama, LM Studio) | `provider=OPEN_AI` + `apiKey=ollama` + `baseURL=http\://host\:port/v1` |
| Rate-limit calls to stay within API quota | `rateLimitTimeInterval` + `rateLimitRequestsPerInterval` |
| Handle network failures gracefully | `sendRequestOnError` — return `CONTINUE` to retry in CTL, or write error to output + `OK` |
| A/B test two providers | Two nodes, one with `enabled="disabled"` |

## Mistakes

| Wrong | Correct |
|---|---|
| `connection="provider=OPEN_AI\napiKey=..."` (literal `\n`) | Use `&#10;` for newlines in XML: `connection="provider=OPEN_AI&#10;apiKey=..."` |
| `baseURL=http://host:11434/v1` in XML | Escape `:` as `\:`: `baseURL=http\://host\:11434/v1` |
| `requestTimeout="60000"` (raw milliseconds) | Use time units: `requestTimeout="1m"` or `"30s"` |
| `CONTINUE` used without defining it | Always declare `const integer CONTINUE = -3;` at module level |
| Infinite loop — `processResponse` returns `CONTINUE` with no exit | Always cap with `iterationIndex < N` guard before returning `CONTINUE` |
| `$out.0` written in `prepareQuery()` | Not accessible — write output only in `processResponse()` |
| `$in.0` not accessible in `newChat()` | Not accessible in `newChat()` — only in `prepareQuery()` and `processResponse()` |
| `sendRequestOnError` called on first failure when retryCount > 0 | Only called after ALL retries have been exhausted |
| Forgetting `$out.0.* = $in.0.*;` when passthrough is needed | Explicitly copy input fields in `processResponse()` — no auto-passthrough |
| `systemMessage` and `systemMessageURL` both set | `systemMessageURL` takes precedence |
