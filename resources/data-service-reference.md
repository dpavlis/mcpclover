description: Reference for CloverDX REST data services built as .rjob graphs: restJob graph nature, EndpointSettings and HTTP method configuration, request/response metadata flow, response status mapping, URL/query/header/body parameter handling, and deployment-relevant structure needed to generate or edit API-facing graphs correctly.

# Data Service (.rjob) Reference — LLM Graph Building

## What is a Data Service?

A Data Service is a CloverDX graph published as a REST API endpoint. The file extension is `.rjob`. It lives in `${PROJECT}/data-service/` by default. Supports GET, POST, PUT, PATCH, DELETE.

## .rjob File Structure

An `.rjob` is XML identical to a `.grf` graph with these additions:

```xml
<Graph name="MyService" nature="restJob" ...>
  <Global>
    <EndpointSettings>...</EndpointSettings>
    <RestJobResponseStatus>...</RestJobResponseStatus>
    <!-- normal: Metadata, Connection, GraphParameters, Dictionary -->
  </Global>
  <!-- normal: Phase, Node, Edge -->
</Graph>
```

**Critical:** `nature="restJob"` on the `<Graph>` element distinguishes .rjob from .grf.

## EndpointSettings Block

```xml
<EndpointSettings>
  <UrlPath>/my-prefix/my-endpoint</UrlPath>
  <EndpointName>Human-readable title</EndpointName>
  <Description>Markdown-like description</Description>
  <RequestMethod name="GET"/>
  <RequestMethod name="POST"/>
  <!-- Parameters: -->
  <RequestParameter id="RestJobParameter0"
      name="paramName"
      location="query"       <!-- or "path" -->
      type="string"          <!-- string|date|num_int|num_long|num_number|num_decimal|boolean|enumeration|binary_file|text_file -->
      required="true"
      label="UI Label"
      description="Human description"
      hint="placeholder"
      defaultValue="val"
      sensitive="false"/>
  <!-- Path params use {name} in UrlPath: /items/{itemId} -->
  <!-- Regex path params: {filename:.+} matches slashes -->
  <!-- Enum parameter example: -->
  <RequestParameter id="RestJobParameter1" name="format" type="enumeration" location="query">
    <Values>
      <Value>json</Value>
      <Value>csv</Value>
    </Values>
  </RequestParameter>
  <!-- Validation rules for numeric params: -->
  <RequestParameter id="RestJobParameter2" name="count" type="num_int" location="query">
    <ValidationRules>
      <ValidationRule type="minValue" value="0"/>
      <ValidationRule type="maxValue" value="100"/>
    </ValidationRules>
  </RequestParameter>
</EndpointSettings>
```

## RestJobResponseStatus Block

Always include this standard block:

```xml
<RestJobResponseStatus>
  <JobError>
    <ReasonPhrase>Job failed</ReasonPhrase>
    <StatusCode>500</StatusCode>
  </JobError>
  <Success>
    <StatusCode>200</StatusCode>  <!-- or 201, 204 etc -->
  </Success>
  <ValidationError>
    <ReasonPhrase>Request validation failed</ReasonPhrase>
    <StatusCode>400</StatusCode>
  </ValidationError>
</RestJobResponseStatus>
```

## Special Components

### RESTJOB_INPUT (Input component)

```xml
<Node guiName="Input" guiX="80" guiY="10" id="RESTJOB_INPUT0"
      restJobInput="true"
      type="RESTJOB_INPUT"
      requestFormat="JSON"/>   <!-- JSON (default since 5.12), STRING, or omit for BINARY -->
```

**Output ports:**
- `Port 0 (Parameters)` — auto-generates metadata from EndpointSettings parameters. Connect to downstream component to receive typed parameter values.
- `Port 1 (Body)` — request body. Metadata depends on `requestFormat`:
  - JSON → single `variant` field `body`
  - STRING → single `string` field `body`
  - BINARY → single `byte` field `body` (chunked, 1024B default)

### RESTJOB_OUTPUT (Output component)

```xml
<Node guiName="Output" guiX="1100" guiY="10" id="RESTJOB_OUTPUT0"
      restJobOutput="true"
      type="RESTJOB_OUTPUT"
      responseFormat="JSON"       <!-- JSON, XML, CSV, CUSTOM, or FILE -->
      metadataName="false"        <!-- true=wrap in {"MetaName":[...]}, false=anonymous array -->
      topLevelArray="true"        <!-- false=single object (fails if >1 record) -->
      attachment="false"/>        <!-- true=Content-Disposition: attachment -->
```

