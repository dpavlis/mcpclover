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
- Input port 0 `Port 0 (input)` (optional) — for port reading; field must be `byte`, `cbyte`, or `string`

All attributes go as `<attr name="..."><![CDATA[...]]></attr>` children.

## NODE ATTRIBUTES

| Attr | Default | Notes |
|---|---|---|
| `fileURL` | required | See FILE URL section |
| `charset` | UTF-8 | Encoding of input file — always specify explicitly |
| `dataPolicy` | `strict` | See DATA POLICY section |
| `skipRows` | 0 | Lines to skip from start of file |
| `skipSourceRows` | 0 | Lines to skip per source file (multiple files) |
| `numRecords` | unlimited | Max records to read total |
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

## DATA POLICY

`dataPolicy` controls what happens when a record cannot be parsed according to the metadata.

| Value | Behaviour | Use when |
|---|---|---|
| `strict` | Fail immediately on first parse error | Default; use during development and for trusted well-structured files |
| `controlled` | Route bad records to port 1; continue processing | Need to capture and inspect rejected rows; port 1 must be connected |
| `lenient` | Silently discard bad records; continue | **Avoid** — produces zero output with no error message when the whole file is rejected; hides real problems |

**Never use `lenient` as a workaround for a file that is hard to parse.** If parsing fails, the correct approach is to diagnose using `strict`, understand why records fail, then either fix the metadata or switch to the line-by-line reading pattern.

**`controlled` requires port 1 to be connected** — to TRASH or a writer. If port 1 has no edge, the component raises an init-time error. Port 1 metadata must match the exact 5-field error schema (see ERROR PORT METADATA section) — connecting regular record metadata to port 1 causes a component initialization failure.

## ITERATIVE DEBUG APPROACH

When parsing fails or produces unexpected record counts, iterate using `strict` mode:

1. **Set `dataPolicy="strict"`** — graph fails on the first bad record with a specific error message identifying field name, record number, and the problem.
2. **Read the execution log** — look for `Parsing error:` lines. They name the field, record number, and the value that failed.
3. **Fix the root cause** — wrong delimiter, wrong field count in metadata, missing `eofAsDelimiter`, wrong charset, etc.
4. **Re-run and repeat** — `strict` stops at the first error each time; multiple issues may require multiple iterations.
5. **Switch to `controlled`** only after `strict` succeeds cleanly, if you need ongoing error handling for genuinely dirty production data.

Common error messages and their fixes:

| Error message | Cause | Fix |
|---|---|---|
| `Unexpected default field delimiter, probably record has too many fields` | `fieldDelimiter` matches a character that appears in the data | Change `fieldDelimiter` in metadata to a character not present in the data |
| `Unexpected end of file in record N, field M ("fieldName")` | Last field delimiter not found — EOF reached before the expected record terminator | Set `eofAsDelimiter="true"` on the last field, or ensure `recordDelimiter` matches actual line endings |
| `The log port metadata has invalid format` | Port 1 connected with wrong metadata | Port 1 requires the exact 5-field error schema (see ERROR PORT METADATA) |
| `Component initialization failed` | Port 1 connected but metadata wrong, or `dataPolicy="controlled"` with no port 1 edge | Fix port 1 metadata or connect the edge |

## FILE URL FORMATS

```
${DATAIN_DIR}/input.csv                          local file
${DATAIN_DIR}/data/*.csv                         glob wildcard — reads all matching files
${DATAIN_DIR}/data/file1.csv;file2.csv           semicolon-separated list
zip:(${DATAIN_DIR}/archive.zip)!data/input.csv   single file from ZIP
zip:(${DATAIN_DIR}/archive.zip)!*.csv            all CSVs from ZIP
port:$0.fieldName:discrete                       each port record = one complete "file"
port:$0.fieldName:stream                         all port records concatenated = one stream
port:$0.filePath:source                          port field contains a file path to open
dict:myDictEntry                                 read from dictionary entry
http://example.com/data.csv                      remote HTTP
ftp://user:pass@host/path/file.csv               remote FTP
```

## LINE-BY-LINE READING (non-uniform / complex files)

**When to use:** When the file structure is non-uniform and standard DATA_READER parsing cannot work:
- File has a title/metadata header block before the data rows (variable or fixed length)
- File has a footer block (totals, summaries) after data rows
- Header, data, and footer rows have different field counts or different delimiters
- `skipRows` cannot solve it because the data section boundary is content-dependent
- `dataPolicy="lenient"` produces zero output — the parser is rejecting all rows silently
- Any use of `dataPolicy="lenient"` to mask structural problems in the file

