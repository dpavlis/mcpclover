# CloverDX REST_CONNECTOR — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x REST_CONNECTOR (RESTConnector).
> Incorporates confirmed working patterns from AddressValidationLib and MiscExamples sandboxes.
> RESTConnector is the modern, preferred component for REST API integration — available since 6.7.
> For lower-level HTTP control or non-REST endpoints, see the HTTP_CONNECTOR reference.

---

## WHEN TO USE REST_CONNECTOR VS ALTERNATIVES

| Component | Since | Use when |
|---|---|---|
| **REST_CONNECTOR** | 6.7 | **Default choice for new REST API integrations.** Auto-loads config from OpenAPI spec, built-in JSON request/response mapping, built-in pagination (offset, page, token-based), rate limiting, visual response mapping per HTTP status code. Easiest to configure. |
| HTTP_CONNECTOR | 3.x | Fall back when: no OpenAPI spec + highly custom request handling, raw HTTP control needed (multipart uploads, streaming, raw bytes), non-REST endpoints (file downloads, webhooks, form submissions), extending older graphs. |
| WebServiceClient | — | SOAP/WSDL web services only. Not for REST APIs. |

**Decision rule:** For REST APIs with JSON payloads, use `REST_CONNECTOR`. It handles pagination, rate limiting, status-code routing, and JSON parsing that HTTP_CONNECTOR requires manual graph logic for.

---

## COMPONENT SKELETON

### Minimal — GET with OpenAPI spec

```xml
<Node apiRootUrl="https://api.example.com/v3.1" endpoint="/items"
      guiName="GetItems" guiX="400" guiY="100" id="REST_GET"
      openApiUrl="${DATAIN_DIR}/api-spec.yaml"
      requestMethod="GET" type="REST_CONNECTOR">
</Node>
```

### GET with request parameters and input mapping

```xml
<Node apiRootUrl="https://restcountries.com/v3.1" endpoint="/alpha/{code}"
      guiName="GetCountry" guiX="845" guiY="-50" id="REST_COUNTRY"
      openApiUrl="${DATAIN_DIR}/restCountriesOPENAPI.yaml"
      requestMethod="GET" requestParameters="code=&#13;&#10;"
      type="REST_CONNECTOR">
    <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.2.code = $in.0.country_code;
    return ALL;
}
]]></attr>
    <attr name="responseMapping"><![CDATA[<Mappings>
    <Mapping element="HTTP_200" responsesKey="200">
        <Mapping element="body_json">
            <Mapping element="flags">
                <Mapping element="png" outPort="0"
                    xmlFields="../../{}cca2;../{}png"
                    cloverFields="cca2;png"/>
            </Mapping>
        </Mapping>
    </Mapping>
</Mappings>
]]></attr>
    <attr name="defaultOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.content = $in.0.content;
    $out.1.statusCode = $in.0.statusCode;
    $out.1.errorMessage = $in.0.errorMessage;
    return ALL;
}
]]></attr>
</Node>
```

### POST with JSON body built from input fields

```xml
<Node apiRootUrl="https://addressvalidation.googleapis.com" endpoint="v1:validateAddress"
      guiName="ValidateAddress" guiX="399" guiY="122" id="VALIDATE_ADDR"
      headerProperties="Accept=*/*&#10;"
      requestMethod="POST" type="REST_CONNECTOR">
    <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.2.key = getParamValue("API_KEY");
    variant payload = {"address" -> {"regionCode" -> $in.0.country, "addressLines" -> [$in.0.address]}};
    $out.0.requestContent = writeJson(payload);
    return ALL;
}
]]></attr>
    <attr name="defaultOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.response = $in.0.content;
    $out.0.statusCode = $in.0.statusCode;
    $out.0.errorMessage = $in.0.errorMessage;
    $out.0.recordID = $in.2.recordID;
    return ALL;
}
]]></attr>
</Node>
```

---

## NODE-LEVEL ATTRIBUTES

