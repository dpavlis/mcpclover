# CloverDX HTTP_CONNECTOR — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x HTTP_CONNECTOR (HTTPConnector).
> Incorporates confirmed working patterns from the DataManagerLib sandbox subgraphs.
> HTTPConnector is the older, general-purpose HTTP component — for new REST API integrations,
> consider RESTConnector first (see comparison below).

---

## WHEN TO USE HTTP_CONNECTOR VS ALTERNATIVES

| Component | Since | Use when |
|---|---|---|
| **REST_CONNECTOR** | 6.7 | **Default choice for new REST API integrations.** Loads config from OpenAPI spec, built-in JSON request/response mapping, built-in pagination (offset, page, token-based), rate limiting, visual response mapping per status code. Easier to configure and maintain. |
| **HTTP_CONNECTOR** | 3.x | General-purpose HTTP/S component. Use when: (1) the API has no OpenAPI spec and requires highly custom request/response handling, (2) you need raw HTTP control (custom headers, multipart file uploads, streaming, raw byte responses), (3) working with non-REST HTTP endpoints (file downloads, webhooks, SOAP-over-HTTP, form submissions), (4) maintaining or extending older graphs that already use it. |
| WebServiceClient | — | SOAP/WSDL web services only. Not for REST APIs. |

**Decision rule:** For REST APIs with JSON payloads, start with `REST_CONNECTOR`. Fall back to `HTTP_CONNECTOR` when you need lower-level HTTP control, non-JSON content types, or the API interaction doesn't fit the REST pattern.

**Note:** HTTP_CONNECTOR is widely used in existing graphs and libraries (e.g. DataManagerLib). Understanding it remains essential for reading, maintaining, and extending existing CloverDX solutions.

### What REST_CONNECTOR handles that HTTP_CONNECTOR requires manual work for

| Capability | REST_CONNECTOR | HTTP_CONNECTOR |
|---|---|---|
| OpenAPI spec loading | Auto-loads endpoints, params, schemas | Manual configuration |
| JSON response parsing | Built-in visual mapping per status code | Requires downstream JSON_READER |
| JSON request body | Built-in mapping from input records | Requires CTL in input mapping with `writeJson()` |
| Pagination | Built-in: offset, page-based, token-based | Manual: loop with DATA_GENERATOR or recursive subgraph |
| Rate limiting | Built-in: max requests per time interval | Manual: CTL sleep/delay logic |
| Status code routing | Visual mapping per status code range | Manual: EXT_FILTER + CTL error formatting |
| Error handling | Default output/error mapping with fallback | Manual: separate port 1 + EXT_FILTER pattern |
| Multiple input ports | 0-n input ports with JSON body mapping | Single input port 0 only |
| Multiple output ports | 0-n output ports with per-status routing | Port 0 (response) + port 1 (errors) only |

---

## COMPONENT SKELETON

### Minimal — no input port, GET request, output to port 0

```xml
<Node guiName="GET data" guiX="200" guiY="100" id="HTTP_GET"
      requestMethod="GET" type="HTTP_CONNECTOR"
      url="https://api.example.com/v1/data"
      username="${API_USER}" password="${API_PASS}">
    <attr name="headerProperties"><![CDATA[Content-Type=application/json
]]></attr>
</Node>
```

### With input port — per-record requests with URL placeholders

```xml
<Node guiName="PUT update" guiX="500" guiY="100" id="HTTP_PUT"
      requestMethod="PUT" type="HTTP_CONNECTOR"
      url="https://api.example.com/v1/items/*{itemId}/columns/*{columnName}"
      username="${API_USER}" password="${API_PASS}">
    <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.requestContent = writeJson({"value" -> $in.0.newValue});
    return ALL;
}
]]></attr>
    <attr name="standardOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;
    $out.0.itemId = $in.0.itemId;
    return ALL;
}
]]></attr>
    <attr name="errorOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.errorMessage = $in.1.errorMessage;
    $out.1.itemId = $in.0.itemId;
    return ALL;
}
]]></attr>
    <attr name="headerProperties"><![CDATA[Content-Type=application/json
]]></attr>
</Node>
```

**Key node attributes:** `url`, `requestMethod`, `username`/`password`, `headerProperties`.
**Ports:** Optional input `0`, optional output `0` (response), optional output `1` (errors).

---

