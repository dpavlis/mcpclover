# CloverDX STRUCTURE_WRITER — LLM Reference

## What it does
Writes records to a file (local, remote, or port) using a user-defined text structure.
Combines a **header**, repeated **body** (one mask expansion per input record), and a **footer** into a single output file — without needing graph phases.
Primary use case: generating HTML reports, JSON arrays, CSV with custom headers, XML, or any other structured text format from CloverDX records.

No CTL transformation. No record modification. Output format is entirely driven by mask templates.

**Limitation:** Cannot write list or map field types.

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | ✓ | Records for body (one mask expansion per record) | Any |
| Input 1 | optional | Records for header | Any |
| Input 2 | optional | Records for footer | Any |
| Output 0 | optional | For port writing | One field: `byte`, `cbyte`, or `string` |

No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `fileURL` | yes | — | Output file path. Supports graph params, `$$` placeholder for partitioned files. |
| `charset` | no | `UTF-8` | Output encoding. **Always set explicitly.** |
| `mask` | no | XML auto-structure | Body mask — written once per input port 0 record. References `$fieldName` from port 0 metadata. |
| `header` | no | empty | Header mask — written once at the start of the file. References `$fieldName` from port 1 metadata (if connected), or is literal text. **Required if port 1 is connected.** |
| `footer` | no | empty | Footer mask — written once at the end. References `$fieldName` from port 2 metadata (if connected), or is literal text. **Required if port 2 is connected.** |
| `append` | no | `false` | Append to existing file instead of overwriting. |
| `makeDirs` | no | `false` | Auto-create missing output directories. |
| `recordsPerFile` | no | — | Max body records per output file. Header and footer are written to every file. |
| `bytesPerFile` | no | — | Max bytes per output file. |
| `createEmptyFiles` | no | `true` | Create output file even if there are no input records. |
| `skipRecords` | no | `0` | Skip N records before writing. |
| `numRecords` | no | — | Max total records to write. |
| `partitionKey` | no | — | Field name(s) for distributing records to multiple files. |
| `partitionFileTag` | no | `Number file tag` | `Key file tag` = name files by partition key value; default = number sequence. |
| `sortedInput` | no | `false` | When partitioning: set `true` if input is sorted by partition key to avoid opening all output files simultaneously. |

## Mask Syntax

Masks are plain text containing literal content mixed with field references:

```
$fieldName                    — insert field value
$field1 literal text $field2  — mix fields and literal text freely
```

- Field names are preceded by `$`
- Not all fields need to be referenced — use only what's needed
- Masks can span multiple lines (literal newlines are preserved)
- XML/HTML tags, JSON structure, CSV headers — all valid as mask content

### Default body mask (when `mask` not set)
When no `mask` is specified, STRUCTURE_WRITER generates an XML-like structure automatically:
```xml
<recordName>
    <field1name>field1value</field1name>
    <field2name>field2value</field2name>
    ...
</recordName>
```
In most production use cases, set `mask` explicitly.

## Two Usage Modes

### Mode 1: Inline attributes (most common)
Header, body, and footer are all specified as XML attributes — no port 1 or port 2 connection needed. All field references in `mask` come from port 0 (body records). `header` and `footer` are pure literal text.

```xml
<Node type="STRUCTURE_WRITER"
      fileURL="${DATAOUT_DIR}/report.html"
      charset="UTF-8"
      makeDirs="true"
      header="&lt;html&gt;&lt;body&gt;&lt;table&gt;"
      mask="&lt;tr&gt;&lt;td&gt;$id&lt;/td&gt;&lt;td&gt;$name&lt;/td&gt;&lt;/tr&gt;"
      footer="&lt;/table&gt;&lt;/body&gt;&lt;/html&gt;"/>
```

In `.grf` XML, attribute values containing HTML/text structure must be XML-escaped:
- `<` → `&lt;`, `>` → `&gt;`, `"` → `&quot;`
- Newlines → `&#13;&#10;` (CRLF) — the visual editor encodes every line break this way

This escaping is **intentional and required** — the `.grf` is XML and the mask content is just a string attribute value. The sandbox examples confirm this exact encoding in real graphs.