### Connection

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="REST_CONNECTOR"` | yes | Component type |
| `apiRootUrl` | yes | Base URL of the API (e.g. `https://api.example.com/v1`). Use graph parameters. |
| `endpoint` | yes | API endpoint path (e.g. `/items`, `/alpha/{code}`). Path parameters in `{param}` are resolved from request parameters. |
| `openApiUrl` | no | Path to OpenAPI 2.x/3.x spec (JSON or YAML). Auto-loads endpoints, parameters, schemas. Strongly recommended. |
| `requestMethod` | no | `GET` (default), `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS`, `TRACE` |
| `charset` | no | Request/response encoding. Best practice: always `UTF-8` for JSON APIs. |

### Authentication

| Attribute (XML) | Description |
|---|---|
| `oAuth2Connection` | OAuth2 connection for automatic token management and refresh. |
| `username` / `password` | HTTP Basic authentication. Use secure parameters for password. |
| `bearerToken` | Bearer token — can be a parameter reference or set via input mapping. |
| `apiKeyValue` | API key value — can be a parameter reference or set via input mapping. |
| `apiKeyLocation` | Where to send API key: `header` (default) or `query`. |
| `apiKeyName` | Header or query parameter name for the API key. |

### Request

| Attribute (XML) | Description |
|---|---|
| `requestParameters` | Static request parameters, auto-loaded from OpenAPI spec. Line-separated `key=value` pairs. Values can reference graph parameters. |
| `requestBodyMapping` | Visual JSON request body mapping — maps input records to JSON structure. For multi-port, set `recordsPerFile` too. |
| `requestContent` | Static request body text. Can reference parameters. Cannot combine with `requestBodyMapping`. |
| `inFileUrl` | Read request body from file. |
| `recordsPerFile` | Max records per request (for JSON array bodies or multi-port mapping). |
| `multipartEntities` | Semicolon-separated field names for multipart POST. |
| `inputMapping` | CTL mapping: set request parameters and attributes dynamically from input record. |
| `headerProperties` | HTTP headers. Line-separated `key=value`. Auto-loaded from OpenAPI spec. |
| `sortKeys` | Sort key for input records — optimizes JSON body mapping to avoid caching. |

### Response

| Attribute (XML) | Description |
|---|---|
| `responseMapping` | Visual JSON response mapping per HTTP status code. Maps response body to output ports. |
| `defaultOutputMapping` | CTL fallback mapping for status codes not covered by `responseMapping`. Also handles connection errors. |
| `outFileUrl` | Write response to file. |
| `appendOutput` | Append to output file (default: `false`). |
| `pagination` | Built-in pagination configuration (see Pagination section). |

### Error handling & debugging

| Attribute (XML) | Description |
|---|---|
| `retryCount` | Retries on connection failure (not HTTP error codes). Default: `0`. |
| `retryDelay` | Comma-separated delays in seconds between retries. Default: `0`. |
| `rateLimitTimeInterval` | Rate limit window: `1s` (default), `1m`, `1h`, `1d`. |
| `rateLimitRequestsPerInterval` | Max requests per time window. Unlimited by default. |
| `debugPrint` | `true`: log API calls and responses to execution log. Default: `false`. |

---

## MAPPINGS — THE CORE CONCEPT

REST_CONNECTOR has a different mapping model from HTTP_CONNECTOR. There are two types of response mapping that work together, plus an input mapping.

### Mapping overview

| Mapping | XML attribute | Purpose | When used |
|---|---|---|---|
| **Input mapping** | `inputMapping` | Set request params and body from input record | Before sending request |
| **JSON response mapping** | `responseMapping` | Visual per-status-code JSON parsing to output ports | When response status matches a defined filter |
| **Default output/error mapping** | `defaultOutputMapping` | CTL fallback for unmatched status codes and connection errors | When no `responseMapping` filter matches, or on error |

### `$in` / `$out` port numbering

**Critical difference from HTTP_CONNECTOR:** In REST_CONNECTOR mappings, `$in.0` and `$out.0` refer to the **component's internal virtual ports**, not directly to the graph ports.

| Port reference | In input mapping | In default output mapping |
|---|---|---|
| `$in.0` | First connected input record (driver port) | Response result: `content`, `contentByte`, `contentJson`, `statusCode`, `responseHeaders`, `errorMessage` |
| `$in.2` | — | Input record (pass-through from request) |
| `$out.0` | Request body: `requestContent` | — |
| `$out.2` | Request parameters (by parameter name) | — |
| `$out.N` | — | Output port N |

