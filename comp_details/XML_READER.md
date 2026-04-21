# CloverDX XML_READER — LLM Reference

## What it does
DOM-based XML reader. Loads the entire document into memory, then extracts records using XPath-based mapping. Sends records to one or more output ports. Supports full XPath including sibling references, functions (`count()`, `text()`, `name()`), `..` parent navigation, and namespace-qualified paths.

**Use for:** small-to-medium XML files, complex/irregular structures requiring full XPath.
**Do not use for large files (>>5 MB)** — entire document held in RAM. Use XML_EXTRACT (SAX-based) instead.

Also known as **XMLReader** (display name). Component type string: `XML_READER`.

Supersedes XMLXPathReader (also DOM-based, more complex XPath expressions than XML_EXTRACT but slower and more memory-intensive).

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | optional | Port reading — one `string`/`byte`/`cbyte` field | One field only |
| Output 0 to N-1 | ✓ (at least 1) | Correct data records — each port can have different metadata | Any |
| Output N (last) | optional | **Error port** — fixed format, see below | Template format |

**Error port metadata template** (`XMLReader_TreeReader_ErrPortWithFile`):

| Field | Type | Description |
|---|---|---|
| `port` | integer | Output port where error occurred |
| `recordNumber` | integer | Record number (per source and port) |
| `fieldNumber` | integer | Field index |
| `fieldName` | string | Field name |
| `value` | string | Value that caused the error |
| `message` | string | Error message |
| `file` | string | Source filename (optional — template without it: `ErrPortWithoutFile`) |

No metadata propagation. Each output port can have different metadata. Metadata can use Autofilling functions.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `fileURL` | yes | — | Source file path. Supports graph params, zip, port read, dictionary. |
| `charset` | no | Auto (file) / required (port/dict) | Encoding. **Always set explicitly when reading from port or dictionary** — no autodetection there. |
| `mapping` [attr-cdata] | one of | — | Inline XPath mapping XML |
| `mappingURL` | one of | — | External mapping file. Takes precedence if both set. |
| `implicitMapping` | no | `false` | When `true`: auto-maps XML elements to same-named metadata fields. Explicit `<Mapping>` still needed for renamed or nested fields. |
| `dataPolicy` | no | `strict` | `strict` / `controlled` / `lenient` |

## Mapping XML

Goes in `<attr name="mapping"><![CDATA[ ... ]]></attr>`.

### Context Tag — `<Context>`

Navigates the XML tree to a node level. Each matching node produces records.

```xml
<Context xpath="xpathExpression"
         outPort="N"
         parentKey="field1;field2"
         generatedKey="childField1;childField2"
         sequenceId="SequenceId"
         sequenceField="seqField"
         namespacePaths='prefix="URI"'>
```

| Attribute | Req | Description |
|---|---|---|
| `xpath` | yes | XPath expression locating the repeated element |
| `outPort` | no | Output port number. If omitted, this Context is navigation-only — no output produced. |
| `parentKey` | both or neither | Semicolon-separated field names from the **parent** Context's output metadata. Used to propagate a parent ID to child records. |
| `generatedKey` | both or neither | Semicolon-separated field names from **this** Context's output metadata. Receives the parent key value. Count and types must match `parentKey`. |
| `sequenceId` | optional | Sequence ID — when parentKey/generatedKey alone don't guarantee uniqueness |
| `sequenceField` | optional | Metadata field on this level that stores the sequence value — can itself serve as `parentKey` for deeper nesting |
| `namespacePaths` | optional | Namespace declarations for XPath: `namespacePaths='n1="http://uri1";n2="http://uri2"'`. Inherited by child `<Mapping>` elements. Required when input XML uses namespaces. |

**`outPort` is optional** — a `<Context>` without `outPort` is used purely for navigation. This avoids unnecessary intermediate wrapper elements.

### Mapping Tag — `<Mapping>`

Extracts a value and maps it to a metadata field.

```xml
<Mapping xpath="xpathExpression" cloverField="fieldName" trim="true"/>
<!-- OR (faster for simple element names): -->
<Mapping nodeName="elementName" cloverField="fieldName"/>
<!-- OR (map from input port field): -->
<Mapping inputField="inputFieldName" cloverField="outputFieldName"/>
```

