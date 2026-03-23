# CloverDX XML_EXTRACT — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x XML_EXTRACT (XMLExtract) component.
> Incorporates confirmed working patterns from the XMLProcessing.grf example graph and official docs.
> XMLExtract uses SAX-based parsing — fast, low-memory, suitable for large XML files.

---

## WHEN TO USE XML_EXTRACT VS ALTERNATIVES

| Component | Parser | Use when |
|---|---|---|
| **XML_EXTRACT** | SAX | Default choice. Fast, low-memory. Visual mapping editor. XPath-like element addressing. |
| XMLReader | DOM | Need complex XPath (e.g. sibling references). Slower, more memory. |
| XMLXPathReader | DOM | Legacy. Superseded by XMLReader. |

---

## COMPONENT SKELETON

```xml
<Node charset="UTF-8" enabled="enabled" guiName="ReadXML" guiX="95" guiY="325" id="XML_EXTRACT0" schema="${DATAIN_DIR}/input.xsd" sourceUri="${DATAIN_DIR}/input.xml" type="XML_EXTRACT" useNestedNodes="true">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="rootElement">
        <Mapping element="record" outPort="0"/>
    </Mapping>
</Mappings>
]]></attr>
</Node>
```

**Key node attributes:** `sourceUri` (file URL), `schema` (XSD path), `useNestedNodes`, `charset`.
**Ports:** output `0` required, output `1..n` optional (each can have different metadata). Optional input `0` for port-reading mode.

---

## NODE-LEVEL ATTRIBUTES

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="XML_EXTRACT"` | yes | Component type |
| `sourceUri` | yes | XML source file path. Supports graph parameters, wildcards, port reading. |
| `schema` | no | Path to XSD schema file. Used by visual mapping editor. No effect at runtime. |
| `useNestedNodes` | no | `true` (default): nested elements auto-mapped if names are unique. `false`: explicit `<Mapping>` required for every element. |
| `charset` | no | Input file encoding. Best practice: always set explicitly (e.g. `UTF-8`, `ISO-8859-1`). |
| `trimStrings` | no | `true` (default): trim whitespace from element values. |
| `validate` | no | `true`: validate XML against DTD. Default: `false`. |
| `skipRows` | no | Skip N matching records globally across all sources. |
| `numRecords` | no | Max total records to emit. |

---

## MAPPING — THE CORE CONCEPT

The `mapping` attribute (or `mappingURL` for external file) contains a `<Mappings>` XML block that tells the component how to extract data from the XML structure into Clover records.

**The mapping nesting mirrors the XML nesting.** A `<Mapping>` element without `outPort` acts as a structural anchor (just locates the element without emitting records). A `<Mapping>` with `outPort` emits records to that port.

---

## MAPPING SKELETON

```xml
<Mappings>
    <Mapping element="rootElement">                          <!-- structural anchor, no outPort -->
        <Mapping element="record" outPort="0"/>              <!-- emits records to port 0 -->
    </Mapping>