**Note:** `$out.2` in input mapping maps to request parameters — the parameter names become field names. For example, if the endpoint has a `code` parameter: `$out.2.code = $in.0.country_code;`

---

## INPUT MAPPING

Sets request parameters and body dynamically from the input record.

### Setting request parameters

```ctl
//#CTL2
function integer transform() {
    $out.2.code = $in.0.country_code;        // path/query parameter
    $out.2.countrycodes = lowerCase($in.0.country);  // query parameter
    return ALL;
}
```

`$out.2` fields correspond to parameter names defined in `requestParameters` or the OpenAPI spec.

### Setting request body (POST/PUT/PATCH)

```ctl
//#CTL2
function integer transform() {
    variant payload = {"address" -> {"regionCode" -> $in.0.country, "addressLines" -> [$in.0.address]}};
    $out.0.requestContent = writeJson(payload);
    return ALL;
}
```

### Setting API key dynamically

```ctl
//#CTL2
function integer transform() {
    $out.2.key = getParamValue("API_KEY");
    return ALL;
}
```

### Rate limiting via CTL sleep (when built-in rate limiter is insufficient)

```ctl
//#CTL2
const integer sleepTime = 1000 / ${RATE_LIMIT};

function integer transform() {
    sleep(sleepTime);
    $out.2.q = $in.0.address;
    return ALL;
}
```

---

## JSON RESPONSE MAPPING

The primary response parsing mechanism. Maps JSON responses to output ports visually, with per-status-code routing.

```xml
<attr name="responseMapping"><![CDATA[<Mappings>
    <Mapping element="HTTP_200" responsesKey="200">
        <Mapping element="body_json">
            <Mapping element="items" outPort="0"/>
        </Mapping>
    </Mapping>
    <Mapping element="HTTP_404" responsesKey="404">
        <Mapping element="body_json" outPort="1"/>
    </Mapping>
</Mappings>
]]></attr>
```

### How status code matching works

- `responsesKey` can be a specific code (`"200"`), a range (`"400-499"`), or a wildcard (`"2XX"`)
- More specific codes take priority over ranges (e.g. `"404"` wins over `"400-499"`)
- Unmatched status codes fall through to `defaultOutputMapping`
- If no `defaultOutputMapping` exists: 2xx = success (no output), ≥300 = component fails

### Mapping syntax

The JSON response mapping uses XML syntax similar to XML_EXTRACT mapping:

- `<Mapping element="..." outPort="N">` — maps a JSON element to an output port
- `xmlFields` / `cloverFields` — explicit field name mapping (same syntax as XML_EXTRACT)
- `../` — parent navigation for accessing fields from enclosing JSON objects
- `{}fieldName` — attribute-style disambiguation

### Example — multi-port response mapping

```xml
<Mappings>
    <Mapping element="HTTP_200" responsesKey="200">
        <Mapping element="body_json">
            <Mapping element="flags">
                <Mapping element="png" outPort="0"
                    xmlFields="../../{}cca2;../{}png"
                    cloverFields="cca2;png"/>
            </Mapping>
        </Mapping>
    </Mapping>
</Mappings>
```

This maps the `cca2` field from two levels up and the `png` field from the parent `flags` object into output port 0.

---

## DEFAULT OUTPUT AND ERROR MAPPING

CTL-based fallback mapping for:
1. Status codes not matched by `responseMapping`
2. Connection/processing errors (timeout, DNS failure, SSL error)

```ctl
//#CTL2
function integer transform() {
    $out.0.response = $in.0.content;          // response body as string
    $out.0.statusCode = $in.0.statusCode;     // HTTP status code
    $out.0.errorMessage = $in.0.errorMessage; // error message (on failure)
    $out.0.recordID = $in.2.recordID;         // pass-through from input
    return ALL;
}
```

### Available `$in.0` fields (response result)