| Attribute | Req | Description |
|---|---|---|
| `xpath` | one of | XPath expression to extract value |
| `nodeName` | one of | Simple element name — **faster than `xpath`** for direct child elements |
| `cloverField` | yes | Output metadata field name |
| `trim` | no | Default `true`. Strip leading/trailing whitespace from value. |
| `namespacePaths` | optional | Namespace declarations for this Mapping's XPath. Inherits from parent `<Context>`. |
| `inputField` | — | Maps an input port field (from port-reading mode) to the output field. |

### XPath expressions in `<Mapping>`

```xml
<!-- XML attribute -->
<Mapping cloverField="id"           xpath="@id"/>

<!-- Child element text -->
<Mapping cloverField="name"         xpath="name"/>
<Mapping cloverField="name"         nodeName="name"/>   <!-- faster equivalent -->

<!-- Nested element text -->
<Mapping cloverField="firstname"    xpath="name/firstname"/>
<Mapping cloverField="salary"       xpath="tagA/salary"/>

<!-- Current node text content -->
<Mapping cloverField="productID"    xpath="."/>

<!-- Element text content via function -->
<Mapping cloverField="productName"  xpath="text()"/>

<!-- Navigate to parent attribute (for child Context records) -->
<Mapping cloverField="orderId"      xpath="../@id"/>
<Mapping cloverField="countryName"  xpath="../name"/>

<!-- XPath aggregate function -->
<Mapping cloverField="itemsCount"   xpath="count(item)"/>

<!-- XPath node name function -->
<Mapping cloverField="elementName"  xpath="name()"/>

<!-- Ancestor path building -->
<Mapping cloverField="path"         xpath="concat('/',string-join(ancestor::*/name(),'/'))" />
```

### Reading list fields (multivalue)

When an XML element repeats at the same level, map it to a `list` typed metadata field — all values are collected into one list:

```xml
<!-- Input XML has multiple <attendees> siblings -->
<Mapping xpath="attendees" cloverField="attendanceList"/>
<!-- Result: attendanceList = [John, Vicky, Brian] -->
```

Maps are read as strings (serialized representation).

## Multi-Port Hierarchical Extraction

Nested `<Context>` elements mirror the XML nesting. `parentKey`/`generatedKey` propagate IDs from parent to child records:

```xml
<Context xpath="/countries/country" outPort="0">
    <Mapping cloverField="countryName" xpath="n"/>
    <Context xpath="./county" outPort="1">
        <Mapping cloverField="countryName" xpath="../n"/>    <!-- parent ref -->
        <Mapping cloverField="countyName"  xpath="n"/>
    </Context>
</Context>
```

With `parentKey`/`generatedKey` for explicit key propagation:
```xml
<Context xpath="/employees/employee" outPort="0">
    <Mapping nodeName="salary"    cloverField="basic_salary"/>
    <Mapping xpath="name/firstname" cloverField="firstname"/>
    <Context xpath="child" outPort="1"
             parentKey="empID" generatedKey="parentID"/>
    <Context xpath="benefits" outPort="2"
             parentKey="empID;jobID" generatedKey="empID;jobID"
             sequenceField="seqKey" sequenceId="Sequence0">
        <Context xpath="financial" outPort="3"
                 parentKey="seqKey" generatedKey="seqKey"/>
    </Context>
</Context>
```

## Namespace Handling

When input XML uses namespaces, declare them in `namespacePaths` and use the prefix in XPath:

```xml
<Context xpath="/xhtml:html//svg:a"
         namespacePaths='xhtml="http://www.w3.org/1999/xhtml";svg="http://www.w3.org/2000/svg"'
         outPort="0">
    <Mapping cloverField="url" xpath="@href"/>
</Context>
```

`namespacePaths` is inherited from `<Context>` by its child `<Mapping>` elements.

## Input Field Mapping (`inputField`)

When reading from port in `source` or `discrete` mode, pass input port field values through to output:

```xml
<!-- fileURL="port:$0.filename:source" — each input record provides a file path -->
<Context xpath="/products/product" outPort="0">
    <Mapping cloverField="productID"  xpath="."/>
    <Mapping cloverField="customerID" inputField="ID"/>    <!-- from input port -->
</Context>
```

## Real Sandbox Examples

