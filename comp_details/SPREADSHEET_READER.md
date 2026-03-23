# CloverDX SPREADSHEET_READER — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x SpreadsheetDataReader component.
> All mapping XML forms and attribute names are verified from official docs and confirmed real GRF examples.

---

## COMPONENT OVERVIEW

- **Component type:** `SPREADSHEET_READER`
- **Purpose:** Reads data from XLS (Excel 97/2003 BIFF8) or XLSX (Excel 2007+) spreadsheets.
- **Input ports:** 0–1 (port 0 optional — for reading file from byte/cbyte field)
- **Output ports:** port 0 (valid records, required), port 1 (error records, optional)

---

## COMPONENT SKELETON

```xml
<Node dataPolicy="controlled" enabled="enabled" fileURL="${DATAIN_DIR}/input.xlsx" id="SPREADSHEET_READER0" sheet="Sheet1" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A1"/>
                <headerRange begin="B1"/>
                <headerRange begin="C1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Edge outPort name:** `Port 0 (output)` for valid records, `Port 1 (output)` for errors.

---

## NODE-LEVEL ATTRIBUTES

| Attribute | Required | Description |
|---|---|---|
| `type` | yes | Always `SPREADSHEET_READER` |
| `fileURL` | yes | Input file path. Supports parameters, wildcards, port reading. |
| `sheet` | no | Sheet name or 0-based index. Multiple: comma-separated. Wildcards: `*` and `?`. Default: first sheet. |
| `dataPolicy` | no | Error handling. **Deprecated** — prefer port connection. See below. |
| `attitude` | no | Read mode. `IN_MEMORY` (default) or `STREAM`. Required for formula reading. |
| `enabled` | no | `enabled` (default) or `disabled` |
| `id` | yes | Unique node ID in the graph |
| `guiName`, `guiX`, `guiY` | no | Visual layout only |

### dataPolicy values (deprecated — use error port connection instead)
- `strict` — stop on first error
- `controlled` — route errors to output port 1 (requires port 1 edge)
- `lenient` — silently skip errors

**Preferred approach:** connect an edge to port 1 to automatically enable controlled behavior. If port 1 has no edge, component uses strict behavior.

### Sheet selection examples
```
sheet="Sheet1"          single sheet by name
sheet="0"               first sheet by index (zero-based)
sheet="*"               all sheets (wildcard)
sheet="Orders,Returns"  multiple named sheets
sheet="Q?_*"            wildcard pattern
```

### fileURL examples
```
${DATAIN_DIR}/input.xlsx
${DATAIN_DIR}/others/O*.xls      file glob wildcard
port:$0.filePath                  read path from input port field
```

### Read mode (attitude)
```xml
<!-- In-memory (default) — required for formula reading -->
<Node attitude="IN_MEMORY" ... type="SPREADSHEET_READER">

<!-- Stream — use for large files that won't fit in memory -->
<Node attitude="STREAM" ... type="SPREADSHEET_READER">
```
If `attitude` is omitted, in-memory mode is used.

---

## MAPPING MODES

There are four ways to configure reading, in order of specificity:

### Mode 1 — Auto (no mapping attribute)
Omit the `<attr name="mapping">` entirely. The first row is treated as headers and mapped to output metadata fields by name. Data starts at row 2. Simplest form, used when spreadsheet layout is standard.

```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/orders.xlsx" id="READER0" type="SPREADSHEET_READER"/>
```

### Mode 2 — Inline mapping (most common for LLM generation)
Embed a `<mapping>` XML block in `<attr name="mapping">`. All examples below use this mode.

### Mode 3 — External mapping file
```xml
<Node fileURL="${DATAIN_DIR}/input.xlsx" id="READER0" type="SPREADSHEET_READER">
    <attr name="mappingURL">${GRAPH_DIR}/shared_mapping.xml</attr>