</Mappings>
```

For the mapping to work:
- The `<Mappings>` root tag has no attributes
- Each `<Mapping>` requires `element` attribute matching the XML element name
- `outPort` determines which output port receives records for that element

---

## MAPPING ATTRIBUTE REFERENCE

### `<Mapping>` attributes

| Attribute | Required | Description |
|---|---|---|
| `element` | yes | XML element name to match. Use `prefix:name` for namespaced elements. |
| `outPort` | no | Output port number. Omit to use the element only as a structural anchor (no records emitted). |
| `implicit` | no | `true` (default): auto-map XML field names to Clover fields of same name. `false`: only `xmlFields`/`cloverFields` mappings apply. |
| `xmlFields` | no | Semicolon-separated list of XML element/attribute names to map. Use `.` for the element's own text content. Use `../fieldName` to reference a parent-level field. |
| `cloverFields` | no | Semicolon-separated list of Clover field names corresponding to `xmlFields`. Must match in count and type. |
| `parentKey` | no | Semicolon-separated Clover field names from the **parent** record to copy down to the child. Used to link parent and child records. |
| `generatedKey` | no | Semicolon-separated Clover field names in the **child** record that receive the values from `parentKey`. Counts and types must match. |
| `sequenceField` | no | Name of the child Clover field that receives an auto-incremented sequence number (for disambiguating multiple children of the same element name). |
| `sequenceId` | no | ID of a graph `<Sequence>` to use for `sequenceField` numbering (custom start/step/persistence). |
| `useParentRecord` | no | `true`: write mapped values into the nearest parent record (with `outPort`) instead of creating a new record. Default: `false`. |
| `skipRows` | no | Skip first N occurrences of this element. |
| `numRecords` | no | Read at most N occurrences of this element. |
| `templateId` | no | Declares this mapping as a reusable template with the given ID. |
| `templateRef` | no | Inserts the named template at this position. |
| `nestedDepth` | no | Shorthand for `N` levels of nested `templateRef`. Use instead of deeply nested template references. |

### `<FieldMapping>` (pass-through from input port)

Maps a field from the optional input port record into an output record. Used when the component reads from a port and you want to pass through context fields.

```xml
<FieldMapping inputField="sessionID" outputField="sessionID"/>
```

### `<TypeOverride>` (visual editor hint only)

Overrides the schema-declared type of an element for the visual mapping editor. **Has no effect at runtime.**

```xml
<TypeOverride elementPath="/employee/child" overridingType="boy"/>
```

---

## COMPLETE WORKING EXAMPLE (from XMLProcessing.grf)

**XML structure being read:**
```xml
<movies>
    <movie>
        <movie_id>1</movie_id>
        <title>...</title>
        <description>...</description>
        <release_year>2010</release_year>
        <language>en</language>
        <length>120</length>
        <rating>PG</rating>
        <category>Action</category>
        <actor>
            <actor_id>5</actor_id>
            <first_name>John</first_name>
            <last_name>Smith</last_name>
        </actor>
        <actor>
            <actor_id>12</actor_id>
            ...
        </actor>
    </movie>
</movies>
```

**Graph node:**
```xml
<Node charset="UTF-8" enabled="enabled" guiName="Read Movies.xml" guiX="95" guiY="325" id="XML_EXTRACT0" schema="${DATAIN_DIR}/others/movies.xsd" sourceUri="${DATAIN_DIR}/others/Movies.xml" type="XML_EXTRACT" useNestedNodes="true">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="movies">
        <Mapping element="movie" outPort="1">
            <Mapping element="actor" outPort="0" parentKey="movie_id" generatedKey="movie_id"
                xmlFields="first_name;actor_id;last_name"
                cloverFields="first_name;actor_id;last_name"/>
        </Mapping>
    </Mapping>
</Mappings>
]]></attr>
</Node>
```

**What this does:**
- Port 1 receives one record per `<movie>` element with all child fields auto-mapped by name (implicit=true)
- Port 0 receives one record per `<actor>` element, with `movie_id` copied from the parent `<movie>` record into `movie_id` on the child via `parentKey`/`generatedKey`
- `xmlFields`/`cloverFields` explicitly map the three actor fields (same names, but explicit mapping shown for clarity)

**Edge declarations for this pattern:**
```xml
<Edge fromNode="XML_EXTRACT0:0" id="Edge1" inPort="Port 0 (in)" metadata="MetaActor" outPort="Port 0 (out)" toNode="NEXT0:0"/>
<Edge fromNode="XML_EXTRACT0:1" id="Edge0" inPort="Port 0 (in)" metadata="MetaMovie" outPort="Port 1 (out)" toNode="NEXT1:0"/>
```

---

## FIELD MAPPING PATTERNS

### Pattern 1 — Implicit: field names match element names (simplest)

```xml
<Mappings>
    <Mapping element="orders">
        <Mapping element="order" outPort="0"/>
    </Mapping>
</Mappings>
```

All child elements of `<order>` are auto-mapped to Clover fields with the same name. No `xmlFields`/`cloverFields` needed.

### Pattern 2 — Explicit rename: XML names differ from field names

```xml
<Mappings>
    <Mapping element="employee" outPort="0"
        xmlFields="salary;spouse"
        cloverFields="basic_salary;partner_name"/>
