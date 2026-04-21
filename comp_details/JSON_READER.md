# CloverDX JSON_READER — LLM Reference

## What it does
DOM-based JSON reader. Loads the entire document into memory, internally converts it to XML DOM, then extracts records using XPath-like mapping. Sends records to one or more output ports.

**Use for:** small-to-medium JSON files, complex or irregular structures best expressed with full XPath.
**Do not use for large files (>5–10 MB)** — entire document held in RAM. Use JSON_EXTRACT (SAX-based) instead.

Also known as **JSONReader** (display name). Component type string: `JSON_READER`.

**Key difference from XML_READER:** JSON has no attributes — XPath expressions **never contain `@`**. Everything is navigated as element paths.

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | optional | Port reading — one `byte`/`cbyte`/`string` field | One field only |
| Output 0 | ✓ | Successfully read records | Any |
| Output 1-N | optional | Additional output ports for nested structures | Any — each port can have different metadata |
| Last output port | optional | **Error port** — fixed format, see below | Template format |

**Error port metadata template** (`JSONReader_TreeReader_ErrPortWithFile`):

| Field | Type | Description |
|---|---|---|
| `port` | integer | Output port where data would go if correct |
| `recordNumber` | integer | Output record number (starts at 1, per port) |
| `fieldNumber` | integer | Field index (starts at 1) |
| `fieldName` | string | Field name |
| `value` | string | Value causing the error |
| `message` | string | Error message |
| `file` | string | Input file (optional — template without it: `ErrPortWithoutFile`) |

**Auto-propagated metadata: ✓** — JSONReader propagates metadata to output ports.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `fileURL` | yes | — | Source file. Supports graph params, zip, port read, dictionary. |
| `charset` | no | Auto (UTF-* autodetected) | Encoding. **Always set explicitly when reading from port or dictionary** — no autodetection in those modes. |
| `mapping` [attr-cdata] | one of | — | Inline XPath mapping XML |
| `mappingURL` | one of | — | External mapping file. Takes precedence if both set. |
| `implicitMapping` | no | `false` | When `true`: auto-maps JSON elements to same-named metadata fields. |
| `dataPolicy` | no | `strict` | `strict` / `controlled` (sends errors to error port if connected) / `lenient` |

## Mapping XML

Goes in `<attr name="mapping"><![CDATA[ ... ]]></attr>`.

### Root Context — mandatory fixed format

The first `<Context>` element **must** use one of exactly two `xpath` values:

```xml
<Context xpath="/root/object">   <!-- when JSON root is { ... } -->
<Context xpath="/root/array">    <!-- when JSON root is [ ... ] -->
```

This `/root/object` or `/root/array` prefix is an internal artefact of the JSON→XML conversion — it does not appear in output. All subsequent navigation is relative to this root.

### Context Tag — `<Context>`

```xml
<Context xpath="xpathExpression"
         outPort="N"
         parentKey="field1;field2"
         generatedKey="childField1;childField2"
         namespacePaths='prefix="URI"'>
```

| Attribute | Description |
|---|---|
| `xpath` | XPath navigating into the JSON tree. No `@` — JSON has no attributes. |
| `outPort` | Output port number. Optional — omit to use Context for navigation only. |
| `parentKey` | Semicolon-separated parent-level field names to propagate to child records. |
| `generatedKey` | Semicolon-separated field names on this level receiving the parent value. |
| `namespacePaths` | Namespace declarations for XPath functions: `namespacePaths='json-functions="http://www.cloveretl.com/ns/TagNameEncoder"'`. Required for `decode()`, `encode()`, `toJSON()`. |

### Mapping Tag — `<Mapping>`

```xml
<Mapping xpath="xpathExpression" cloverField="fieldName"/>
<!-- Map from input port field: -->
<Mapping inputField="inputFieldName" cloverField="outputFieldName"/>
```

| Attribute | Description |
|---|---|
| `xpath` | XPath expression. Never use `@`. Use element paths, `.`, `..`, `name()`, `text()`, etc. |
| `cloverField` | Output metadata field name |
| `inputField` | Maps an input port field to the output field (for port-reading modes) |

### XPath expressions — JSON specifics

