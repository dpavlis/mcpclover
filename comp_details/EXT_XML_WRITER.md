# CloverDX EXT_XML_WRITER — LLM Reference

## What it does
Writes records from one or more input ports into a structured XML file.
Combines multiple input streams into a single nested XML document via a declarative mapping that defines the XML tree structure, port-to-element bindings, key-based JOIN between parent and child elements, and field-to-value assignments.

No CTL transformation. Structure is entirely driven by the `mapping` XML.

Also known as **XMLWriter** (display name). Component type string: `EXT_XML_WRITER`.

Can write to: local/remote files, compressed files (zip), output port, dictionary.
Can write list fields (each element produces N child elements). Maps are written as `{key=value}` strings.

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | ✓ | First data stream | Any |
| Input 1-N | optional | Additional data streams for child elements | Any — each port can have different metadata |
| Output 0 | optional | For port writing | One field: `byte`, `cbyte`, or `string` |

No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `fileURL` | yes | — | Output path. Supports graph params, zip, port write, dictionary. |
| `charset` | no | UTF-8 | Output encoding. **Always set explicitly.** |
| `mapping` [attr-cdata] | one of | — | Inline XML mapping definition |
| `mappingURL` | one of | — | External mapping file. Takes precedence over `mapping` if both set. |
| `xmlSchemaURL` | no | — | Path to XSD schema for mapping pre-generation |
| `omitNewLines` | no | `false` | When `true`: all tags on one line. When `false`: each element on a separate line. |
| `omitXmlDeclaration` | no | `false` | When `true`: suppresses `<?xml version="1.0"?>` header |
| `makeDirs` | no | `false` | Auto-create missing output directories |
| `sortedInput` | no | `false` | Set `true` when input is sorted on sort keys — enables streaming mode (avoids disk cache) |
| `cacheSize` | no | auto | Disk cache size (e.g. `300MB`, `1GB`). Increase for large multi-port joins. |
| `cacheInMemory` | no | `false` | Cache in RAM instead of disk. Faster but risks OutOfMemoryError on large data. |
| `createEmptyFiles` | no | `true` | Set `false` to suppress empty output files |
| `recordsPerFile` | no | — | Max records per output file (for partitioning) |
| `partitionKey` | no | — | Field name driving output file partitioning |
| `partitionKeySorted` | no | `false` | Set `true` when input sorted by partition key — avoids opening all files simultaneously |

## Mapping XML

Goes in `<attr name="mapping"><![CDATA[ ... ]]></attr>`.

The mapping is a valid XML document that defines the output structure. CloverDX-specific directives use the `clover:` namespace — **no `clover:` attribute or element is written to the output file** — they are processing instructions only.

**Required namespace declaration on root element:**
```xml
xmlns:clover="http://www.cloveretl.com/ns/xmlmapping"
```

---

### Core Directives

#### `clover:inPort="N"` — Port binding (drives element repetition)
Binds an element to input port N. The element repeats once per record arriving on that port.

```xml
<order clover:inPort="0">
```

Without `clover:key`/`clover:parentKey`, the element repeats for every record on port N — use keys to join child to parent.

#### `clover:key="field"` / `clover:parentKey="field"` — JOIN between parent and child

Joins a child element's port to its parent element's port. The child element is only written when `child.key == parent.parentKey`.

```xml
<order clover:inPort="0">
    <item clover:inPort="1"
          clover:key="orderId"
          clover:parentKey="id">
    </item>
</order>
```
Port 1 records where `orderId` matches port 0's `id` are nested as `<item>` children of the matching `<order>`. Composite keys: semicolon-separated — must have equal count of keys and parentKeys.

#### Field value syntax
```xml
<!-- Field as XML attribute value -->
<order id="$0.id" date="$0.orderDate" clover:inPort="0">

<!-- Field as element body text -->
<city>$2.city</city>
<n>$2.name</n>

<!-- Field adjacent to literal text -->
<price>$0.amount USD</price>
<price>{$0.amount}USD</price>   <!-- curly braces isolate field name from adjacent text -->

<!-- Escape literal $ sign (suppress field substitution) -->
<note>$$0.field</note>          <!-- outputs literal "$0.field" -->
```

#### `clover:include` / `clover:exclude` — Wildcard field selection
```xml
<!-- All fields from port 0 except id -->
<actor clover:inPort="0" clover:include="$0.*" clover:exclude="$0.id">

<!-- Specific fields only -->
<spouse clover:inPort="1" clover:key="id" clover:parentKey="id"
        clover:include="$1.name"/>

<!-- Multiple fields, semicolon-separated -->
clover:exclude="$1.movie_id;$1.actor_id"
```

#### `<clover:elements>` — Wildcard child element generation
Generates one child element per included field, named after the field:
```xml
<person clover:inPort="0">
    <clover:elements clover:include="$0.*" clover:exclude="$0.id"/>
</person>
```
Output: `<firstName>John</firstName><lastName>Smith</lastName>...` — one tag per field.