**Input ports:** Connect edges carrying response records. Port 0, 1, 2... Records auto-serialized in port order.

**For CUSTOM output format:** Do NOT connect edges to Output. Use a writer component with `fileURL="response:body"` instead. Set content type via CTL `setResponseContentType()`.

**For FILE output format:** No edges to Output. Set `responseFormat="FILE"` and `fileURL="${DATATMP_DIR}/result-${RUN_ID}.xlsx"`.

## Input Access Patterns

### Pattern 1: Parameters as graph parameters
No edge needed from RESTJOB_INPUT. Use `${paramName}` in component attributes directly. Use `${request.PARAM}` prefix if name conflicts with a graph parameter.

### Pattern 2: Parameters as data records
Connect edge from `Port 0 (Parameters)` to a REFORMAT or other component. Records arrive with fields matching parameter names/types. Auto type-conversion when edge is connected.

### Pattern 3: Request body via port
Connect edge from `Port 1 (Body)`. For JSON: use variant CTL functions. For binary: pipe to a reader via `port:$0.body:stream`.

### Pattern 4: Request body via URL
Use `request:body` as fileURL of a reader component (e.g. FLAT_FILE_READER, JSON_EXTRACT). Stream is consumed once — second read fails. For multipart: `request:part:partName`.

### Pattern 5: CTL functions (see full reference below)

## CTL Data Service HTTP Library — Complete Function Reference

All functions below are available ONLY in .rjob (Data Service) context.

### Request Functions

#### getRequestParameter
```
string getRequestParameter(string param)
```
Returns value of GET or POST parameter by name (always string). Works for both query params and path params. Returns null if missing.

#### getRequestParameters
```
string[] getRequestParameters(string name)
map[string,string] getRequestParameters()
```
Overload 1: Returns list of values for multivalue parameter (e.g. `?name=doe&name=john` → `["doe","john"]`).
Overload 2 (no args): Returns map of all parameter name→value pairs. For multivalue params, only one value is in the map — use the string[] overload for all values.

#### getRequestParameterNames
```
string[] getRequestParameterNames()
```
Returns names of all GET/POST parameters (including path params).

#### getRequestBody
```
string getRequestBody()
```
Returns entire request body as a string. **Stores in memory** — not recommended for large payloads. Can be called repeatedly (unlike `request:body` stream which is consumed once).

#### getRequestHeader
```
string getRequestHeader(string headerField)
```
Returns value of a single HTTP request header. Returns null if not present. Case-insensitive field name.

#### getRequestHeaders
```
map[string,string] getRequestHeaders()
string[] getRequestHeaders(string param)
```
Overload 1 (no args): Returns map of all headers. For multi-value headers (e.g. multiple Accept), only ONE value is in the map.
Overload 2 (string): Returns list of ALL values for a multi-value header (e.g. `getRequestHeaders("Accept")` → `["text/plain","text/html","application/json"]`).

#### getRequestHeaderNames
```
string[] getRequestHeaderNames()
```
Returns names of all HTTP request header fields (lowercase).