| Field | Type | Description |
|---|---|---|
| `content` | string | Response body as string |
| `contentByte` | byte | Response body as raw bytes |
| `contentJson` | variant | Response body as pre-parsed JSON variant (unique to REST_CONNECTOR) |
| `statusCode` | integer | HTTP status code |
| `responseHeaders` | map[string,string] | Response headers |
| `errorMessage` | string | Error message on connection failure |

### `$in.2` — input record pass-through

`$in.2` provides access to the original input record fields. Use this to preserve context (IDs, keys) in the output for downstream processing.

**Note:** `contentJson` (variant type) is unique to REST_CONNECTOR — it gives you the response already parsed as a JSON variant, so you can use `cast()` and map access directly in CTL without calling `parseJson()`.

---

## PAGINATION

REST_CONNECTOR handles pagination automatically. Configure the pagination type and parameters — the component issues repeated requests until all pages are retrieved.

### Offset and limit pagination

For APIs that use: "return N results starting from position M"

```
Pagination type: Offset and limit
Page size parameter: pageSize
Page size (limit): 50
Page offset parameter: startIndex
Initial page offset: 0
Response data path: members
Maximum number of requests: 100
```

Generates: `?pageSize=50&startIndex=0`, then `&startIndex=50`, `&startIndex=100`, ...

### Page-based pagination

For APIs that use: "return page N of M"

```
Pagination type: Page-based
Page size parameter: per_page
Page size (limit): 50
Page number parameter: page
Initial page number: 1
Response data path: (empty if data is root array)
Maximum number of requests: 100
```

Generates: `?per_page=50&page=1`, then `&page=2`, `&page=3`, ...

### Token-based pagination

For APIs that return a next-page token in the response:

```
Pagination type: Token-based
Page size parameter: max_results
Page size (limit): 50
Page token parameter: pagination_token
Next page token path: meta.next_token
Maximum number of requests: (unlimited)
```

Generates: first request without token, then adds `&pagination_token=<token from response>` until no token is returned.

### Key pagination fields

| Field | Description |
|---|---|
| **Response data path** | Dot-delimited path to the JSON node containing the actual data array. Used to detect empty pages. Leave empty if the root response is the data array. |
| **Next page token path** | (Token-based only) Dot-delimited path to the next-page token in the response. |
| **Maximum number of requests** | Safety limit to prevent infinite loops. |

---

## TYPICAL GRAPH PATTERNS

### Pattern 1 — GET with JSON response mapping (simplest)

```
[input data] --> [REST_CONNECTOR (GET)]
                     |-- port 0 (responseMapping: 200) --> [parsed records]
                     |-- port 1 (defaultOutputMapping) --> [error/unmatched handling]
```

No downstream JSON_READER needed — response mapping handles parsing.

### Pattern 2 — POST per-record with default output mapping

```
[input data] --> [REST_CONNECTOR (POST)]
                     |-- port 0 (defaultOutputMapping) --> [REFORMAT: parse response] --> output
```

When the response is not parsed by `responseMapping`, use `defaultOutputMapping` to capture `content`, `statusCode`, and pass-through fields, then parse in a downstream REFORMAT with `parseJson()`.

### Pattern 3 — API with pagination (automatic)

```
[REST_CONNECTOR (GET, pagination configured)]
    |-- port 0 --> [all pages merged automatically into single stream]
```

No looping logic needed. The component issues all page requests and outputs all records to port 0 as a single stream.

### Pattern 4 — Chain of API calls

```
[HTTP_CONNECTOR (GET ipapi)] --> [parse IP info] --> [REST_CONNECTOR (GET country details)]
                                                         |-- port 0 (responseMapping) --> [next step]
                                                         |-- port 1 (defaultOutputMapping) --> [error]
```

Mix HTTP_CONNECTOR and REST_CONNECTOR as appropriate — use REST_CONNECTOR when the API has an OpenAPI spec, HTTP_CONNECTOR for simpler or non-REST calls.

---

## EDGE DECLARATIONS

Port outPort names follow the pattern `Port N (out)`:

```xml
<Edge fromNode="REST_CONN:0" id="Edge0" outPort="Port 0 (out)" ... />
<Edge fromNode="REST_CONN:1" id="Edge1" outPort="Port 1 (out)" ... />
```

Input port:
```xml
<Edge ... inPort="Port 0 (in)" toNode="REST_CONN:0"/>
```