#### `clover:hide="true"` — Intermediate JOIN element suppressed from output
The element is not written but its children are. Useful for creating a JOIN level without producing an unwanted wrapper tag:
```xml
<movies>
    <movies clover:inPort="1" clover:key="actor_id" clover:parentKey="actor_id"
            clover:hide="true">
        <movie title="$1.title">...</movie>
    </movies>
</movies>
```
The outer `<movies>` is written; the inner `<movies>` binding element is suppressed; only `<movie>` tags appear inside.

#### `clover:writeNullElement="false"` — Suppress null elements
When a field mapping produces a null value, the element is omitted:
```xml
<Field clover:inPort="1" clover:key="__name" clover:parentKey="__name"
       clover:writeNullElement="false" clover:include="$1.*" clover:exclude="$1.__name"/>
```

---

## Mapping Structure Skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rootElement xmlns:clover="http://www.cloveretl.com/ns/xmlmapping">
    <parentElement attr1="$0.field1" attr2="$0.field2" clover:inPort="0">
        <childElement clover:inPort="1"
                      clover:key="foreignKeyField"
                      clover:parentKey="primaryKeyField">
            <clover:elements clover:include="$1.*"
                             clover:exclude="$1.foreignKeyField"/>
        </childElement>
    </parentElement>
</rootElement>
```

---

## Real Sandbox Examples

### IntroExamples — person + spouse + children (3-port hierarchical join)
```xml
<Node fileURL="${DATAOUT_DIR}/people.xml"
      omitNewLines="false" id="EXT_XML_WRITER0" type="EXT_XML_WRITER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<persons xmlns:clover="http://www.cloveretl.com/ns/xmlmapping">
  <person clover:inPort="0">
    <clover:elements clover:include="$0.*" clover:exclude="$0.id"/>
    <spouse clover:inPort="1" clover:key="id" clover:parentKey="id"
            clover:include="$1.name"/>
    <child  clover:inPort="2" clover:key="id" clover:parentKey="id"
            clover:include="$2.name"/>
  </person>
</persons>]]></attr>
</Node>
```
Three input ports. `<person>` repeats per port-0 record; `<spouse>` and `<child>` joined on `id`. All person fields except `id` written as child elements via `<clover:elements>`.

### IntroExamples — actor + nested movies (hide intermediate element)
```xml
<Node charset="UTF-8" fileURL="${DATAOUT_DIR}/Actors.xml"
      id="EXT_XML_WRITER0" type="EXT_XML_WRITER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<actors xmlns:clover="http://www.cloveretl.com/ns/xmlmapping">
  <actor clover:inPort="0">
    <clover:elements clover:include="$0.first_name;$0.last_name"/>
    <movie clover:inPort="1" clover:key="actor_id" clover:parentKey="actor_id"
           clover:include="$1.*" clover:exclude="$1.movie_id;$1.actor_id"/>
  </actor>
</actors>]]></attr>
</Node>
```

### CLV_MCP_KWBASE / BasicFeatures — orders with items and addresses (3 ports, field as attr + body text, zip output)
```xml
<Node charset="UTF-8"
      fileURL="zip:(${DATAIN_DIR}/Orders.zip)#Orders.xml"
      xmlSchemaURL="${META_DIR}/online-store/Orders.xsd"
      id="ORDERS_XML" type="EXT_XML_WRITER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<orders xmlns:clover="http://www.cloveretl.com/ns/xmlmapping">
  <order id="$0.id" customerId="$0.customerId" date="$0.orderDatetime"
         clover:inPort="0">
    <item productCode="$1.productCode" unitPrice="$1.unitPrice" qty="$1.units"
          clover:inPort="1" clover:key="orderId" clover:parentKey="id">$1.productName</item>
    <address type="$2.type" clover:inPort="2" clover:key="id" clover:parentKey="id">
      <n>$2.name</n>
      <street>$2.street</street>
      <city>$2.city</city>
      <zip>$2.zip</zip>
      <state>$2.state</state>
      <country>$2.country</country>
    </address>
  </order>
</orders>]]></attr>
</Node>
```
Key patterns: field values as XML attributes (`id="$0.id"`); field value as element body text (`<item>$1.productName</item>`); write to zip; XSD schema referenced.

### DataAnalyticsBundleLib — write to output port, one record per file, null suppression
```xml
<Node createEmptyFiles="false" fileURL="port:$0.xml:discrete"
      makeDirs="true" partitionKeySorted="true" recordsPerFile="1"
      id="CREATE_FILE_STRUCTURE1" type="EXT_XML_WRITER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<Record xmlns:clover="http://www.cloveretl.com/ns/xmlmapping"
        clover:inPort="0" clover:include="$0.*">
  <Field clover:inPort="1" clover:key="__name" clover:parentKey="__name"
         clover:writeNullElement="false" clover:include="$1.*"
         clover:exclude="$1.__name"/>