#### getRequestMethod
```
string getRequestMethod()
```
Returns HTTP method: `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, or `"DELETE"`.

#### getRequestContentType
```
string getRequestContentType()
```
Returns Content-Type of the request (e.g. `"application/x-www-form-urlencoded"`, `"application/json"`).

#### getRequestEncoding
```
string getRequestEncoding()
```
Returns encoding from Content-Type header charset parameter. Returns null if not specified. E.g. for `Content-Type: text/html; charset=UTF-8` returns `"UTF-8"`.

#### getRequestClientIPAddress
```
string getRequestClientIPAddress()
```
Returns client IP address (e.g. `"127.0.0.1"` or `"0:0:0:0:0:0:0:1"` for localhost).

#### getRequestPartFilename
```
string getRequestPartFilename(string paramName)
```
Returns original filename from a multipart file upload. `paramName` is the HTML form field name / request parameter name.

#### setRequestEncoding
```
void setRequestEncoding(string encoding)
```
Sets encoding for POST request body parsing. **Must be called in `init()`.** E.g. `setRequestEncoding("utf-8")`, `setRequestEncoding("iso-8859-2")`.

### Response Functions

#### setResponseStatus
```
void setResponseStatus(integer statusCode)
void setResponseStatus(integer statusCode, string message)
```
Overrides the default HTTP response status code (and optional reason phrase). Overrides RestJobResponseStatus defaults. E.g. `setResponseStatus(201)`, `setResponseStatus(414, "URI Too Long")`.

#### setResponseBody
```
void setResponseBody(string body)
```
Sets HTTP response body directly. If both `setResponseBody()` and `response:body` writer are used, the writer wins. Use with CUSTOM output format.

#### setResponseContentType
```
void setResponseContentType(string contentType)
```
Sets Content-Type response header. Overrides value from Output configuration. E.g. `setResponseContentType("text/plain")`, `setResponseContentType("application/json")`.

#### setResponseEncoding
```
void setResponseEncoding(string encoding)
```
Sets response body encoding. Used when body is set via `setResponseBody()`. E.g. `setResponseEncoding("UTF-8")`.

#### setResponseHeader
```
void setResponseHeader(string field, string value)
```
Sets a response header. If header already exists, **replaces** the value. E.g. `setResponseHeader("Server", "BOA")`.

#### addResponseHeader
```
void addResponseHeader(string name, string value)
```
**Adds** a response header (does not replace — allows multiple values for same header). If `name` is null/empty or `value` is null, header is not added. E.g. `addResponseHeader("Content-Language", "fr")`.

#### containsResponseHeader
```
boolean containsResponseHeader(string headerField)
```
Checks if a user-added response header exists. Does NOT check server-added headers (e.g. `Server: Apache`). Case-insensitive.

#### getResponseContentType
```
string getResponseContentType()
```
Returns current response Content-Type value (e.g. `"application/json"`).

#### getResponseEncoding
```
string getResponseEncoding()
```
Returns current response encoding (e.g. `"iso-8859-1"`).

### Error pattern: fail-fast with custom status
```ctl
setResponseStatus(404, "Resource not found");
raiseError("Item " + id + " does not exist");
```
`raiseError()` terminates graph execution. The status code set before `raiseError()` is returned.

## Output / Response Patterns

### JSON auto-serialization (most common)
Connect edge(s) to RESTJOB_OUTPUT input ports. Field names become JSON keys.

**JSON formatting options:**
- `metadataName="true"` (default): wraps output as `{"MetadataRecordName": [{...}, {...}]}`
- `metadataName="false"`: anonymous array `[{...}, {...}]` — use when only one output port
- `topLevelArray="false"`: single object `{...}` — fails if >1 record arrives

**Variant shortcut:** If exactly one edge with one `variant` field, the variant value is serialized directly as JSON (no wrapping). Useful for building complex JSON in CTL and passing it through.

**Multiple output ports:** Data from ports concatenated in order. Port 0 = "Books": [...], Port 1 = "Movies": [...] etc. Each port's records grouped under their metadata name.

### CSV auto-serialization
Set `responseFormat="CSV"`. Only ONE port allowed. Content-Type auto-set to `text/csv`.

### Custom serialization
Set `responseFormat="CUSTOM"`. Use a writer with `fileURL="response:body"`. Default Content-Type is `application/octet-stream` — override recommended. Can start streaming before all components finish (useful for large responses, but partial response on error).

### File response
Set `responseFormat="FILE"` and `fileURL="path/to/file"`. Use `${RUN_ID}` in temp filenames to avoid parallel-request collisions. Content-Type auto-detected from extension.

### Static file publishing
Set `responseFormat="FILE"` and point to a static file. No graph logic needed — just Input and Output components.

## Common Patterns from DWHExample

### Pattern A: DB query → JSON response
```
RESTJOB_INPUT:Parameters → REFORMAT(build SQL) → DB_INPUT_TABLE → RESTJOB_OUTPUT:0
```
Use `url="port:$0.query:discrete"` on DB_INPUT_TABLE to read SQL from upstream edge.

### Pattern B: DB query → CSV via stream
```
RESTJOB_INPUT → [Phase 0] DB_INPUT_TABLE → REFORMAT → FLAT_FILE_WRITER(port:$0.content:discrete) → [Phase N] RESTJOB_OUTPUT
```
FLAT_FILE_WRITER writes to a byte stream edge. RESTJOB_OUTPUT in a later phase with `responseFormat="CSV"`.

### Pattern C: Custom response with CTL
```
RESTJOB_INPUT → GET_JOB_INPUT(CTL: getRequestParameter + setResponseBody + setResponseContentType) → RESTJOB_OUTPUT(CUSTOM)
```
No edges to Output. All response built in CTL.

### Pattern D: Read debug/file data
```
RESTJOB_INPUT → GET_JOB_INPUT(validate params) → CLOVER_READER(fileURL from params) → RESTJOB_OUTPUT:0(JSON)
```

### Pattern E: File upload processing
```
RESTJOB_INPUT:Body → READER(fileURL="port:$0.body:stream" or "request:part:paramName") → transform → RESTJOB_OUTPUT
```
Use `request:part:paramName` for multipart file uploads. Get original filename with `getRequestPartFilename("paramName")`.

## Metadata Patterns in .rjob

Same rules as .grf: inline `<Record>` in `<Metadata>` or external `.fmt` files via `fileURL`.

For byte-stream piping (CSV pattern), use:
```xml
<Metadata id="MetaResult">
  <Record eofAsDelimiter="true" name="result" type="delimited">
    <Field name="content" type="byte"/>
  </Record>
