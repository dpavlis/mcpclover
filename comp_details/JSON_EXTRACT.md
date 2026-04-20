# CloverDX JSON_EXTRACT — LLM Reference

## What it does
SAX-streaming JSON reader. Maps JSON tree structure to one or more output ports via declarative mapping XML.
Lower memory than JSON_READER (no DOM). Internally converts JSON→XML and uses the same mapping engine as XML_EXTRACT.
Use for large JSON files, HTTP/REST response parsing, or hierarchical JSON → multiple output ports.

## Ports
- Input 0: optional — one field (`byte`, `cbyte`, or `string`) for port reading
- Output 0: required. Additional output ports 1-N: required if mapping sends records to them.
No metadata propagation. No metadata templates. Each output port can have different metadata.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `sourceUri` | yes | File path, port read, or dictionary. See sourceUri patterns below. |
| `mapping` [attr-cdata] | one of | Inline mapping XML |
| `mappingURL` | one of | External mapping file path. Takes precedence over `mapping` if both set. |
| `schema` | no | Path to equivalent XSD schema file — for visual mapping editor. |
| `useNestedNodes` | no | Default `true`. When `false`, only explicitly mapped elements are extracted. Prevents name collision issues in nested JSON. |
| `trim` | no | Default `true`. Strip leading/trailing whitespace from string values. |
| `skipRows` | no | Number of records to skip from beginning of input. |
| `numRecords` | no | Max records to read total across all source files. |
| `charset` | no | Character encoding. **Always set explicitly** — do not rely on system default. |

**Best practice:** Always specify `charset` explicitly (e.g. `charset="UTF-8"`).

**Max string field size:** Default 20 MB per field. Increase if parsing very large string values.

**Null values:** Since version 5.11.0, null JSON values are output as null (not converted to empty string).

## sourceUri Patterns

```xml
<!-- File on disk -->
sourceUri="${DATAIN_DIR}/data.json"

<!-- Read JSON from upstream port (HTTP_CONNECTOR or REST_CONNECTOR response) -->
sourceUri="port:$0.content:discrete"    <!-- complete document per token — most common -->
sourceUri="port:$0.content:stream"      <!-- streaming — for very large responses -->

<!-- From dictionary -->
sourceUri="dict:myDictEntry"
```

`port:$0.content:discrete` is the canonical pattern for parsing HTTP/REST API responses.

## Mapping XML

Goes in `<attr name="mapping"><![CDATA[ ... ]]></attr>`.

### Flat JSON object → scalar fields on one output port
```xml
<Mappings>
    <Mapping element="json_object" outPort="0"
             xmlFields="{}field1;{}field2;{}field3"
             cloverFields="field1;field2;field3">
    </Mapping>
</Mappings>
```
- `element`: JSON node type — `json_object`, `json_array`, `json_string`, `json_number`, `json_boolean`
- `xmlFields`: `{}fieldName` — the `{}` namespace prefix is required
- `cloverFields`: output metadata field names in matching order
- Fields are semicolon-separated in both lists

### Capturing a JSON subtree as a single variant field

Use `xmlFields="-"` (a literal dash) with a single `variant`-typed cloverField to capture the **entire matched JSON element** — including all nested structure — into one variant output field.

**Output metadata** must declare the field as `type="variant"`:
```xml
<Field name="arrayElem" type="variant"/>
```

**Mapping:**
```xml
<Mappings>
    <Mapping element="json_array">
        <Mapping element="json_array" outPort="0"
                 xmlFields="-"
                 cloverFields="arrayElem">
        </Mapping>
    </Mapping>
</Mappings>
```

**Real example (fixExamples.grf):** Reading a JSONL training set where each record is an array element containing a full JSON object:
```xml
<Node sourceUri="${DATAIN_DIR}/CTL_LoRA_training_set_1.json"
      schema="${META_DIR}/CTL_LoRA_training_set_3_json"
      type="JSON_EXTRACT">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="json_array">
        <Mapping element="json_array" outPort="0"
                 xmlFields="-"
                 cloverFields="arrayElem">
        </Mapping>
    </Mapping>
</Mappings>
]]></attr>
</Node>
```