</Record>]]></attr>
</Node>
```
Writing to `port:$0.xml:discrete` sends output to the next component's input port. `recordsPerFile="1"` + `partitionKeySorted="true"` = one XML document per input record.

### MiscExamples — writing CloverDX metadata format as XML
```xml
<Node fileURL="${DATATMP_DIR}/${ROOT_RUN_ID}/tmpMeta.fmt"
      makeDirs="true" id="WRITE_TMP_METADATA" type="EXT_XML_WRITER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<Record xmlns:clover="http://www.cloveretl.com/ns/xmlmapping"
        fieldDelimiter="|" recordSize="-1" name="tmpMeta"
        skipSourceRows="1" type="delimited" recordDelimiter="\n">
  <Field name="$0.fieldName" label="$0.fieldLabel" nullable="true"
         type="string" clover:inPort="0">
    <attr name="description">
      <![CDATA[$0.fieldDescription]]]]><![CDATA[>
    </attr>
  </Field>
</Record>]]></attr>
</Node>
```
Generates a `.fmt` metadata file dynamically. Note the nested CDATA split trick: `]]]]><![CDATA[>` — when the content itself contains `]]>`, split the outer CDATA at that point.

---

## fileURL Patterns

```xml
fileURL="${DATAOUT_DIR}/output.xml"                    <!-- plain file -->
fileURL="zip:(${DATAOUT_DIR}/output.zip)#data.xml"    <!-- inside zip archive -->
fileURL="port:$0.xml:discrete"                         <!-- to output port field -->
fileURL="dict:myDictEntry"                             <!-- to dictionary entry -->
```

---

## Performance: Streaming vs Caching

By default EXT_XML_WRITER **caches** slave port data to disk before writing — this is safe but slower for large data.

**To enable streaming mode** (faster, no disk cache): set `sortedInput="true"` and declare `sortKeys` matching the key fields used in bindings. Both master and slave input must be pre-sorted.

For small-to-medium slave data: leave defaults, optionally tune `cacheSize` (e.g. `cacheSize="500MB"`).
For large slave data with known sort order: use `sortedInput="true"`.
For very large slave that fits in memory: `cacheInMemory="true"` (risk: OOM).

---

## Decision Guide

| Need | Approach |
|---|---|
| Single flat stream → XML | One port, `clover:inPort="0"`, field values as attributes or child elements |
| Master + child records joined | `clover:inPort` on both, `clover:key`/`clover:parentKey` on child |
| All fields from port as child elements | `<clover:elements clover:include="$0.*"/>` |
| Some fields as XML attributes, others as child elements | Mix: `attr="$0.field"` for attributes, `<clover:elements>` for child elements |
| Field value as element body text | `<elem>$0.field</elem>` or `<elem>{$0.field}suffix</elem>` |
| Skip null elements | `clover:writeNullElement="false"` on the binding element |
| Suppress intermediate JOIN wrapper element | `clover:hide="true"` |
| Write to zip file | `fileURL="zip:(${DIR}/file.zip)#entry.xml"` |
| Write to output port | `fileURL="port:$0.fieldName:discrete"` |
| XSD-driven structure | Set `xmlSchemaURL`, use mapping editor to generate |
| One XML doc per input record | `recordsPerFile="1"` + `partitionKeySorted="true"` |
| Shared mapping across graphs | `mappingURL` pointing to external file |

---

## Mistakes

| Wrong | Correct |
|---|---|
| Missing `xmlns:clover="http://www.cloveretl.com/ns/xmlmapping"` on root | Required — without it, all `clover:` directives are invalid XML |
| `clover:key` without `clover:parentKey` (or vice versa) | Both must be set together; count of key fields must match |
| Field reference `$0.field` adjacent to text without braces | Use `{$0.field}suffix` when field name could be ambiguous; without braces `$0.fieldUSD` is parsed as field named `fieldUSD` |
| `clover:` attributes written to output | They are never written — they are processing directives only |
| Binding root element to a port when multiple records arrive | Root can only repeat if partitioning is configured; multiple root bindings produce invalid XML |
| `clover:key`/`clover:parentKey` field count mismatch | Must have exactly as many `key` fields as `parentKey` fields |
| Large multi-port join with default settings on huge data | Increase `cacheSize` or enable `sortedInput="true"` with sorted input |
| Omitting `charset` | Always set `charset="UTF-8"` explicitly |
| `mappingURL` and `mapping` both set | `mappingURL` takes precedence — remove `mapping` to avoid confusion |
| Nested CDATA `]]>` inside the mapping CDATA block | Split using `]]]]><![CDATA[>` — see MiscExamples pattern above |
| `omitNewLines="true"` when readable output needed | Default `false` writes each element on its own line |