</Node>
```

### Mode 4 — Input port reading (byte stream)
Connect an input port carrying a `byte` or `cbyte` field containing the file contents. Useful for files retrieved from HTTP, database BLOBs, etc.

---

## MAPPING XML STRUCTURE

The mapping XML goes inside `<attr name="mapping"><![CDATA[ ... ]]></attr>`.

### Skeleton
```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>    <!-- VERTICAL or HORIZONTAL -->
        <step>1</step>                          <!-- rows per step (VERTICAL) or cols per step (HORIZONTAL) -->
        <writeHeader>true</writeHeader>         <!-- always include; always true for reader -->
    </globalAttributes>
    <defaultSkip>1</defaultSkip>               <!-- global data offset: rows to skip after header -->
    <headerGroups>
        <!-- one or more headerGroup elements -->
    </headerGroups>
</mapping>
```

### globalAttributes

| Element | Values | Meaning |
|---|---|---|
| `<orientation>` | `VERTICAL` / `HORIZONTAL` | VERTICAL: records advance by rows (normal tables). HORIZONTAL: records advance by columns. |
| `<step>` | integer | In VERTICAL mode: always `1`. In HORIZONTAL mode: number of source columns that form one record (e.g. `2` for paired columns). |
| `<writeHeader>` | `true` | Always include this; always `true` for reader (no effect but part of canonical format). |

### defaultSkip
Number of rows (VERTICAL) or columns (HORIZONTAL) between the header cell and the first data cell.

- `defaultSkip=1` — header at row 1, data starts at row 2 (skip 1 row after header).
- `defaultSkip=3` — header at some row, data starts 3 rows after that header row.

`defaultSkip` sets the **global default**. Each `headerGroup` can override with its own `skip` attribute. In typical use, both are set to the same value.

---

## HEADERGROUP FORMS

A `<headerGroup>` maps one or more spreadsheet cells to output fields. Two mutually exclusive mapping strategies exist:

### Strategy A — autoMappingType (maps a batch of cells by name or order)
Use when multiple cells in a row share the same mapping strategy.

```xml
<headerGroup skip="1">
    <autoMappingType>NAME</autoMappingType>
    <headerRanges>
        <headerRange begin="A1"/>
        <headerRange begin="B1"/>
        <headerRange begin="C1"/>
        <headerRange begin="D1"/>
    </headerRanges>
</headerGroup>
```

`autoMappingType` values:
- `NAME` — cell content is matched to a metadata field with the same name or label
- `ORDER` — cells are mapped to fields in declaration order

### Strategy B — cloverField (maps one cell to one specific named field)
Use when you need to map specific non-contiguous cells to specific named fields (explicit mapping). One `headerGroup` per field.

```xml
<headerGroup skip="1">
    <cloverField>Order_Id</cloverField>
    <headerRanges>
        <headerRange begin="A1"/>
    </headerRanges>
</headerGroup>
<headerGroup skip="1">
    <cloverField>Customer_Name</cloverField>
    <headerRanges>
        <headerRange begin="C1"/>
    </headerRanges>
</headerGroup>
```

**CRITICAL:** `autoMappingType` and `cloverField` are mutually exclusive within one `headerGroup`. Never put both in the same group.

### headerGroup attributes

| Attribute | Meaning |
|---|---|
| `skip` | Local data offset — overrides `defaultSkip`. Rows to skip between header cell and first data cell. |

### headerRange@begin
Cell reference in standard A1 notation: `A1`, `B5`, `C1`, etc.
- In VERTICAL mode: this is the header/leading cell; reading advances downward.
- In HORIZONTAL mode: this is the header/leading cell; reading advances rightward.

---

## CONFIRMED WORKING EXAMPLES

### Example 1 — Simple table, headers in row 1, data from row 2 (autoMappingType NAME)
Most common pattern.

```xml
<Node dataPolicy="controlled" enabled="enabled" fileURL="${DATAIN_DIR}/orders.xlsx" id="READER0" sheet="Sheet0" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A1"/>
                <headerRange begin="B1"/>
                <headerRange begin="C1"/>
                <headerRange begin="D1"/>
                <headerRange begin="E1"/>
                <headerRange begin="F1"/>
                <headerRange begin="G1"/>
                <headerRange begin="H1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