### Mode 2: Port-based header/footer
Connect port 1 for dynamic header records, port 2 for dynamic footer records. The corresponding mask attribute must then be set and can reference `$fieldName` from that port's metadata.

```xml
<!-- Port 1 connected: header comes from upstream component -->
<Node type="STRUCTURE_WRITER"
      fileURL="${DATAOUT_DIR}/output.txt"
      charset="UTF-8"
      header="$header"
      mask="$body"
      footer=""/>
```
`header` must be specified if port 1 is connected. `footer` must be specified if port 2 is connected.

## Real Sandbox Examples

All four sandbox examples use Mode 1 (inline attributes) — the dominant real-world pattern.

### MiscExamples — TopCustomers: HTML table report
```xml
<Node charset="UTF-8" enabled="enabled"
      fileURL="${DATAOUT_DIR}/top-20-customers.html"
      makeDirs="true"
      header="&lt;html&gt;
&lt;body&gt;
&lt;h3&gt;Top 20 Customers by Transaction Amount &lt;/h3&gt;
&lt;table cellpadding=&quot;5&quot; cellspacing=&quot;0&quot; border=&quot;1&quot;&gt;
&lt;tr&gt;
&lt;th&gt;Customer&lt;/th&gt;&lt;th&gt;Amount&lt;/th&gt;&lt;th&gt;Currency&lt;/th&gt;&lt;th&gt;Full Name&lt;/th&gt;
&lt;/tr&gt;"
      mask="&lt;tr&gt;
&lt;td&gt;$customer_id&lt;/td&gt;
&lt;td&gt;$amount&lt;/td&gt;
&lt;td&gt;$currency&lt;/td&gt;
&lt;td&gt;$customer_first_name $customer_last_name&lt;/td&gt;
&lt;/tr&gt;"
      footer="&lt;/table&gt;
&lt;/body&gt;
&lt;/html&gt;"
      id="TOP_20_CUSTOMERS_AS_HTML"
      type="STRUCTURE_WRITER"/>
```
Two fields in a single mask cell: `$customer_first_name $customer_last_name` — concatenated with a space literal.

### MiscExamples — CreditCardFraudDetection: rejects as HTML (fewer columns)
```xml
<Node charset="UTF-8" enabled="enabled"
      fileURL="${DATAOUT_DIR}/missing-customer.html"
      makeDirs="true"
      header="&lt;html&gt;
&lt;body&gt;
&lt;h3&gt;Transactions with missing customer&lt;/h3&gt;
&lt;table cellpadding=&quot;5&quot; cellspacing=&quot;0&quot; border=&quot;1&quot;&gt;
&lt;tr&gt;&lt;th&gt;Transaction&lt;/th&gt;&lt;th&gt;Amount&lt;/th&gt;&lt;th&gt;Currency&lt;/th&gt;&lt;/tr&gt;"
      mask="&lt;tr&gt;
&lt;td&gt;$transaction_id&lt;/td&gt;
&lt;td&gt;$amount&lt;/td&gt;
&lt;td&gt;$currency&lt;/td&gt;
&lt;/tr&gt;"
      footer="&lt;/table&gt;
&lt;/body&gt;
&lt;/html&gt;"
      id="MISSING_CUSTOMER_ID"
      type="STRUCTURE_WRITER"/>
```

### fixExamples.grf — JSON array output
```xml
<Node append="false"
      fileURL="${DATAOUT_DIR}/training_set_1.${TIMESTAMP}.json"
      header="["
      footer="]"
      mask="$json_example"
      id="STRUCTURED_DATA_WRITER"
      type="STRUCTURE_WRITER"/>
```
Body records contain pre-formatted JSON in the `$json_example` field (including trailing comma+newline). Header `[` and footer `]` wrap them into a JSON array. No HTML escaping needed since the header/footer are simple characters. This is the canonical pattern for generating JSON files from CloverDX records.

## Common Patterns

### HTML table report (most common)
```
READER → [transforms] → STRUCTURE_WRITER(header=<html><table>, mask=<tr><td>$f</td></tr>, footer=</table></html>)
```