**Accessing variant fields in downstream CTL (REFORMAT):**
```ctl
// $in.0.arrayElem is type variant — the entire JSON object/array is accessible
variant msg = $in.0.arrayElem["messages"];             // navigate into object by key

$out.0.system    = cast(msg[0]["content"], string);    // array index + object key, cast to string
$out.0.user      = cast(msg[1]["content"], string);
$out.0.assistant = cast(msg[2]["content"], string);
```

**Variant navigation and type extraction:**

JSON values stored in variant are **already typed** by the JSON parser — they are not raw strings. The types are:

| JSON type | CTL variant internal type |
|---|---|
| string | `string` |
| integer number | `long` |
| float number | `number` |
| boolean | `boolean` |
| null | `null` |

To assign a variant value to a strongly-typed CTL variable, or pass it as a typed parameter, use `cast(variant, type)`. This is the **only** valid conversion from variant to a strong type — `toInteger()`, `toBoolean()`, `toDouble()` etc. do **not** exist in CTL2.

```ctl
// Navigate into variant — result is still variant
variant v    = $in.0.data["key"];       // object field
variant elem = $in.0.data[0];           // array element
variant deep = $in.0.data["x"][1]["y"]; // chained access

// Cast variant → strong type for assignment or typed parameters
string  s = cast($in.0.data["name"],    string);   // JSON string → string
long    l = cast($in.0.data["count"],   long);     // JSON integer → long (JSON ints are long)
integer i = cast($in.0.data["count"],   integer);  // JSON integer → integer (if value fits)
number  n = cast($in.0.data["price"],   number);   // JSON float → number (double)
boolean b = cast($in.0.data["enabled"], boolean);  // JSON boolean → boolean

// Null-safe: cast of a null variant produces null, not an exception
string safe = cast($in.0.data["maybeNull"], string);  // null variant → null string
```

**Do NOT use `cast()` between strong types** — it is only for `variant → strong type`. Between strong types, use the dedicated conversion functions: `long2integer()`, `decimal2integer()`, `num2str()`, etc.

```ctl
// WRONG — cast between strong types:
integer wrong = cast(someDecimal, integer);      // compile error
// CORRECT:
integer right = decimal2integer(someDecimal);

// WRONG — non-existent functions:
integer bad = toInteger($in.0.data["n"]);       // toInteger() does not exist
boolean bad2 = toBoolean($in.0.data["flag"]);   // toBoolean() does not exist
// CORRECT:
integer ok  = cast($in.0.data["n"],    integer);
boolean ok2 = cast($in.0.data["flag"], boolean);
```

### JSON array of objects → one record per array element
```xml
<Mappings>
    <Mapping element="json_array">
        <Mapping element="json_object" outPort="0"
                 xmlFields="{}name;{}value"
                 cloverFields="name;value">
        </Mapping>
    </Mapping>
</Mappings>
```

### Nested JSON → parent+child pattern (parentKey / generatedKey)
```xml
<Mappings>
    <Mapping element="json_object" outPort="0"
             xmlFields="{}orderId;{}orderDate"
             cloverFields="orderId;orderDate">
        <Mapping element="items" outPort="1"
                 xmlFields="{}productCode;{}quantity"
                 cloverFields="productCode;quantity"
                 parentKey="orderId"
                 generatedKey="orderId">
        </Mapping>
    </Mapping>
</Mappings>
```
- `parentKey`: field name in parent output record to propagate to child
- `generatedKey`: field name in child output record that receives the parent value

### useNestedNodes — name collision behaviour

When `useNestedNodes="true"` (default) and the same element name appears at multiple nesting levels, **SAX parsing returns the first occurrence found** — which may not be the one at the intended level.