</Mappings>
```

### Pattern 3 — Parent-child relationship with foreign key propagation

```xml
<Mappings>
    <Mapping element="invoice" outPort="0">
        <Mapping element="line_item" outPort="1"
            parentKey="invoice_id"
            generatedKey="invoice_id"/>
    </Mapping>
</Mappings>
```

`invoice_id` from the parent `<invoice>` record (port 0) is copied into `invoice_id` on each child `<line_item>` record (port 1). Both metadata must have an `invoice_id` field.

### Pattern 4 — Multi-field parent key

```xml
<Mapping element="project" outPort="0">
    <Mapping element="customer" outPort="1"
        parentKey="projName;projManager"
        generatedKey="projName;projManager"/>
</Mapping>
```

Multiple parent fields, delimited by `;`. Field counts and types must match between `parentKey` and `generatedKey`.

### Pattern 5 — Sequence for ambiguous parent-child (one parent → multiple same-name children)

```xml
<Mapping element="benefits" outPort="0"
    parentKey="empID" generatedKey="empID"
    sequenceField="seqKey" sequenceId="Sequence0">
    <Mapping element="financial" outPort="1"
        parentKey="seqKey" generatedKey="seqKey"/>
</Mapping>
```

When multiple `<financial>` elements exist under each `<benefits>`, they can't be uniquely identified by parent key alone. `sequenceField` auto-assigns an incrementing number into `seqKey`, which the next level then uses as its parent key.

### Pattern 6 — Map element text content with dot syntax

```xml
<Mapping element="project">
    <Mapping element="customer" outPort="0"
        xmlFields=".;../."
        cloverFields="customerValue;projectValue"/>
</Mapping>
```

`.` = the element's own text content (text between its tags). `../.` = the parent element's text content. Every other name in `xmlFields` refers to a child element or attribute.

### Pattern 7 — Map element content + attribute of same name (disambiguation)

When `<customer>` has both an attribute named `customer` and a child element named `customer`:

```xml
<Mapping element="customer" outPort="0"
    xmlFields=".;customer"
    cloverFields="customerText;customerAttr">
    <Mapping element="customer" outPort="1"/>
</Mapping>
```

- `.` maps the text content of `<customer>`
- `customer` (without dot) maps the attribute named `customer`
- The child `<Mapping element="customer">` handles the sub-element also named `customer`

### Pattern 8 — Attribute disambiguation using `{}` prefix

When a `<customer>` element has both an attribute `name` and a child element `name`, use `{}name` to refer to the attribute (empty namespace prefix):

```xml
<Mappings>
    <Mapping element="customer" outPort="0"
        xmlFields="{}name"
        cloverFields="nameAttribute">
        <Mapping element="name" useParentRecord="true"
            xmlFields="../{}name"
            cloverFields="nameElement">
        </Mapping>
    </Mapping>
</Mappings>
```

### Pattern 9 — useParentRecord: merge child value into parent record

```xml
<Mapping element="project" outPort="0" xmlFields="." cloverFields="projectValue">
    <Mapping element="customer" useParentRecord="true"
        xmlFields="." cloverFields="customerValue"/>
</Mapping>
```

`customerValue` is written into the same port-0 record as `projectValue`. No separate child record is created.

### Pattern 10 — No-outPort anchor: locate without emitting

```xml
<Mappings>
    <Mapping element="response">           <!-- no outPort: just anchors -->
        <Mapping element="results">        <!-- no outPort: just anchors -->
            <Mapping element="record" outPort="0"/>
        </Mapping>
    </Mapping>
</Mappings>
```

The outer `<Mapping>` elements without `outPort` simply navigate to the target element depth. No records are emitted for them.

### Pattern 11 — Read XML subtree as string (+ and - content mapping)

```xml
<!-- + includes the element's own tags -->
<Mapping element="customer" outPort="0"
    xmlFields="+" cloverFields="fullXml"/>