</Metadata>
```

For custom metadata on body edge: must have one `byte`/`cbyte`/`string` field. Mixed or delimited ok — whole body in single field of one record.

## Phases

- RESTJOB_INPUT is always in phase 0 (lowest)
- RESTJOB_OUTPUT can be in a higher phase to ensure all data is ready before serialization
- If reader component is in same phase as Input, body is streamed (good for large payloads)
- If reader is in a later phase, body is buffered first
- Auto-serialization happens AFTER all components finish — so errors during processing set correct HTTP error codes

## Graph Parameters

Same as .grf: `<GraphParameterFile fileURL="workspace.prm"/>` plus request parameters are auto-resolved as graph parameters. Use `${request.PARAM}` prefix if name conflicts with a graph parameter.

## Connections, Subgraphs

- Database connections: same `<Connection>` as .grf
- Subgraphs work inside .rjob BUT cannot access HTTP context (no request/response from subgraph). Subgraphs can be used as transforming components only.
- ExecuteGraph/ExecuteJobflow: HTTP context NOT passed to child jobs

## Error Handling

1. Missing required params → automatic 400 (ValidationError)
2. Graph exception → automatic 500 (JobError)
3. Custom: call `setResponseStatus(code, "message")` then `raiseError("details")` for controlled failure
4. Infrastructure problems generate built-in error codes — check app server access.log for connectivity issues

## Data Apps

Data Services can be exposed as Data Apps (simple web UI). Parameters become form widgets:
- string → text input (validation: minLength, maxLength, regex, predefined rules: email/URL/digits/letters)
- date → calendar picker (accepts YYYY-MM-DD, YYYY-MM-DD HH:mm, YYYY-MM-DD HH:mm:ss, YYYY-MM-DD HH:mm:ss.SSS; sent as ISO 8601 in server timezone)
- num_int/num_long/num_number/num_decimal → validated number input (minValue/maxValue validation)
- boolean → checkbox (always sent, no required marking)
- enumeration → dropdown (static Values or Dynamic Values from another Data Service endpoint)
- binary_file/text_file → file upload (accessed via `request:part:paramName`)

Data App detection in CTL: `getRequestHeader("X-CLOVER-DATA-APP") == "true"`

Data Manager integration headers: `X-Clover-Data-Set-Code` (data set code), `X-Clover-Data-Set-Batch-Key` (batch key if batching enabled).

Custom JS injection: create .js file in sandbox, set "Path to injected JavaScript file" property. Use `cleanupHook()` for cleanup, `beforeSubmitHook()` for pre-submit validation (return truthy to allow submit).

Programmatic form value setting: `document.getElementById('paramName_input').value = "val"; .dispatchEvent(new Event("input"))`. For checkboxes: `.checked = true; .dispatchEvent(new Event("change"))`.

## MCP Tool Workflow for Building .rjob

1. Use `get_workflow_guide` (if available) for general graph workflow
2. Use `get_component_info` for RESTJOB_INPUT and RESTJOB_OUTPUT types
3. Use `plan_graph` — same as .grf but set nature="restJob" in the written XML
4. Use `write_file` to create the .rjob in `data-service/` directory
5. Publishing requires Server UI or Designer — no MCP tool for publish

## Key Differences from .grf

| Aspect | .grf | .rjob |
|--------|------|-------|
| `nature` attribute | (absent or "graph") | `"restJob"` |
| `<EndpointSettings>` | absent | required |
| `<RestJobResponseStatus>` | absent | required |
| RESTJOB_INPUT/OUTPUT | not used | required |
| File location | `graph/` | `data-service/` |
| Extension | `.grf` | `.rjob` |
| Execution | scheduled/manual | HTTP request triggered |
| HTTP context CTL | not available | available (22 functions) |

## Minimal .rjob Template (GET → JSON)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph name="MyService" nature="restJob" showComponentDetails="true">
<Global>
<EndpointSettings>
  <UrlPath>/my-prefix/my-endpoint</UrlPath>
  <EndpointName>My Service</EndpointName>
  <RequestMethod name="GET"/>
</EndpointSettings>
<RestJobResponseStatus>
  <JobError><ReasonPhrase>Job failed</ReasonPhrase><StatusCode>500</StatusCode></JobError>
  <Success><StatusCode>200</StatusCode></Success>
  <ValidationError><ReasonPhrase>Request validation failed</ReasonPhrase><StatusCode>400</StatusCode></ValidationError>
</RestJobResponseStatus>
<Metadata id="MetaOutput">
  <Record fieldDelimiter="|" name="output" recordDelimiter="\n" type="delimited">
    <Field name="message" type="string"/>
  </Record>
</Metadata>
<GraphParameters>
  <GraphParameterFile fileURL="workspace.prm"/>
</GraphParameters>
<Dictionary/>
</Global>
<Phase number="0">
<Node guiName="Input" guiX="80" guiY="25" id="RESTJOB_INPUT0" restJobInput="true" type="RESTJOB_INPUT"/>
<Node guiName="Generate Response" guiX="400" guiY="200" id="GENERATE_RESPONSE" type="GET_JOB_INPUT">
  <attr name="mapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.message = "Hello from Data Service";
    return ALL;
}]]></attr>
</Node>
<Node guiName="Output" guiX="800" guiY="25" id="RESTJOB_OUTPUT0"
      restJobOutput="true" type="RESTJOB_OUTPUT"
      responseFormat="JSON" metadataName="false" topLevelArray="false"/>
<Edge fromNode="GENERATE_RESPONSE:0" guiRouter="Manhattan" id="Edge0"
      inPort="Port 0 (in)" metadata="MetaOutput" outPort="Port 0 (out)" toNode="RESTJOB_OUTPUT0:0"/>
</Phase>
</Graph>
```