### JSON array file
```
READER → REFORMAT(produces $json_line = writeJson(variant) + ",\n") → STRUCTURE_WRITER(header="[", mask="$json_line", footer="]")
```

### CSV with custom header
```
STRUCTURE_WRITER(header="id,name,amount\n", mask="$id,$name,$amount\n", footer="")
```

### Per-partition files (one file per category)
```xml
<Node type="STRUCTURE_WRITER"
      fileURL="${DATAOUT_DIR}/report_$$.html"
      partitionKey="category"
      partitionFileTag="Key file tag"
      header="&lt;html&gt;&lt;table&gt;"
      mask="&lt;tr&gt;&lt;td&gt;$name&lt;/td&gt;&lt;/tr&gt;"
      footer="&lt;/table&gt;&lt;/html&gt;"/>
```
`$$` in `fileURL` is replaced by the partition key value (when `partitionFileTag="Key file tag"`) or sequence number (default).

### recordsPerFile — split body across multiple files, shared header/footer
```xml
<Node type="STRUCTURE_WRITER"
      fileURL="${DATAOUT_DIR}/page_$$.txt"
      recordsPerFile="50"
      header="--- PAGE HEADER ---&#10;"
      mask="$body&#10;"
      footer="--- PAGE FOOTER ---&#10;"/>
```
Header and footer are written to **every** output file. Only body is split. `&#10;` = newline in XML attribute.

## Output File Structure

```
[header mask — written once]
[body mask — written once per port 0 record]
[body mask — written once per port 0 record]
...
[footer mask — written once]
```

When `recordsPerFile=N`, structure is:
```
[header][body × N][footer]   ← file 1
[header][body × N][footer]   ← file 2
...
```

## Edge Declarations
```xml
<!-- Body (always required) -->
<Edge fromNode="UPSTREAM:0" outPort="Port 0 (out)" toNode="WRITER:0" inPort="Port 0 (Body port)"/>

<!-- Header (optional, port 1) -->
<Edge fromNode="HEADER_SRC:0" outPort="Port 0 (out)" toNode="WRITER:1" inPort="Port 1 (Header port)"/>

<!-- Footer (optional, port 2) -->
<Edge fromNode="FOOTER_SRC:0" outPort="Port 0 (out)" toNode="WRITER:2" inPort="Port 2 (Footer port)"/>
```

## Decision Guide

| Need | Use |
|---|---|
| Generate HTML report from records | STRUCTURE_WRITER with HTML mask |
| Generate JSON array file | STRUCTURE_WRITER with `header="["`, `footer="]"`, pre-formatted `$json_line` mask |
| Custom CSV with header row | STRUCTURE_WRITER (simpler than FLAT_FILE_WRITER for custom headers) |
| Fill a text/XML template | STRUCTURE_WRITER with template content in `header` / `mask` |
| Write standard flat file | FLAT_FILE_WRITER (more appropriate for simple delimited/fixed-length files) |
| Write Excel spreadsheet | SPREADSHEET_WRITER |

## Mistakes

| Wrong | Correct |
|---|---|
| Forgetting XML-escaping in `header`/`mask`/`footer` attributes | `<` → `&lt;`, `>` → `&gt;`, `"` → `&quot;` in XML attribute values |
| `$field` reference with field not in port 0 metadata | Only port 0 fields usable in `mask`; port 1 fields in `header`; port 2 in `footer` |
| Connecting port 1 without setting `header` attribute | `header` must be specified when port 1 is connected |
| Connecting port 2 without setting `footer` attribute | `footer` must be specified when port 2 is connected |
| Expecting `recordsPerFile` to split header/footer too | `recordsPerFile` affects body only — header and footer appear in every split file |
| Writing list or map fields | Not supported — STRUCTURE_WRITER cannot serialize list/map types |
| Omitting `charset` | Always set explicitly, e.g. `charset="UTF-8"` |
| Many partition files causing "too many open files" error | Sort input by partition key and set `sortedInput="true"` |
| `$$` in fileURL without `partitionKey` | `$$` requires partitioning to be active (`partitionKey` must be set) |
| Forgetting `makeDirs="true"` for deep output paths | Without it, write fails if output directory doesn't exist |