<!-- - includes only the inner content, not the wrapping element tag -->
<Mapping element="customer" outPort="0"
    xmlFields="-" cloverFields="innerXml"/>
```

`+` maps the full subtree including the element itself; `-` maps only the element's children/content. Output is a string. **Warning:** can produce large amounts of data; impacts performance.

### Pattern 12 — Parent field access with ../

```xml
<Mapping element="employee">
    <Mapping element="project">
        <Mapping element="customer" outPort="0"
            xmlFields="name;../../empID"
            cloverFields="name;empId"/>
    </Mapping>
</Mapping>
```

`../` navigates up one `<Mapping>` level. `../../` goes up two levels. Each `../` refers to the XML element defined in the direct parent `<Mapping>` — not the absolute XML parent if `useNestedNodes=true` collapses levels.

---

## useNestedNodes — CRITICAL BEHAVIOR

**`useNestedNodes="true"` (default):** Fields from deeply nested elements are automatically accessible at the current mapping level if their names are unique. The SAX parser scans into descendants.

**`useNestedNodes="false"`:** Only direct children of the mapped element are accessible. You must create explicit `<Mapping>` tags for every level.

**The naming ambiguity trap:** If two elements at different depths have the same name and `useNestedNodes=true`, the **first one found during SAX traversal** wins — which may not be the intended one.

```xml
<!-- Two <id> elements at different depths: -->
<root>
  <r>
    <groups><id>groupID</id></groups>   <!-- found first when useNestedNodes=true -->
    <id>resultID</id>                   <!-- found first when useNestedNodes=false -->
  </r>
</root>
```

- `useNestedNodes=true` → maps `groupID` (first `<id>` encountered)
- `useNestedNodes=false` → maps `resultID` (only direct child `<id>` of `<r>` mapping)

**Rule:** When element names are not unique across depths, use `useNestedNodes="false"` and be explicit in your mapping structure.

---

## IMPLICIT VS EXPLICIT FIELD MAPPING

By default (`implicit="true"`), any XML element or attribute whose name exactly matches a Clover field name is auto-mapped. To disable this for a specific `<Mapping>` element:

```xml
<Mapping element="employee" outPort="0" implicit="false"
    xmlFields="salary" cloverFields="basic_salary"/>
```

With `implicit="false"`, only the explicitly listed fields are mapped. Everything else is ignored even if names match.

**Priority:** Explicit `xmlFields`/`cloverFields` mapping always overrides implicit name matching.

---

## SEMICOLON-SEPARATED FIELD LISTS

`xmlFields`, `cloverFields`, `parentKey`, `generatedKey` all accept fields separated by `;`, `:`, or `|`. All three delimiters are equivalent.

```xml
parentKey="first_name;last_name"
parentKey="first_name:last_name"
parentKey="first_name|last_name"
```

---

## NAMESPACES

Set `namespacePaths` attribute on the node and use prefixes in mapping element names:

```xml
<Node ... namespacePaths="myNs=http://www.example.com/schema">
    <attr name="mapping"><![CDATA[<Mappings>
    <Mapping element="myNs:records">
        <Mapping element="myNs:record" outPort="0"/>
    </Mapping>
</Mappings>
]]></attr>
</Node>
```

Namespace URI can also be used directly with `{}` notation:

```xml
<Mapping element="{http://www.example.com/schema}record" outPort="0"/>
```

---

## TEMPLATES (for recursive/deep structures)

Templates allow reuse of mapping patterns — essential for recursive XML or deeply nested structures.

```xml
<Mappings>
    <!-- Declare template -->
    <Mapping element="category" templateId="catTemplate">
        <Mapping element="subCategory" outPort="0"
            xmlFields="name" cloverFields="name"/>
        <!-- Self-reference for recursion: -->
        <Mapping templateRef="catTemplate" nestedDepth="5"/>
    </Mapping>