## Minimal .rjob Template (POST JSON body → JSON response)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph name="ProcessJSON" nature="restJob" showComponentDetails="true">
<Global>
<EndpointSettings>
  <UrlPath>/my-prefix/process</UrlPath>
  <EndpointName>Process JSON</EndpointName>
  <RequestMethod name="POST"/>
</EndpointSettings>
<RestJobResponseStatus>
  <JobError><ReasonPhrase>Job failed</ReasonPhrase><StatusCode>500</StatusCode></JobError>
  <Success><StatusCode>200</StatusCode></Success>
  <ValidationError><ReasonPhrase>Request validation failed</ReasonPhrase><StatusCode>400</StatusCode></ValidationError>
</RestJobResponseStatus>
<Metadata id="MetaBody">
  <Record name="body" type="delimited">
    <Field name="body" type="string" eofAsDelimiter="true"/>
  </Record>
</Metadata>
<Metadata id="MetaOutput">
  <Record fieldDelimiter="|" name="output" recordDelimiter="\n" type="delimited">
    <Field name="status" type="string"/>
    <Field name="result" type="string"/>
  </Record>
</Metadata>
<GraphParameters>
  <GraphParameterFile fileURL="workspace.prm"/>
</GraphParameters>
<Dictionary/>
</Global>
<Phase number="0">
<Node guiName="Input" guiX="80" guiY="25" id="RESTJOB_INPUT0"
      restJobInput="true" type="RESTJOB_INPUT" requestFormat="JSON"/>
<Node guiName="Process" guiX="400" guiY="200" id="PROCESS" type="REFORMAT">
  <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    $out.0.status = "ok";
    $out.0.result = getRequestBody();
    return ALL;
}]]></attr>
</Node>
<Node guiName="Output" guiX="800" guiY="25" id="RESTJOB_OUTPUT0"
      restJobOutput="true" type="RESTJOB_OUTPUT"
      responseFormat="JSON" metadataName="false" topLevelArray="false"/>
<Edge fromNode="RESTJOB_INPUT0:1" guiRouter="Manhattan" id="Edge0"
      inPort="Port 0 (in)" metadata="MetaBody" outPort="Port 1 (Body)" toNode="PROCESS:0"/>
<Edge fromNode="PROCESS:0" guiRouter="Manhattan" id="Edge1"
      inPort="Port 0 (in)" metadata="MetaOutput" outPort="Port 0 (out)" toNode="RESTJOB_OUTPUT0:0"/>
</Phase>
</Graph>
```