```xml
<!-- Simple key value -->
<Mapping cloverField="id"       xpath="id"/>

<!-- Nested object -->
<Mapping cloverField="author"   xpath="user/name"/>

<!-- Current element value -->
<Mapping cloverField="value"    xpath="."/>

<!-- Parent element value (child Context referencing parent) -->
<Mapping cloverField="orderId"  xpath="../id"/>

<!-- Nested object path -->
<Mapping cloverField="newRows"  xpath="stats/newRows"/>

<!-- Count of children -->
<Mapping cloverField="count"    xpath="count(items)"/>

<!-- Node name (for structural analysis) -->
<Mapping cloverField="name"     xpath="name()"/>

<!-- Ancestor path building -->
<Mapping cloverField="path"     xpath="concat('/',string-join(ancestor::*/name(),'/'))" />

<!-- Depth -->
<Mapping cloverField="depth"    xpath="count(ancestor::*/name())"/>

<!-- Type detection: 'object' if has children, 'value' if leaf -->
<Mapping cloverField="type"
         xpath="concat(substring('object',1,number(not(count(child::*)=0))*string-length('object')),substring('value',1,number(count(child::*)=0)*string-length('value')))"/>
```

### Handling Arrays

Repeated JSON arrays at the same level: each array element produces one output record. Navigate into them by using the same name in the XPath:

```xml
<!-- commonArray: [ "hello", "hi", "howdy" ] -->
<Context xpath="commonArray" outPort="0">
    <Mapping xpath="." cloverField="field1"/>
</Context>

<!-- arrayOfArrays: [ ["val1","val2"], [""], ["val5","val6"] ] — nested array -->
<Context xpath="arrayOfArrays/arrayOfArrays" outPort="1">
    <Mapping xpath="." cloverField="field2"/>
</Context>
```

Array handling rules:
- Null values (`[]`) are **skipped** entirely — no output record produced
- Empty strings (`[""]`) produce a record with an empty string value
- Nested arrays: repeat the array name in XPath for each nesting level

### JSON key name encoding

Since JSON is converted to XML internally, JSON key names containing characters invalid in XML are encoded as `_xHHHH` (Unicode hex). Examples:
- `created_at` → `created_x005fat` (the `_` before `at` is encoded as `_x005f`)
- `@type` → `_x0040_type`

**To decode encoded names**, use the `decode()` function from the TagNameEncoder namespace:

```xml
<Context xpath="/root/object/map/*" outPort="0"
         namespacePaths='json-functions="http://www.cloveretl.com/ns/TagNameEncoder"'>
    <Mapping cloverField="key"   xpath="json-functions:decode(name())"/>
    <Mapping cloverField="value" xpath="."/>
</Context>
```

**Best practice:** verify actual encoded key names by running with `implicitMapping="true"` first when keys contain special characters.

### `toJSON()` function — extract subtree as JSON string

Extracts a JSON subtree as a serialized JSON string — useful for processing large JSON in chunks without loading the entire document model:

```xml
<Context xpath="/root/object">
    <Context xpath="orders/addresses" outPort="0"
             namespacePaths='json-functions="http://www.cloveretl.com/ns/TagNameEncoder"'>
        <Mapping cloverField="addresses" xpath="json-functions:toJSON(*)"/>
    </Context>
</Context>
```

Output: one record per address object, each containing a full JSON string `{"ROOT_GROUP": {...}}`.

Requires `namespacePaths='json-functions="http://www.cloveretl.com/ns/TagNameEncoder"'` on the containing `<Context>`.

## Real Sandbox Examples

### CLV_MCP_KWBASE / BasicFeatures — orders JSON from zip, 3 ports, parent key propagation
```xml
<Node charset="UTF-8"
      fileURL="zip:(${DATAIN_DIR}/OrdersJSON.zip)#Orders.json"
      implicitMapping="true"
      id="JSONREADER" type="JSON_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="/root/object">
    <Context xpath="orders" outPort="0">
        <Mapping cloverField="itemsCount" xpath="count(items)"/>

        <Context xpath="items" outPort="1">
            <Mapping cloverField="orderId" xpath="../id"/>
        </Context>

        <Context xpath="addresses" outPort="2">
            <Mapping cloverField="orderId" xpath="../id"/>
        </Context>
    </Context>
</Context>]]></attr>
</Node>
```

### DataManagerLib — parse HTTP API response from port, nested stats object
```xml
<Node charset="UTF-8"
      fileURL="port:$0.content:discrete"
      implicitMapping="true"
      id="PARSE_RESPONSE" type="JSON_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="/root/object">
    <Context xpath="members" outPort="0">
        <Mapping cloverField="newRows"       xpath="stats/newRows"/>
        <Mapping cloverField="editedRows"    xpath="stats/editedRows"/>
        <Mapping cloverField="approvedRows"  xpath="stats/approvedRows"/>
        <Mapping cloverField="committedRows" xpath="stats/committedRows"/>
        <Mapping cloverField="lastLoadRows"  xpath="stats/lastLoadRows"/>
    </Context>
</Context>]]></attr>
</Node>
```