One `headerGroup` with `autoMappingType>NAME` covers all columns. `defaultSkip=1` and `skip="1"` both 1 — data starts at row 2.

---

### Example 2 — Non-default layout (header at row 5, data offset 3)
From `SpreadsheetReadWrite.grf`. County totals spreadsheet with header at row 5, data starting 3 rows below that.

```xml
<Node dataPolicy="controlled" enabled="enabled" fileURL="${DATAIN_DIR}/others/county_totals_2009.xls" id="SPREADSHEET_READER0" sheet="County" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>3</defaultSkip>
    <headerGroups>
        <headerGroup skip="3">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A5"/>
                <headerRange begin="B5"/>
                <headerRange begin="C5"/>
                <headerRange begin="D5"/>
                <headerRange begin="E5"/>
                <headerRange begin="F5"/>
                <headerRange begin="G5"/>
                <headerRange begin="H5"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

Header at row 5 → `headerRange begin="X5"`. `defaultSkip=3` and `skip="3"` → data starts at row 8 (3 rows after row 5).

---

### Example 3 — Explicit cloverField mapping (non-contiguous or excluded columns)
From `SpreadsheetReadWrite.grf`. Maps specific columns to specific named fields, skipping others.

```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/data.xlsx" id="READER0" sheet="Sheet1" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <cloverField>COUNTY_DESCRIPTION</cloverField>
            <headerRanges>
                <headerRange begin="B1"/>
            </headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>NUMBER_OF_FIRMS</cloverField>
            <headerRanges>
                <headerRange begin="C1"/>
            </headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>EMPLOYMENT</cloverField>
            <headerRanges>
                <headerRange begin="E1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

One `headerGroup` per field. Columns A and D are skipped by not mapping them.

---

### Example 4 — Multiple files with wildcard + all sheets (no mapping)
Read all XLS files matching `O*.xls`, all sheets, auto mode.

```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/others/O*.xls" id="XLS_ORDERS" sheet="*" type="SPREADSHEET_READER"/>
```

No mapping — auto mode maps by name from first row. `sheet="*"` reads all sheets sequentially.

---

### Example 5 — Multi-sheet reading with sheet name autofilled into a field
Reads all sheets; sheet name is filled into field `ShipCountry` via metadata autofilling.

```xml
<Node enabled="enabled" fileURL="${DATAOUT_DIR}/ordersByCountry.xlsx" id="ORDERS_BY_COUNTRY" sheet="*" type="SPREADSHEET_READER"/>
```

The autofilling is configured in **metadata** (not the mapping), by setting `auto_filling="sheet_name"` on the target field:

```xml
<Field auto_filling="sheet_name" label="Sheet" name="ShipCountry" type="string"/>
```

**Autofilling function values for metadata fields:**

| Value | Fills with |
|---|---|
| `sheet_name` | Name of the current sheet being read |
| `source_name` | Name of the source file |
| `source_timestamp` | Last modified timestamp of the source file |
| `source_size` | Size of the source file in bytes (0 if remote/archive) |

---

### Example 6 — Horizontal reading with step=2 (value + note column pairs)
From `SpreadsheetReadWrite.grf`. Tax statistics: HORIZONTAL orientation, `step=2` (each record spans 2 source columns — value column + note column).