---

## METADATA

### Recommended output metadata for default output mapping

```xml
<Record name="RESTResponse" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <Field name="content" type="string"/>
    <Field name="statusCode" type="integer" trim="true"/>
    <Field name="errorMessage" type="string"/>
    <Field containerType="map" name="responseHeaders" type="string"/>
    <!-- Add pass-through fields from input as needed: -->
    <Field name="recordID" type="string"/>
</Record>
```

For pre-parsed JSON access (unique to REST_CONNECTOR):
```xml
    <Field name="contentJson" type="variant"/>
```

---

## GENERATION RULES FOR LLM

**REST_CONNECTOR is the default choice for new REST API integrations.** Use HTTP_CONNECTOR only when REST_CONNECTOR doesn't fit (see comparison in HTTP_CONNECTOR reference).

Always include:
- `type="REST_CONNECTOR"`
- `apiRootUrl` (base URL — use graph parameters)
- `endpoint` (API path)
- `requestMethod` (explicit, even for GET)

When OpenAPI spec is available:
- Set `openApiUrl` — it auto-loads endpoints, parameters, and schemas
- Populate attributes top-to-bottom: OpenAPI URL → endpoint → parameters → mappings

When using input port:
- Use `$out.2.paramName` in input mapping to set request parameters
- Use `$out.0.requestContent = writeJson(...)` for POST/PUT/PATCH body
- Use `$in.2.fieldName` in output mappings to pass through input context

Response handling:
- Use `responseMapping` for structured per-status-code JSON parsing (no downstream parser needed)
- Use `defaultOutputMapping` as fallback for unmatched status codes and errors
- Use `$in.0.contentJson` (variant) for pre-parsed JSON access in CTL — no `parseJson()` needed

Pagination:
- Configure the matching pagination type and parameters — no loop logic needed
- Set `Maximum number of requests` as a safety limit
- Set `Response data path` to the JSON node containing the data array

Rate limiting:
- Use built-in `rateLimitRequestsPerInterval` + `rateLimitTimeInterval`
- Fall back to CTL `sleep()` in input mapping only when built-in limiter is insufficient

Authentication:
- Store passwords/tokens in secure graph parameters
- Use `oAuth2Connection` for OAuth2 with automatic token refresh
- Use `bearerToken` or `apiKeyValue` with parameter references
- Use input mapping for dynamic per-request tokens

Do NOT:
- Use `requestContent` AND `requestBodyMapping` simultaneously — they conflict
- Forget `headerProperties` with `Accept=*/*` or `Content-Type=application/json` when needed
- Manually set `Content-Type: multipart/form-data` with multipart entities — auto-handled
- Build manual pagination loops — use built-in pagination
- Build manual rate limiting — use built-in rate limiter first
- Pre-encode URL parameters — request parameters are auto-encoded
- Confuse `$in.0` (response result) with `$in.2` (input record) in output mappings

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| Confusing `$in.0` and `$in.2` in output mapping | `$in.0` = response (content, statusCode), `$in.2` = input record pass-through |
| Building pagination loops with DATA_GENERATOR | Use built-in pagination — offset, page-based, or token-based |
| Building rate limiting with CTL sleep | Use `rateLimitRequestsPerInterval` + `rateLimitTimeInterval` attributes first |
| Using `parseJson()` on response in CTL | Use `$in.0.contentJson` (variant) for pre-parsed access — unique to REST_CONNECTOR |
| Missing `defaultOutputMapping` | Without it, unmatched status codes ≥300 fail the component silently |
| No `Maximum number of requests` on pagination | Set a safety limit to prevent infinite loops on misbehaving APIs |
| Using HTTP_CONNECTOR for a standard REST API | REST_CONNECTOR is the modern default — easier config, built-in pagination and rate limiting |
| Combining `requestContent` with `requestBodyMapping` | Use one or the other — they cannot coexist |
| Not populating attributes top-to-bottom with OpenAPI | OpenAPI URL must be set first, then endpoint, then parameters — order matters for auto-population |
| Forgetting `Response data path` in pagination | Component cannot detect empty pages without it — may loop indefinitely |