**Strategy:** Use DATA_READER with single-field line metadata to slurp the file one raw line at a time with zero parsing. Every line — blanks, title, column header, data rows, footer — arrives as a plain string. Downstream logic classifies and routes.

### LineMeta — the correct single-field metadata

```xml
<Metadata id="LineMeta">
    <Record name="raw_line" type="delimited" charset="UTF-8">
        <Field name="line" type="string" delimiter="\n|\r\n|\r" eofAsDelimiter="true"/>
    </Record>
</Metadata>
```

**Critical rules:**
- No `recordDelimiter` on `<Record>` — the field delimiter alone drives record boundaries
- `delimiter="\n|\r\n|\r"` on the field — pipe-separated alternatives handle Unix (`\n`), Windows (`\r\n`), and old Mac (`\r`) line endings
- `eofAsDelimiter="true"` on the field — the last line of a file typically has no trailing newline; without this the parser hits EOF before finding the delimiter and fails with `Unexpected end of file in record N, field 1`
- Do NOT set `recordDelimiter="\n"` and `fieldDelimiter="\n"` simultaneously — the parser becomes ambiguous and fails with `Unexpected default field delimiter`
- Do NOT set `delimiter` to a character that appears in the data (e.g. `;` for CSV files)

**DATA_READER node — no skipRows, no dataPolicy:**
```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/export.csv" guiName="Read Lines"
      guiX="30" guiY="150" id="DATA_READER0" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>
```

### Option A — REFORMAT with CTL (parse in-place)

REFORMAT receives each raw line, classifies it, splits on the delimiter, and maps fields by index to the output metadata. No extra component needed. Best when field parsing logic is manageable in CTL.

```xml
<Node enabled="enabled" guiName="Filter + Parse" guiX="300" guiY="150"
      id="REFORMAT0" type="REFORMAT">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    string line = $in.0.line;
    if (isnull(line) || length(trim(line)) == 0) { return SKIP; }
    list[string] parts = split(line, ";");
    if (length(parts) < 13) { return SKIP; }          // header/footer rows have fewer fields
    if (!contains(parts[12], "ExpectedMarker")) { return SKIP; }
    $out.0.Symbol = trim(parts[2]);
    $out.0.Amount = str2double(replace(replace(parts[4], " ", ""), ",", "."));
    return ALL;
}
]]></attr>
</Node>
```

### Option B — Filter REFORMAT + port-reading second DATA_READER

REFORMAT acts as a lightweight line classifier only — drops blanks and structural garbage, passes qualifying raw lines. A second DATA_READER reads those lines via port and parses them using the full target metadata. Best when data rows are well-structured but the surrounding file is not.

```xml
<!-- Stage 1: read all lines raw -->
<Node enabled="enabled" fileURL="${DATAIN_DIR}/export.csv" guiName="Read Lines"
      guiX="30" guiY="150" id="DATA_READER0" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
</Node>

<!-- Stage 2: lightweight classifier — drop blanks and lines without a delimiter -->
<Node enabled="enabled" guiName="Filter Structured Lines" guiX="280" guiY="150"
      id="REFORMAT0" type="REFORMAT">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    string line = $in.0.line;
    if (isnull(line) || length(trim(line)) == 0) { return SKIP; }
    if (!contains(line, ";")) { return SKIP; }   // plain-text header lines have no semicolons
    $out.0.line = line;
    return ALL;
}
]]></attr>
</Node>

<!-- Stage 3: parse filtered lines — each line is one discrete "file" -->
<Node enabled="enabled" fileURL="port:$0.line:discrete" guiName="Parse Data Lines"
      guiX="560" guiY="150" id="DATA_READER1" type="DATA_READER">
    <attr name="charset"><![CDATA[UTF-8]]></attr>
    <attr name="dataPolicy"><![CDATA[strict]]></attr>
</Node>

<Edge fromNode="DATA_READER0:0" id="E0" inPort="Port 0 (in)"    metadata="LineMeta"   outPort="Port 0 (output)" toNode="REFORMAT0:0"/>
<Edge fromNode="REFORMAT0:0"    id="E1" inPort="Port 0 (input)" metadata="LineMeta"   outPort="Port 0 (out)"    toNode="DATA_READER1:0"/>
<Edge fromNode="DATA_READER1:0" id="E2" inPort="Port 0 (in)"    metadata="ParsedMeta" outPort="Port 0 (output)" toNode="NEXT:0"/>
```