### DataAnalyticsBundleLib — structural introspection (wildcard traverse all nodes)
```xml
<Node charset="${CHARSET}"
      fileURL="${READER_URL}"
      id="READ_SAMPLE_FILE" type="JSON_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="//*" outPort="0">
    <Mapping cloverField="name"   xpath="name()"/>
    <Mapping cloverField="parent" xpath="parent::*/name()"/>
    <Mapping cloverField="path"   xpath="concat('/',string-join(ancestor::*/name(),'/'))" />
    <Mapping cloverField="depth"  xpath="count(ancestor::*/name())"/>
    <Mapping cloverField="type"   xpath="concat(substring('object',1,number(not(count(child::*)=0))*string-length('object')),substring('value',1,number(count(child::*)=0)*string-length('value')))"/>
    <Mapping cloverField="value"  xpath="text()"/>
</Context>]]></attr>
</Node>
```
`xpath="//*"` matches every node in the document. Produces one record per structural node — used for JSON schema discovery.

### IntroExamples — Twitter API response from port (UTF-16, encoded key name)
```xml
<Node charset="UTF-16"
      fileURL="port:$0.content:discrete"
      id="JSONREADER" type="JSON_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="/root/object/statuses" outPort="0">
    <Mapping cloverField="tweet_text" xpath="text"/>
    <Mapping cloverField="created"    xpath="created_x005fat"/>  <!-- created_at encoded -->
    <Mapping cloverField="author"     xpath="user/name"/>
    <Mapping cloverField="id"         xpath="id"/>
</Context>]]></attr>
</Node>
```
`charset="UTF-16"` — API responses may not be UTF-8. `created_x005fat` = JSON key `created_at` with `_` before `at` encoded.

### Official example — reading list of JSON files from input port
```xml
<!-- fileURL="port:$0.fileName:source" — each input record is a file path to read -->
<Context xpath="/root/object" outPort="0">
    <Mapping cloverField="name"           xpath="firstname"/>
    <Mapping cloverField="orderDate"      inputField="orderDate"/>  <!-- from input port -->
    <Mapping cloverField="orderedProducts" xpath="products"/>       <!-- list field -->
</Context>
```
With `implicitMapping="true"`, other matching fields auto-map.

## fileURL Modes for Port Reading

```
fileURL="port:$0.content:discrete"   -- each input record IS the JSON document
fileURL="port:$0.filename:source"    -- each input record PROVIDES A PATH to a JSON file
fileURL="port:$0.content:stream"     -- continuous JSON stream from port
```

`source` mode: input field must be `string` type (file path). `discrete`/`stream`: input field must be `byte`, `cbyte`, or `string`.

## Metadata Field Name Warning

If output metadata field names contain underscore `_`, JSONReader warns because `_` is an illegal character in the mapping XPath. Options:
- Remove the underscore
- Replace with dash: `my-field`
- Use Unicode representation in XPath: `_x005f` represents `_`

## JSON_READER vs JSON_EXTRACT

| | JSON_READER | JSON_EXTRACT |
|---|---|---|
| Parser | DOM (full document in RAM) | SAX (streaming) |
| Memory | Entire document | Low — streaming |
| File size | Small-medium (<5–10 MB) | Any size |
| XPath support | Full XPath + functions | Limited element paths only |
| `count()`, `name()`, `ancestor::*` | ✓ | ✗ |
| No `@` attributes | ✓ (JSON has none) | ✓ |
| `decode()`/`toJSON()` functions | ✓ | ✗ |
| Variant output | ✗ | ✓ (`xmlFields="-"`) |
| Array handling | `arrayName/arrayName` for nested | Separate `<Mapping element="json_array">` |
| Error port | ✓ | ✗ |
| Auto-propagated metadata | ✓ | ✗ |

## Mistakes

| Wrong | Correct |
|---|---|
| `xpath="@attribute"` | JSON has no attributes — never use `@` in JSON_READER XPath |
| `xpath="/orders"` (XML-style root) | Always start with `/root/object` or `/root/array` |
| `xpath="/root/object"` when JSON root is an array | Use `xpath="/root/array"` |
| `xpath="created_at"` for JSON key `created_at` | May need `xpath="created_x005fat"` — verify with `implicitMapping="true"` first |
| Using on large JSON files | Use JSON_EXTRACT for files >5–10 MB |
| Missing `charset` when reading from port/dictionary | **Required** — no auto-detection in those modes |
| `mappingURL` and `mapping` both set | `mappingURL` takes precedence |
| Underscore `_` in metadata field names | Causes XPath conflict — use `-` or `_x005f` instead |
| Nested array: `xpath="outerArray/innerArray"` | Correct only if inner array name matches. For self-nested: `xpath="arrayName/arrayName"` |
| Null array values `[]` expecting empty string | Null values are skipped entirely; `[""]` produces an empty string record |