```xml
<Node attitude="IN_MEMORY" enabled="enabled" fileURL="${DATAIN_DIR}/others/10staxss.xls" id="SPREADSHEET_READER1" sheet="Sheet1" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>HORIZONTAL</orientation>
        <step>2</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <cloverField>State</cloverField>
            <headerRanges>
                <headerRange begin="B4"/>
            </headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Total_taxes</cloverField>
            <headerRanges>
                <headerRange begin="B9"/>
            </headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Total_taxes_note</cloverField>
            <headerRanges>
                <headerRange begin="C9"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

- `orientation>HORIZONTAL` — records advance left to right
- `step>2` — each record occupies 2 columns (B=value, C=note)
- `attitude="IN_MEMORY"` — required for in-memory processing; also required for formula reading
- Each field mapped with `cloverField`, `headerRange` anchors to specific non-contiguous cells

---

### Example 7 — One record per source file (form/template reading)
Limit to 1 record per file using `maxRecordsPerSource` node attribute.

```xml
<Node enabled="enabled" fileURL="${DATAIN_DIR}/forms/*.xlsx" id="READER0" maxRecordsPerSource="1" sheet="Tax data" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>true</writeHeader>
    </globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A1"/>
                <headerRange begin="B1"/>
                <headerRange begin="C1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

---

## ALL NODE ATTRIBUTES REFERENCE

| XML Attribute | Description | Example value |
|---|---|---|
| `type` | Component type | `SPREADSHEET_READER` |
| `id` | Unique node ID | `READER0` |
| `fileURL` | Input file(s) | `${DATAIN_DIR}/file.xlsx` |
| `sheet` | Sheet selection | `Sheet1` / `0` / `*` / `Sheet1,Sheet2` |
| `attitude` | Read mode | `IN_MEMORY` (default) / `STREAM` |
| `dataPolicy` | Error policy (deprecated) | `strict` / `controlled` / `lenient` |
| `numRecords` | Max total records | `1000` |
| `skipRecords` | Records to skip globally | `5` |
| `maxRecordsPerSource` | Max records per file | `1` |
| `skipRecordsPerSource` | Records to skip per file | `0` |
| `maxRecordsPerSpreadsheet` | Max records per sheet | `500` |
| `skipRecordsPerSpreadsheet` | Records to skip per sheet | `0` |
| `maxErrorCount` | Max allowed errors before failure (controlled mode) | `0` (fail on first) |
| `incrementalFile` | Path to incremental state file | `${PROJ_DIR}/inc/state.txt` |
| `incrementalKey` | Field name for incremental tracking | `Order_Id` |
| `password` | Decryption password for protected files | `secret` |
| `enabled` | Enable/disable node | `enabled` |
| `guiName` | Display name in graph editor | `My Reader` |
| `guiX`, `guiY` | Visual position | `100`, `200` |

---

## ERROR PORT METADATA TEMPLATE

When output port 1 is connected, each parsing error produces one error record:

| Field | Type | Description |
|---|---|---|
| `recordID` | `integer` | Index of the failed record (1-based) |
| `file` | `string` | Source filename |
| `sheet` | `string` | Sheet name where error occurred |
| `fieldIndex` | `integer` | Zero-based index of the target field |
| `fieldName` | `string` | Name of the target field |
| `cellCoords` | `string` | Cell address (e.g. `D7`) |
| `cellValue` | `string` | Raw cell value that caused the error |
| `cellType` | `string` | Excel cell type (e.g. `String`, `Numeric`) |
| `cellFormat` | `string` | Excel format string (e.g. `#,##0`) |
| `message` | `string` | Human-readable error description |

One error record per field error. A row with 3 bad values produces 3 error records. Group by `recordID` to aggregate errors per source row.

---

## SKIP / OFFSET LOGIC

```
Row 1: [Header cell A1]   <- headerRange begin="A1"
Row 2: [skipped]          |
Row 3: [DATA STARTS]      <- skip=2 means skip 2 rows after header
```

- `defaultSkip` in `<mapping>` = global default applied to all header groups
- `skip` on `<headerGroup>` = local override for that group
- Both should be equal in typical use
- For zig-zagged multi-row layouts, different groups can have different local skip values

**Common values:**

| Header row | Data starts | defaultSkip | skip on headerGroup |
|---|---|---|---|
| Row 1 | Row 2 | `1` | `"1"` |
| Row 1 | Row 4 | `3` | `"3"` |
| Row 5 | Row 8 | `3` | `"3"` (with `begin="X5"`) |