**Option B specific rules:**
- Edge to DATA_READER1 input uses `inPort="Port 0 (input)"` (not `Port 0 (in)`)
- `port:$0.fieldName:discrete` — each record from the port = one complete "file" to parse. Use for line-by-line (one parsed record per line).
- `port:$0.fieldName:stream` — all records concatenated = one file stream. Use when multiple port records together form a single logical file.
- **Last field in ParsedMeta must have `eofAsDelimiter="true"`** — each line arrives without a trailing newline, so the parser hits EOF before finding the last field's `\n` delimiter. Without this attribute, DATA_READER1 fails with `Unexpected end of file in record 1, field N`. Example: `<Field name="Trailing" type="string" delimiter="\n" eofAsDelimiter="true"/>`
- Use `dataPolicy="strict"` on DATA_READER1 — do not use `lenient` (hides parse failures silently). Any rows that slip through REFORMAT0 and fail to parse (e.g. column header, footer) will error clearly, allowing diagnosis and fix.
- Do NOT connect port 1 on DATA_READER1 unless you have the correct 5-field error metadata — wrong metadata on port 1 causes a component initialization failure before the graph runs.

## ERROR PORT METADATA (port 1, controlled mode)

Exactly 5 fields in this order — no other structure is accepted:

| # | Type | Description |
|---|---|---|
| 0 | `long` | Record position (1-based) |
| 1 | `integer` | Field position (1-based) |
| 2 | `string`/`byte`/`cbyte` | Raw erroneous record |
| 3 | `string`/`byte`/`cbyte` | Error message |
| 4 | `string` | Source file URL |

Connecting any other metadata to port 1 (e.g. the same record metadata as port 0) causes: `The log port metadata has invalid format` at initialization — the graph will not start.

## PORT READING (general)

DATA_READER reads from an upstream port field instead of a file:

```
port:$0.fieldName:discrete   field contains full file content; one "file" per record
port:$0.fieldName:stream     all records form one stream treated as one file
port:$0.filePath:source      field contains a file path; reader opens that file
```

Input port 0 field type must be `string`, `byte`, or `cbyte`.

## EDGE DECLARATIONS

```xml
<!-- Standard -->
<Edge fromNode="DATA_READER0:0" id="E0" inPort="Port 0 (in)"    metadata="MyMeta"    outPort="Port 0 (output)" toNode="NEXT:0"/>
<!-- Error port (controlled mode) -->
<Edge fromNode="DATA_READER0:1" id="E1" inPort="Port 0 (in)"    metadata="ErrorMeta" outPort="Port 1 (output)" toNode="TRASH0:0"/>
<!-- Port reading input -->
<Edge fromNode="UPSTREAM:0"     id="E2" inPort="Port 0 (input)" metadata="LineMeta"  outPort="Port 0 (out)"    toNode="DATA_READER1:0"/>
```

Note: the input port on DATA_READER uses `inPort="Port 0 (input)"`, not `Port 0 (in)`.

## MISTAKES

| Wrong | Correct |
|---|---|
| `type="UniversalDataReader"` | `type="DATA_READER"` |
| `dataPolicy="lenient"` to handle a hard-to-parse file | Produces zero output silently — use `strict`, diagnose from log, fix root cause or switch to line-by-line |
| `fieldDelimiter="\n"` and `recordDelimiter="\n"` both set on LineMeta | `recordDelimiter=""` (empty) + `fieldDelimiter="\n"` |
| `fieldDelimiter` set to `;` or other data character in LineMeta | Use `\n` as field delimiter; never a character that appears in the data |
| `skipRows` to skip non-uniform header blocks | Only works when header is a fixed line count AND all data rows share the same structure; use line-by-line + REFORMAT for mixed files |
| Omitting `charset` | Always specify; default varies by system and JVM locale |
| `dataPolicy="controlled"` with no edge on port 1 | Port 1 must be connected (to TRASH or a writer) |
| Connecting regular record metadata to port 1 | Port 1 requires the exact 5-field error schema — wrong metadata causes init-time failure |
| `fileURL="port:$0.line:discrete"` without `eofAsDelimiter="true"` on last field | Parser hits EOF before finding the last field delimiter — add `eofAsDelimiter="true"` to the last field in the target metadata |
| `inPort="Port 0 (in)"` on DATA_READER port-reading input edge | Use `inPort="Port 0 (input)"` for the DATA_READER input port |
| `dataPolicy="lenient"` on the port-reading DATA_READER1 | Use `strict` — lenient silently drops rows that fail, hiding real parsing problems |
| Multiple source files with `skipRows` | Use `skipSourceRows` to skip header per file; `skipRows` skips only from the first source |