## NODE-LEVEL ATTRIBUTES

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="HTTP_CONNECTOR"` | yes | Component type |
| `url` | yes | Target URL. Supports graph parameters and `*{fieldName}` placeholders (replaced from input record). |
| `requestMethod` | no | `GET` (default), `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`, `TRACE` |
| `charset` | no | Request/response encoding. Best practice: always set `UTF-8` for JSON APIs. |
| `username` | no | HTTP Basic/Digest authentication username. |
| `password` | no | Authentication password. Use `${SECURE_PARAM}` — never inline. |
| `authenticationMethod` | no | `BASIC` (default), `DIGEST`, `ANY`. |
| `addInputFieldsAsParameters` | no | `true`: input fields auto-appended as URL query parameters. Default: `false`. |
| `addInputFieldsAsParametersTo` | no | `QUERY` (default) or `BODY`. Where to send auto-added parameters. |
| `ignoredFields` | no | Semicolon-separated field names to exclude from auto-parameters. |
| `timeout` | no | Response timeout. Default: `1m` (60 seconds). Supports time units: `30s`, `2m`, `500ms`. |
| `retryCount` | no | Number of retries on connection failure (not HTTP error codes). Default: `0`. |
| `retryDelay` | no | Comma-separated delay in seconds between retries. Last value repeats. Default: `0`. |
| `redirectErrorOutput` | no | `true`: error details sent to output port 0 (via `errorMessage` field in output mapping) instead of port 1. Default: `false`. |
| `responseAsFileName` | no | `true`: write response body to temp files, return file path via output mapping. Default: `false`. |
| `responseFilePrefix` | no | Prefix for temp response files. Default: `http-response-`. |
| `streaming` | no | `true` (default): stream input file with chunked transfer encoding. |
| `disableSSLCertValidation` | no | `true`: skip SSL cert validation. Use only for development/testing. |

---

## URL PLACEHOLDERS — `*{fieldName}`

When an input port is connected, `*{fieldName}` in the URL is replaced with the value of that field from the current input record. The field values are **automatically URL-encoded**.

```
url="https://api.example.com/v1/data-sets/*{dataSetCode}/rows/*{rowId}"
```

With input record `{dataSetCode: "PRODUCTS", rowId: 42}`, the resolved URL becomes:
```
https://api.example.com/v1/data-sets/PRODUCTS/rows/42
```

**Rules:**
- Placeholder names must match input metadata field names exactly (case-sensitive).
- Works for all HTTP methods.
- Special characters in field values are automatically URL-encoded — do not pre-encode.
- Graph parameters (`${PARAM}`) in the URL are resolved before field placeholders (`*{field}`).

---

## MAPPINGS — THE CORE CONCEPT

HTTP_CONNECTOR has three CTL mapping blocks, each defined as `[attr-cdata]` properties:

| Mapping | XML attribute name | When it runs | `$in` ports | `$out` ports |
|---|---|---|---|---|
| **Input mapping** | `inputMapping` | Before sending request | `$in.0` = input record | `$out.0` = component attributes (URL, requestContent, headers, etc.) |
| **Output mapping** | `standardOutputMapping` | After receiving response | `$in.0` = input record, `$in.1` = response result | `$out.0` = output port 0 record |
| **Error mapping** | `errorOutputMapping` | On connection/processing error | `$in.0` = input record, `$in.1` = error details | `$out.1` = output port 1 record |

All three use the standard CTL `function integer transform()` signature.

---

## INPUT MAPPING

Sets component attributes dynamically from the input record. The `$out.0` fields map to special component attribute names (not output metadata fields).

### Settable fields in `$out.0`

| Field | Type | Description |
|---|---|---|
| `URL` | string | Override the URL attribute |
| `requestMethod` | string | Override request method |
| `requestContent` | string | Request body as string (for POST/PUT/PATCH) |
| `requestContentByte` | byte | Request body as raw bytes |
| `inputFileURL` | string | Read request body from file |
| `outputFileURL` | string | Write response to file |
| `additionalHTTPHeaderProperties` | string | Additional headers as `{key=value,key2=value2}` |
| `charset` | string | Override charset |
| `username` | string | Override authentication username |
| `password` | string | Override authentication password |
| `oAuth2AccessToken` | string | OAuth2 bearer token |
| `addInputFieldsAsParameters` | boolean | Override auto-parameter behavior |
| `addInputFieldsAsParametersTo` | string | Override parameter destination |
| `ignoredFields` | string | Override ignored fields |
| `storeResponseToTempFile` | boolean | Override temp file storage |

### Common patterns

**POST JSON body from input field:**
```ctl
//#CTL2
function integer transform() {
    $out.0.requestContent = $in.0.jsonPayload;
    return ALL;
}
```

**Build JSON body dynamically with `writeJson()`:**
```ctl
//#CTL2
function integer transform() {
    variant body = {"value" -> $in.0.newValue};
    $out.0.requestContent = writeJson(body);
    return ALL;
}
```

**Set bearer token:**
```ctl
//#CTL2
function integer transform() {
    $out.0.additionalHTTPHeaderProperties = "{Authorization=Bearer " + $in.0.token + "}";
    return ALL;
}
```

---

## OUTPUT MAPPING

Maps response data and input record fields to the output port 0 record.

### Available `$in` sources

| Source | Field | Type | Description |
|---|---|---|---|
| `$in.0` | (input record) | any | Pass-through from input port — preserve context like IDs |
| `$in.1.content` | string | Response body as string (null if written to file) |
| `$in.1.contentByte` | byte | Response body as raw bytes |
| `$in.1.outputFilePath` | string | Path to response file (null if not file mode) |
| `$in.1.statusCode` | integer | HTTP status code (200, 404, 500, etc.) |
| `$in.1.header` | map[string,string] | Response headers as key-value map |
| `$in.1.rawHeaders` | string[] | Response headers as string array |
| `$in.1.errorMessage` | string | Error message (only when `redirectErrorOutput=true`) |

### Common patterns

**Map response + preserve input context:**
```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;          // all response fields
    $out.0.itemId = $in.0.itemId; // preserve input context
    return ALL;
}
```

**Map only status code and content:**
```ctl
//#CTL2
function integer transform() {
    $out.0.statusCode = $in.1.statusCode;
    $out.0.content = $in.1.content;
    return ALL;
}
```

**Default output mapping** (used when no output mapping is defined):
```ctl
$out.0.* = $in.0.*;  // input fields
$out.0.* = $in.1.*;  // response fields (overwrites matching names)
```

---

## ERROR MAPPING

Maps error details to output port 1. Only called when a connection/processing error occurs (IOException, timeout) — NOT for HTTP error status codes like 4xx/5xx.

**Critical distinction:** HTTP 4xx/5xx responses are NOT errors from the component's perspective. They are successful HTTP exchanges — the response goes to the output mapping on port 0. Only actual failures (network timeout, DNS failure, SSL error) trigger the error mapping on port 1.

### Available `$in` sources

| Source | Field | Type | Description |
|---|---|---|---|
| `$in.0` | (input record) | any | Pass-through from input port |
| `$in.1.errorMessage` | string | Error description |

### Common pattern

```ctl
//#CTL2
function integer transform() {
    $out.1.errorMessage = "API call failed for item " + $in.0.itemId + ": " + $in.1.errorMessage;
    return ALL;
}
```

**Default error mapping** (used when no error mapping is defined):
```ctl
$out.1.* = $in.0.*;  // input fields
$out.1.* = $in.1.*;  // error fields
```

---

## HEADER PROPERTIES

Set via `headerProperties` attribute. One header per line, `key=value` format:

```xml
<attr name="headerProperties"><![CDATA[Content-Type=application/json
Accept=application/json
X-Custom-Header=myvalue
]]></attr>
```

**Always set `Content-Type=application/json` for JSON APIs.** Without it, POST/PUT/PATCH bodies may be rejected by the server.

For dynamic headers (varying per request), use the input mapping:
```ctl
$out.0.additionalHTTPHeaderProperties = "{Authorization=Bearer " + $in.0.token + "}";
```

---

## TYPICAL GRAPH PATTERNS

### Pattern 1 — Simple GET, parse JSON response

```
[HTTP_CONNECTOR (GET)] --port 0--> [EXT_FILTER (status==200)]
                                        |-- accepted --> [JSON_READER (port:$0.content:discrete)] --> output
                                        |-- rejected --> [error handling]
                       --port 1--> [error handling]