---

## FORMULA, FORMAT, AND HYPERLINK EXTRACTION

These are per-field options typically configured via the visual Mapping Editor.

| Feature | Requirement | Notes |
|---|---|---|
| **Read formula** | `attitude="IN_MEMORY"` required | Returns Excel formula string (e.g. `=SUM(A1:A5)`) into a `string` target field |
| **Read format** | None | Returns Excel format string (e.g. `#,##0`) into a `string` target field |
| **Read hyperlink** | None | Returns URL into a `string` target field. Single-cell hyperlinks only. |
| **Raw numeric value** | Set field format `excel:raw` in metadata | Returns full-precision number without formatting; available for XLS and XLSX |

---

## READING DATES

- Always read dates into `date` typed metadata fields, not `string`.
- Set field format in metadata to match the Excel format, e.g. `excel:MM/DD/YY`.
- If you must read as string, note the display format depends on locale and may not match Excel.
- To convert date strings, use `isDate` in a downstream VALIDATOR.

---

## EDGE DECLARATIONS

```xml
<Edge fromNode="SPREADSHEET_READER0:0" id="Edge0" inPort="Port 0 (in)" metadata="MetaMyRecord" outPort="Port 0 (output)" toNode="NEXT_COMPONENT:0"/>
<Edge fromNode="SPREADSHEET_READER0:1" id="Edge1" inPort="Port 0 (in)" metadata="MetaErrors"   outPort="Port 1 (output)" toNode="ERROR_WRITER:0"/>
```

---

## TYPICAL GRAPH PATTERNS

- **Read and validate:** `SpreadsheetDataReader → VALIDATOR → valid/rejected CSVs`
- **Read, type-convert, load:** `SpreadsheetDataReader → Map (Reformat) → DatabaseWriter`
- **Multi-file consolidation:** `SpreadsheetDataReader(O*.xls, sheet=*) → FAST_SORT → CloverDataWriter`
- **Form extraction:** `SpreadsheetDataReader(maxRecordsPerSource=1) → Map → FlatFileWriter`
- **Partitioned output by sheet:** `SpreadsheetDataReader(sheet=*) → autofill sheet_name → Partition → SpreadsheetDataWriter`

---

## DECISION GUIDE: WHICH MAPPING TO USE

| Scenario | Use |
|---|---|
| Header row at row 1, field names match metadata | `autoMappingType>NAME`, `defaultSkip=1`, `skip="1"` |
| Header row at row 1, no headers or column order matters | `autoMappingType>ORDER`, `defaultSkip=1`, `skip="1"` |
| Header row not at row 1 (e.g. row 5) | `begin="A5"`, `defaultSkip=3`, `skip="3"` |
| Non-contiguous columns or exclude specific columns | `cloverField` per headerGroup |
| All columns, many files, headers match field names | `autoMappingType>NAME` (one group, all ranges) |
| No mapping config at all needed | Omit `<attr name="mapping">` entirely (auto mode) |
| Horizontal layout (fields in rows, records in columns) | `orientation>HORIZONTAL`, set `step` to columns per record |
| Formula values needed | `attitude="IN_MEMORY"` required |

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| `step=1` in HORIZONTAL mode for paired columns | Set `step=2` (or however many columns form one record) |
| `defaultSkip` not matching `headerGroup skip` | Both should be equal in typical single-offset use |
| `headerRange begin="A1"` when header is at row 5 | Use `begin="A5"` to anchor the header cell correctly |
| Omitting `attitude="IN_MEMORY"` when reading formulas | Formula reading requires in-memory mode |
| Reading dates into `string` fields | Use `date` typed metadata fields |
| `autoMappingType` and `cloverField` in same headerGroup | Mutually exclusive — use one or the other per group |
| `autoMappingType>NAME` when headers don't match field names | Use `ORDER` or explicit `cloverField` mapping instead |
| `sheet="*"` with heterogeneous sheet schemas | All sheets must share the same logical schema with wildcard reads |