### CLV_MCP_KWBASE / BasicFeatures — orders XML from zip, 3 ports (attributes + text + aggregate)
```xml
<Node charset="UTF-8"
      fileURL="zip:(${DATAIN_DIR}/Orders.zip)#Orders.xml"
      implicitMapping="true"
      id="XMLREADER" type="XML_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Context xpath="/orders">
    <Context xpath="order" outPort="0">
        <Mapping cloverField="itemsCount"    xpath="count(item)"/>
        <Mapping cloverField="id"            xpath="@id"/>
        <Mapping cloverField="customerId"    xpath="@customerId"/>
        <Mapping cloverField="orderDatetime" xpath="@date"/>

        <Context xpath="item" outPort="1">
            <Mapping cloverField="orderId"     xpath="../@id"/>
            <Mapping cloverField="productCode" xpath="@productCode"/>
            <Mapping cloverField="unitPrice"   xpath="@unitPrice"/>
            <Mapping cloverField="qty"         xpath="@qty"/>
            <Mapping cloverField="productName" xpath="text()"/>
        </Context>

        <Context xpath="address" outPort="2">
            <Mapping cloverField="orderId" xpath="../@id"/>
            <Mapping cloverField="type"    xpath="@type"/>
        </Context>
    </Context>
</Context>]]></attr>
</Node>
```

### Official example — implicit mapping + list field + attribute
```xml
<!-- Mapping for retail.xml: order_id from attr, emails as list, name/surname implicit -->
<Context xpath="/orders/order" outPort="0">
    <Mapping cloverField="order_id" xpath="@id"/>
    <Mapping cloverField="email"    xpath="./emails/email"/>  <!-- list field -->
</Context>
```
With `implicitMapping="true"`, `firstname` and `surname` elements auto-map to same-named fields.

## XML_READER vs XML_EXTRACT

| | XML_READER | XML_EXTRACT |
|---|---|---|
| Parser | DOM (full document in RAM) | SAX (streaming) |
| Memory | Entire document | Low — streaming |
| File size | Small-medium (<5 MB) | Any size |
| XPath support | Full XPath (`..`, `@`, `count()`, `name()`, `//`) | Element paths only |
| List field support | ✓ (repeating elements → list) | Limited |
| Namespace XPath | ✓ (`namespacePaths`) | Limited |
| Error port | ✓ (structured error metadata) | ✗ |
| Auto-propagated metadata | ✗ | ✗ |

## Best Practices

**Use `implicitMapping="true"`** to avoid writing `<Mapping xpath="salary" cloverField="salary"/>` for fields that match element names. Explicit mappings only for renamed or path-navigated fields.

**Avoid unnecessary `<Context>` elements.** Use `<Context>` only when you need output from that level. Navigate directly:
```xml
<!-- Good: skip intermediate level, map directly -->
<Context xpath="/elem1/elem11" outPort="0">
    <Mapping cloverField="field1" xpath="elem111"/>
</Context>

<!-- Avoid: unnecessary outer Context for navigation only -->
<Context xpath="/elem1">
    <Context xpath="elem11" outPort="0">
        <Mapping cloverField="field1" xpath="elem111"/>
    </Context>
</Context>
```

**Use `nodeName` instead of `xpath` for simple element names** — it is faster.

**Always set `charset` explicitly when reading from port or dictionary** — auto-detection does not work in these modes.

## Mistakes

| Wrong | Correct |
|---|---|
| `xpath="id"` to read XML attribute | `xpath="@id"` — `@` prefix required for attributes |
| `xpath="text"` to read text content | `xpath="text()"` (function) or `xpath="."` (current node) or `nodeName="text"` (element name) |
| `xpath="../id"` when parent value is an attribute | `xpath="../@id"` |
| `xpath="/root/object"` (JSON-style root) | Use actual XML root element: `xpath="/orders"` |
| Using on large files (>>5 MB) | Use XML_EXTRACT (SAX) instead |
| `parentKey` without `generatedKey` (or vice versa) | Both must be set together; field counts must match |
| Missing `charset` when reading from port/dictionary | **Required** — no auto-detection in these modes |
| `mappingURL` and `mapping` both set | `mappingURL` takes precedence |
| Wrapper `<Context>` for every XML level | Only use `<Context>` where you need output; skip intermediate levels |