**Example:** JSON with `id` at both `result.groups.id` and `result.id`:
```json
{"root": {"result": {"groups": {"id": "groupID"}, "id": "resultID"}}}
```

- Mapping at `result` level with automap, `useNestedNodes=true` → returns `groupID` (first found in SAX traversal)
- Mapping at `result` level with automap, `useNestedNodes=false` → returns `resultID` (only direct child)
- Mapping at `result.id` level, `useNestedNodes=true` → returns **both** `groupID` and `resultID` (two records)
- Mapping at `result.id` level, `useNestedNodes=false` → returns only `resultID`

**Rule:** When element names repeat at multiple levels and you need a specific one, either set `useNestedNodes="false"` or write an explicit nested `<Mapping>` path targeting the correct level.

## Typical Pattern: HTTP_CONNECTOR → JSON_EXTRACT

```xml
<!-- Step 1: call API -->
<Node id="GET_DATA" type="HTTP_CONNECTOR" url="https://api.example.com/data"/>

<!-- Step 2: parse JSON response -->
<Node id="PARSE_JSON" sourceUri="port:$0.content:discrete"
      charset="UTF-8" type="JSON_EXTRACT">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="json_object" outPort="0"
             xmlFields="{}id;{}name;{}status"
             cloverFields="id;name;status">
    </Mapping>
</Mappings>]]></attr>
</Node>

<Edge fromNode="GET_DATA:0" outPort="Port 0 (output)" toNode="PARSE_JSON:0" inPort="Port 0 (input)"/>
<Edge fromNode="PARSE_JSON:0" outPort="Port 0 (out)" toNode="NEXT:0" inPort="Port 0 (in)"/>
```

## Decision Guide

| Scenario | Use |
|---|---|
| Parse REST/HTTP JSON response per token | `sourceUri="port:$0.content:discrete"` |
| Large JSON file, low memory | JSON_EXTRACT (SAX) |
| Small JSON, complex JSONPath filtering | JSON_READER instead |
| Nested objects to multiple ports | Nested `<Mapping>` with `parentKey`/`generatedKey` |
| Capture entire JSON subtree for later navigation | `xmlFields="-"` with `variant` output field |
| Name collision in nested JSON | `useNestedNodes="false"` |
| Array of flat objects | Outer `json_array` Mapping, inner `json_object` Mapping |

## Mistakes

| Wrong | Correct |
|---|---|
| `xmlFields="field1;field2"` (no `{}` prefix) | `xmlFields="{}field1;{}field2"` — `{}` required |
| `xmlFields="-"` with non-variant output field | Field must be `type="variant"` |
| `sourceUri="port:0.content"` | `sourceUri="port:$0.content:discrete"` — `$` and `:discrete` required |
| `element="object"` | `element="json_object"` — full `json_` prefix required |
| Omitting `charset` | Always set explicitly, e.g. `charset="UTF-8"` |
| `toInteger($in.0.v["n"])` or `toBoolean($in.0.v["b"])` | These functions do not exist in CTL2 — use `cast($in.0.v["n"], integer)` / `cast($in.0.v["b"], boolean)` |
| `cast(someDecimal, integer)` — casting between strong types | `cast()` is only for `variant → strong type`. Use `decimal2integer()`, `long2integer()` etc. between strong types |
| `toString($in.0.v["field"])` for typed output fields | `toString()` outputs `"null"` string for null; use `cast($in.0.v["field"], string)` for proper typed extraction |
| Reading nested same-name element with default `useNestedNodes=true` | SAX returns first match found, not necessarily the correct level — use `useNestedNodes="false"` or explicit nested path |
| `mappingURL` and `mapping` both set | `mappingURL` takes precedence — remove `mapping` to avoid confusion |
| Expecting null JSON values as empty strings | Since 5.11.0 nulls are output as null, not `""` — check downstream null handling |
