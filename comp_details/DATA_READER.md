# CloverDX DATA_READER — LLM Reference (7.3.x)

`DATA_READER` is the canonical type string. `UniversalDataReader` is an alias — do not use it in generated XML.

## SKELETON

```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/input.csv" guiName="Read CSV"
      guiX="30" guiY="150" id="DATA_READER0" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>
```

- Output port 0 `Port 0 (output)` — parsed records (required)
- Output port 1 `Port 1 (output)` — error records (optional, controlled mode only)
- Input port 0 (optional) — for port reading; field must be `byte`, `cbyte`, or `string`

All attributes go as `<attr name="..."><![CDATA[...]]></attr>` children.

## NODE ATTRIBUTES

| Attr | Default | Notes |
|---|---|---|
| `fileURL` | required | See FILE URL section |
| `charset` | UTF-8 | Encoding of input file |
| `dataPolicy` | `strict` | `strict` = fail on first error; `controlled` = route errors to port 1; `lenient` = silently skip bad records |
| `skipRows` | 0 | Lines to skip from start of file (or per source with `skipSourceRows`) |
| `numRecords` | unlimited | Max records to read total |
| `skipSourceRows` | 0 | Lines to skip per source file (when reading multiple files) |
| `numSourceRecords` | unlimited | Max records per source file |
| `trim` | false | Strip leading/trailing whitespace from string fields |
| `quotedStrings` | (from metadata) | Enable quoted field parsing |
| `quoteCharacter` | (from metadata) | `"` or `'` |
| `missingColumnHandling` | treat as error | `fill_with_null` to accept short records |
| `maxErrorCount` | unlimited | Max errors before abort (controlled mode) |
| `treatMultipleDelimitersAsOne` | false | Collapse consecutive delimiters |
| `incrementalFile` | — | Path to incremental state file (pair with `incrementalKey`) |
| `incrementalKey` | — | Field name tracking last read position |
| `verbose` | false | More detailed error messages (lower performance) |

**`dataPolicy` warning:** `lenient` silently discards all parse errors — zero output with no indication of what failed. Prefer `controlled` with port 1 connected for diagnostics.

## FILE URL FORMATS

```
${DATAIN_DIR}/input.csv                 local file
${DATAIN_DIR}/data/*.csv                glob wildcard — reads all matching files
${DATAIN_DIR}/data/file1.csv;file2.csv  semicolon-separated list
zip:(${DATAIN_DIR}/archive.zip)!data/input.csv   single file from ZIP
zip:(${DATAIN_DIR}/archive.zip)!*.csv            all CSVs from ZIP
port:$0.fileContent:discrete            read content from input port field (one record per field value)
port:$0.fileContent:stream              read content from input port field (streaming)
port:$0.filePath:source                 read file whose path is in input port field
dict:myDictEntry                        read from dictionary entry
http://example.com/data.csv             remote HTTP
ftp://user:pass@host/path/file.csv      remote FTP
```

## LINE-BY-LINE READING (non-uniform / complex files)

**When to use:** When standard DATA_READER parsing cannot work because the file structure is non-uniform. Indicators:
- File has a title/metadata header block of variable or fixed length before the data rows
- File has a footer block (totals row, summary section) after data rows
- Header and data rows have different numbers of fields or different delimiters
- `skipRows` cannot solve it because the data section boundary is content-dependent, not line-count-dependent
- `dataPolicy="lenient"` produces zero output — the parser is rejecting rows silently

**Strategy:** Use DATA_READER with single-field line metadata to read the entire file one line at a time with no parsing. Every line — blanks, title, column header, data, footer — arrives as a raw string. Downstream logic classifies and parses.

**Two options for downstream processing:**

**Option A — REFORMAT with CTL** (recommended): split the raw line string in CTL, classify by field count or content markers, parse fields by index. Full control, no extra component. Use when parsing logic is straightforward.

**Option B — Port-reading second DATA_READER**: REFORMAT filters and passes qualifying raw lines to a second DATA_READER configured with `fileURL="port:$0.line:discrete"` and the full target metadata. The second reader does the actual field parsing. Use when the data rows are well-structured but the surrounding file is not — avoids re-implementing delimiter parsing in CTL.

**Metadata for line-by-line reading:**
```xml
<Metadata id="LineMeta">
    <Record fieldDelimiter="\n" name="raw_line" recordDelimiter="" type="delimited" charset="UTF-8">
        <Field name="line" type="string" delimiter="\n"/>
    </Record>
</Metadata>
```

Critical: `recordDelimiter=""` (empty string) + `fieldDelimiter="\n"`. Do NOT set both `fieldDelimiter` and `recordDelimiter` to `\n` — parser becomes ambiguous. Do NOT use a character that appears in the data as `fieldDelimiter` (e.g. `;` for semicolon-delimited files).

**DATA_READER node — no skipRows, no dataPolicy:**
```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/export.csv" guiName="Read Lines"
      guiX="30" guiY="150" id="DATA_READER0" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>
```