```

The `JSON_READER` reads from the HTTP response using `port:$0.content:discrete` as its `fileURL`, which means "read the `content` field from input port 0 as inline data."

**Output metadata for the HTTP_CONNECTOR in this pattern must include `content` (string) and `statusCode` (integer) at minimum.**

### Pattern 2 — Per-record POST/PUT with input port

```
[input data] --> [REFORMAT (prepare request)] --> [HTTP_CONNECTOR (POST/PUT)]
                                                      |-- port 0 --> [EXT_FILTER (status check)] --> success/error handling
                                                      |-- port 1 --> [error handling]
```

The input record flows through the HTTP_CONNECTOR. URL placeholders `*{field}` are resolved from input fields. The request body is set via input mapping.

### Pattern 3 — Error handling pattern (from DataManagerLib)

```
HTTP_CONNECTOR --port 0--> EXT_FILTER (statusCode==200)
                                |-- accepted --> [parse/process response]
                                |-- rejected --> [REFORMAT: format API error] --> SIMPLE_GATHER
               --port 1--> [REFORMAT: format connection error]              --> SIMPLE_GATHER
                                                                                    |-- port 0 --> [error output]
                                                                                    |-- port 1 --> [FAIL component]
```

**This two-tier error handling separates:**
- **Port 1 errors** — connection failures (timeout, DNS, SSL) via error mapping
- **Port 0 + EXT_FILTER rejected** — HTTP error status codes (4xx, 5xx) from the API

Both error streams are gathered into a single error flow via SIMPLE_GATHER.

### Pattern 4 — API error message extraction

When an API returns JSON error details in the response body (common with REST APIs), use CTL to parse the error:

```ctl
//#CTL2
// ApiFailReporter.ctl — reusable error formatter
function integer transform() {
    string content = $in.0.content;
    variant apiError = content != null ? parseJson(content) : null;
    string message = content != null ? cast(apiError["message"], string) : null;

    $out.0.errorMessage = "HTTP " + $in.0.statusCode
                        + (message == null ? "" : ": " + message);
    return ALL;
}
```

Import this as an external .ctl file for reuse across multiple error-handling REFORMATs:
```ctl
import "${TRANS_DIR}/ApiFailReporter.ctl";
```

---

## RESPONSE PARSING

The HTTP_CONNECTOR outputs the raw response. Parsing is done by downstream components.

### JSON response → JSON_READER

```xml
<Node charset="UTF-8" fileURL="port:$0.content:discrete" guiName="Parse JSON"
      guiX="800" guiY="100" id="PARSE_RESPONSE" type="JSON_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="/root/object">
    <Context xpath="items" outPort="0"/>