</Mappings>
```

- `templateId` declares the template
- `templateRef` inserts the template at that position
- `nestedDepth="N"` is equivalent to N nested `templateRef` elements (cleaner and avoids exponential expansion)

**Rule:** Use `nestedDepth` instead of manually nesting `templateRef` elements — it always produces predictable depth.

---

## NODE-LEVEL ATTRIBUTES — COMPLETE REFERENCE

| Attribute (XML name) | Description | Default |
|---|---|---|
| `sourceUri` | XML file path (or port/dictionary URL) | required |
| `schema` | XSD schema path (visual editor only) | — |
| `useNestedNodes` | Auto-access descendants by name if unique | `true` |
| `charset` | Input file encoding — always set explicitly | system default |
| `trimStrings` | Trim whitespace from element values | `true` |
| `validate` | Validate XML against DTD | `false` |
| `skipRows` | Global record skip count | 0 |
| `numRecords` | Global record limit | unlimited |
| `namespacePaths` | Namespace prefix bindings (`prefix=uri;prefix2=uri2`) | — |
| `addFilePath` | Add file path for resolving external XML entities | `false` |

---

## EDGE DECLARATIONS

Port outPort names follow the pattern `Port N (out)`:

```xml
<Edge fromNode="XML_EXTRACT0:0" id="EdgeA" inPort="Port 0 (in)" metadata="MetaA" outPort="Port 0 (out)" toNode="NEXT0:0"/>
<Edge fromNode="XML_EXTRACT0:1" id="EdgeB" inPort="Port 0 (in)" metadata="MetaB" outPort="Port 1 (out)" toNode="NEXT1:0"/>
```

---

## GENERATION RULES FOR LLM

Always include:
- `type="XML_EXTRACT"`
- `sourceUri` (the XML file path)
- `charset="UTF-8"` (or the appropriate encoding — always explicit)
- `useNestedNodes="true"` unless element names are ambiguous across depths

Mapping generation checklist:
- Mirror the XML nesting structure with nested `<Mapping>` elements
- Elements that just navigate to depth (no records needed): omit `outPort`
- Elements that produce records: add `outPort="N"` where N is the output port number
- Child records that need a foreign key from parent: add `parentKey` on parent and `generatedKey` on child with matching field names and counts
- Multiple same-name children under one parent: add `sequenceField` and optionally `sequenceId`
- Field names match XML element/attribute names: rely on implicit mapping (no `xmlFields`/`cloverFields` needed)
- Field names differ: add explicit `xmlFields="xmlName" cloverFields="cloverFieldName"`
- Element text content: use `.` in `xmlFields`
- Parent element value from child context: use `../fieldName` or `../../fieldName` in `xmlFields`
- Merge nested value into parent record without new record: use `useParentRecord="true"`
- Duplicate element names at different depths: set `useNestedNodes="false"` and be explicit

Do NOT:
- Omit `<Mappings>` wrapper — it is always required as the root element
- Use `outPort` without a connected output edge
- Mix up `parentKey` (field names on parent port) and `generatedKey` (field names on child port)
- Use `../` navigation when `useNestedNodes=true` collapses levels — count `<Mapping>` parents, not XML element parents
- Set `schema` expecting it to affect runtime parsing — it is a visual editor aid only

---

## COMMON MISTAKES

| Mistake | Correct form |
|---|---|
| Omitting `<Mappings>` wrapper | Always required: `<Mappings>...<Mappings/>` |
| `parentKey`/`generatedKey` field counts mismatch | Both lists must have same count and compatible types |
| `../` navigates XML parents, not Mapping parents | With `useNestedNodes=true`, `../` navigates `<Mapping>` parent hierarchy, not XML hierarchy |
| Element and attribute same name, only one mapped | Use `.` for text content and bare name for attribute (or `{}name` for attribute explicitly) |
| Ambiguous nested elements with `useNestedNodes=true` | Set `useNestedNodes="false"` and add explicit `<Mapping>` for each level |
| `implicit="true"` but field name differs from XML name | Add explicit `xmlFields`/`cloverFields` pair or set `implicit="false"` |
| `charset` not set | Always set explicitly to avoid locale-dependent behavior |
| `+`/`-` content mapping for large subtrees | Be aware of performance impact — use only when necessary |
| `schema` attribute wrong path | Only affects visual editor; silently ignored at runtime |