**REFORMAT CTL pattern to classify and parse lines:**
```xml
<Node enabled="enabled" guiName="Filter + Parse" guiX="300" guiY="150"
      id="REFORMAT0" type="REFORMAT">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    string line = $in.0.line;
    // Skip blanks
    if (isnull(line) || length(trim(line)) == 0) {
        return SKIP;
    }
    // Split and check field count
    list[string] parts = split(line, ";");
    if (length(parts) < 13) {
        return SKIP;   // header/footer lines have fewer fields
    }
    // Classify by content of a known field
    if (!contains(parts[12], "ExpectedMarker")) {
        return SKIP;
    }
    // Parse fields by index
    $out.0.Symbol = trim(parts[2]);
    $out.0.Amount = str2double(replace(replace(parts[4], " ", ""), ",", "."));
    return ALL;
}
]]></attr>
</Node>
```

**Option B — REFORMAT passes qualifying lines to a second DATA_READER via port:**
```xml
<!-- Stage 1: read all lines raw -->
<Node enabled="enabled" fileURL="${DATAIN_DIR}/export.csv" guiName="Read Lines"
      guiX="30" guiY="150" id="DATA_READER0" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>
<!-- Stage 2: classify lines, pass data lines only -->
<Node enabled="enabled" guiName="Filter Lines" guiX="280" guiY="150" id="REFORMAT0" type="REFORMAT">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    string line = $in.0.line;
    if (isnull(line) || length(trim(line)) == 0) { return SKIP; }
    list[string] parts = split(line, ";");
    if (length(parts) < 14) { return SKIP; }         // skip header/footer
    if (!contains(parts[12], "DataMarker")) { return SKIP; }
    $out.0.line = line;   // pass the raw line through unchanged
    return ALL;
}
]]></attr>
</Node>
<!-- Stage 3: second DATA_READER parses the filtered lines via port -->
<Node enabled="enabled" fileURL="port:$0.line:discrete" guiName="Parse Data Lines"
      guiX="560" guiY="150" id="DATA_READER1" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>
<Edge fromNode="DATA_READER0:0" id="E0" inPort="Port 0 (in)" metadata="LineMeta"    outPort="Port 0 (output)" toNode="REFORMAT0:0"/>
<Edge fromNode="REFORMAT0:0"    id="E1" inPort="Port 0 (in)" metadata="LineMeta"    outPort="Port 0 (out)"    toNode="DATA_READER1:0"/>
<Edge fromNode="DATA_READER1:0" id="E2" inPort="Port 0 (in)" metadata="ParsedMeta"  outPort="Port 0 (output)" toNode="NEXT:0"/>
```
`LineMeta` is the same single-field metadata on both raw edges. `ParsedMeta` is the full target metadata on the second reader's output. The second DATA_READER's input port 0 field must be `string` type.

`port:$0.fieldName:discrete` — each record from the port is treated as one complete "file".
`port:$0.fieldName:stream` — all records together form a single stream treated as one file.

## PORT READING (general — not line-by-line)

DATA_READER can also read file content or file paths delivered directly from an upstream component's output port, independent of the line-by-line pattern:

```
port:$0.fileContent:discrete   field contains full file content; one "file" per record
port:$0.fileContent:stream     all records form one stream
port:$0.filePath:source        field contains a file path; reader opens that file
```

## ERROR PORT METADATA (port 1, controlled mode)

Exactly 5 fields in this order:

| # | Type | Description |
|---|---|---|
| 0 | `long` | Record position (1-based) |
| 1 | `integer` | Field position (1-based) |
| 2 | `string`/`byte`/`cbyte` | Raw erroneous record |
| 3 | `string`/`byte`/`cbyte` | Error message |
| 4 | `string` | Source file URL |

## EDGE DECLARATIONS

```xml
<!-- Standard -->
<Edge fromNode="DATA_READER0:0" id="E0" inPort="Port 0 (in)" metadata="MyMeta" outPort="Port 0 (output)" toNode="NEXT:0"/>
<!-- With error port -->
<Edge fromNode="DATA_READER0:1" id="E1" inPort="Port 0 (in)" metadata="ErrorMeta" outPort="Port 1 (output)" toNode="TRASH0:0"/>
```

## MISTAKES

| Wrong | Correct |
|---|---|
| `type="UniversalDataReader"` | `type="DATA_READER"` |
| `dataPolicy="lenient"` on non-uniform file | Produces zero output with no error — use line-by-line pattern instead |
| `fieldDelimiter="\n"` and `recordDelimiter="\n"` both set on single-field metadata | Sets `recordDelimiter=""` (empty) and `fieldDelimiter="\n"` |
| `fieldDelimiter` set to a character that appears in the data (e.g. `;` for CSV) in line-by-line mode | Use a character never present in the data, or leave fieldDelimiter and rely on recordDelimiter="" |
| `skipRows` to skip non-uniform header blocks | Only works when header is a fixed number of lines AND data rows all share the same structure — use line-by-line + REFORMAT for mixed files |
| Omitting `charset` | Specify explicitly; default varies by system |
| `dataPolicy="controlled"` with no edge on port 1 | Port 1 must be connected (to TRASH or a writer) for controlled mode to route errors |
| Port reading with wrong `fileURL` format | Use `port:$0.fieldName:discrete` or `port:$0.fieldName:stream`; field type must be `string`/`byte`/`cbyte` |
| Multiple source files with `skipRows` | Use `skipSourceRows` to skip header per file; `skipRows` skips only from the first file |