</Context>
]]></attr>
</Node>
```

**Key:** `fileURL="port:$0.content:discrete"` — reads response body from the input field `content` on port 0 as inline data (one record = one complete JSON document).

### XML response → XML_EXTRACT

```xml
<Node charset="UTF-8" sourceUri="port:$0.content:discrete" guiName="Parse XML"
      guiX="800" guiY="100" id="PARSE_RESPONSE" type="XML_EXTRACT" useNestedNodes="true">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="response">
        <Mapping element="item" outPort="0"/>
    </Mapping>
</Mappings>
]]></attr>
</Node>
```

### Large responses → write to temp file

When the response is too large for a string field, use temp file mode:

```xml
<Node guiName="GET large data" guiX="200" guiY="100" id="HTTP_GET"
      requestMethod="GET" type="HTTP_CONNECTOR"
      url="https://api.example.com/v1/export"
      responseAsFileName="true" responseFilePrefix="api-response-">
    <attr name="standardOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.filePath = $in.1.outputFilePath;
    return ALL;
}
]]></attr>
</Node>
```

Then read the temp file with a downstream reader component (JSON_READER, XML_EXTRACT, FLAT_FILE_READER, etc.) using the file path from the output record.

---

## AUTHENTICATION

### HTTP Basic (default)

```xml
<Node ... type="HTTP_CONNECTOR"
      username="${API_USER}" password="${API_PASS}"
      authenticationMethod="BASIC">
```

### Bearer token (OAuth2)

Set via input mapping or header:

```xml
<attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.additionalHTTPHeaderProperties = "{Authorization=Bearer " + getOAuth2Token("MyOAuth2Connection") + "}";
    return ALL;
}
]]></attr>
```

Or use the `oAuth2Connection` attribute for automatic token management:
```xml
<Node ... type="HTTP_CONNECTOR" oAuth2Connection="MyOAuth2Connection">
```

### OAuth 1.0

```xml
<Node ... type="HTTP_CONNECTOR"
      consumerKey="${OAUTH_KEY}" consumerSecret="${OAUTH_SECRET}"
      oAuthAccessToken="${OAUTH_TOKEN}" oAuthAccessTokenSecret="${OAUTH_TOKEN_SECRET}">
```

---

## EDGE DECLARATIONS

Output port names:

```xml
<!-- Port 0: response output -->
<Edge fromNode="HTTP_CONN:0" id="Edge0" outPort="Port 0 (out)" ... />

<!-- Port 1: error output -->
<Edge fromNode="HTTP_CONN:1" id="Edge1" outPort="Port 1 (out)" ... />
```

Input port:
```xml
<Edge ... inPort="Port 0 (in)" toNode="HTTP_CONN:0"/>
```

---

## METADATA TEMPLATES

### Recommended output metadata (port 0)

```xml
<Record name="HTTPResponse" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <Field name="content" type="string"/>
    <Field name="statusCode" type="integer" trim="true"/>
    <Field name="errorMessage" type="string"/>
    <!-- Add pass-through fields from input as needed: -->
    <Field name="itemId" type="string"/>
</Record>
```

For full response capture, add:
```xml
    <Field name="contentByte" type="byte"/>
    <Field name="outputFilePath" type="string"/>
    <Field containerType="map" name="header" type="string"/>
    <Field containerType="list" name="rawHeaders" type="string"/>
```

### Recommended error metadata (port 1)

```xml
<Record name="HTTPError" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <Field name="errorMessage" type="string"/>
    <!-- Add pass-through fields from input as needed: -->
    <Field name="itemId" type="string"/>
</Record>
```

---

## GENERATION RULES FOR LLM

**Before generating an HTTP_CONNECTOR graph**, consider whether REST_CONNECTOR
(`type="REST_CONNECTOR"`) would be a better fit. Use HTTP_CONNECTOR when:
- The API has no OpenAPI spec and requires custom CTL-based request/response handling
- You need raw HTTP control (multipart uploads, streaming, non-JSON content)
- You're extending an existing graph that already uses HTTP_CONNECTOR
- The interaction is non-REST (file download, webhook, form submission)

If using HTTP_CONNECTOR, always include:
- `type="HTTP_CONNECTOR"`
- `url` (the target URL — use graph parameters for base URL)
- `requestMethod` (explicit, even for GET — clarity over default)
- `headerProperties` with `Content-Type=application/json` for JSON APIs

When using an input port:
- Define input mapping to set `requestContent` for POST/PUT/PATCH
- Use `*{fieldName}` in URL for path parameters — fields must exist in input metadata
- Always define output mapping to preserve input context (`$in.0.itemId` etc.)
- Always define error mapping with input context for error traceability

Error handling:
- Connect port 1 for connection/processing errors
- Add EXT_FILTER after port 0 to check `statusCode` (200, 201, 204, etc.)
- Parse API error messages from response body for non-2xx status codes
- Use SIMPLE_GATHER to merge error streams into a single error flow

Response parsing:
- For JSON: pipe response to JSON_READER with `fileURL="port:$0.content:discrete"`
- For XML: pipe response to XML_EXTRACT with `sourceUri="port:$0.content:discrete"`
- For large responses: use `responseAsFileName="true"` and pass `outputFilePath` to downstream reader

Authentication:
- Store passwords in secure graph parameters — never inline in XML
- Use `username`/`password` for Basic auth
- Use `oAuth2Connection` for OAuth2 with automatic token refresh
- Use input mapping for dynamic bearer tokens

Do NOT:
- Use `requestContent` attribute AND input mapping `requestContent` simultaneously — input mapping overrides
- Pre-encode URL parameters — `*{fieldName}` and `addInputFieldsAsParameters` auto-encode
- Assume HTTP 4xx/5xx triggers the error port — only connection failures use port 1
- Forget `Content-Type` header for POST/PUT/PATCH — API will likely reject the request
- Use `multipartEntities` with a manually set `Content-Type: multipart/form-data` — the component adds boundaries automatically

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| Expecting 4xx/5xx on error port | 4xx/5xx go to port 0 — check `statusCode` with EXT_FILTER |
| Missing `Content-Type` header for POST | Always set `Content-Type=application/json` (or appropriate type) in `headerProperties` |
| Pre-encoding URL parameters | `*{fieldName}` auto-encodes. Do not double-encode. |
| Inline password in graph XML | Use `${SECURE_PARAM}` — store password in secure graph parameter |
| No error handling on port 1 | Always connect port 1 or accept that connection errors will fail the graph |
| No status code check after port 0 | Add EXT_FILTER to check for expected status codes (200, 201, 204) |
| Using `requestContent` attribute for per-record bodies | Use input mapping `$out.0.requestContent = ...` instead |
| Response too large for string field | Set `responseAsFileName="true"` and read the temp file downstream |
| Setting `Content-Type: multipart/form-data` manually with multipart entities | Let the component set it automatically — manual setting breaks boundary headers |
| No timeout configured for external APIs | Set explicit `timeout` — default is 60s which may be too long or too short |
