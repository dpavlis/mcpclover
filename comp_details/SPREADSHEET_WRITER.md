# CloverDX SPREADSHEET_WRITER — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX 7.3.x SPREADSHEET_WRITER (SpreadsheetDataWriter) component.
> Incorporates confirmed working patterns from real graph examples and official docs.

---

## COMPONENT SKELETON

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/output.xlsx" guiName="MyWriter" guiX="400" guiY="80" id="MY_WRITER" sheet="Sheet1" type="SPREADSHEET_WRITER" writeMode="CREATE_FILE_IN_STREAM">
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
            <cloverField>My_Field</cloverField>
            <headerRanges>
                <headerRange begin="A1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Ports:** input `0` (records to write) — required. Optional output `0` for port writing (`byte`/`cbyte`).

---

## NODE-LEVEL ATTRIBUTES

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="SPREADSHEET_WRITER"` | yes | Component type identifier |
| `fileURL` | yes | Output file path. Supports graph parameters, wildcards for partitioning, `#` placeholder for partition numbering. |
| `sheet` | no | Sheet name or 0-based index. Use `$FIELD_NAME` for dynamic sheet name from a data field. Separate multiple sheets with `;`. Default: auto-named new sheet. |
| `writeMode` | no | How data is written — see Write Modes table below |
| `existingSheetsActions` | no | What to do if target sheet already exists — see table below |
| `templateFileURL` | no | Path to template spreadsheet file. Copied to output then populated with data. |
| `makeDirs` | no | `true` to auto-create missing output directories. Default: `false`. |
| `partitionKey` | no | Metadata field name whose values control file partitioning |
| `partitionFileTag` | no | `keyNameFileTag` to name output files by key value; default is numeric (`numberFileTag`) |
| `enabled` | no | Standard enabled flag |

---

## WRITE MODES

| XML `writeMode` value | Description | Streaming | Notes |
|---|---|---|---|
| `CREATE_FILE_IN_STREAM` | Creates new file, streaming mode | Yes (XLSX only) | **Fastest — use by default for new files** |
| `OVERWRITE_SHEET_IN_STREAM` | Overwrites entire sheet, streaming | Yes (XLSX only) | Entire file still loaded before write — memory-intensive for large existing files |
| `CREATE_FILE_IN_MEMORY` | Creates new file, in-memory | No | Slower; use when formula evaluation required |
| `OVERWRITE_IN_SHEET_IN_MEMORY` | Overwrites existing cells in place, in-memory | No | For multiple write passes to same sheet |
| `INSERT_INTO_SHEET_IN_MEMORY` | Inserts data, shifts existing cells down | No | **Required when writing to templates** |
| `APPEND_TO_SHEET_IN_MEMORY` | Appends after last row of existing data | No | For incremental writes |

**Rule:** Use `CREATE_FILE_IN_STREAM` for new files. Use `INSERT_INTO_SHEET_IN_MEMORY` with templates. Use `OVERWRITE_IN_SHEET_IN_MEMORY` for multi-pass writes to the same sheet.

---

## EXISTING SHEETS ACTIONS

| XML `existingSheetsActions` value | Description |
|---|---|
| `DO_NOTHING` | Default. No action before writing; write mode applies as-is. |
| `CLEAR_SHEETS` | Clear specified sheet(s) before writing. Write mode is then ignored. |
| `REPLACE_ALL_SHEETS` | Remove all sheets before writing. Equivalent to Create new file. |

---

## MAPPING — THE SAME XML FORMAT AS READER

The mapping CDATA block uses the same `<mapping>` XML structure as SpreadsheetDataReader. The key difference is `<writeHeader>`:

- **Reader:** `writeHeader` is always `false` (meaningless for reading)
- **Writer:** `writeHeader="true"` writes the field label/name into the leading cell as a column header before writing data rows

### Style A: cloverField (explicit per-field mapping)

Each headerGroup explicitly binds a Clover field to a cell. Most commonly used for writers.

```xml
<headerGroup skip="1">
    <cloverField>Order_Id</cloverField>
    <headerRanges>
        <headerRange begin="A1"/>
    </headerRanges>
</headerGroup>
<headerGroup skip="1">
    <cloverField>Order_Date</cloverField>
    <headerRanges>
        <headerRange begin="B1"/>
    </headerRanges>
</headerGroup>
```

### Style B: implicit (no mapping specified)

Leave the `mapping` attribute empty entirely. The component writes all fields in metadata order starting at A1, with header in row 1 and data from row 2. Equivalent to `writeHeader=true`, `defaultSkip=1`, map by order.

```xml
<!-- No mapping attr needed — implicit mapping applies -->
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/orders.xlsx" guiName="XLSX (Orders)" guiX="395" guiY="375" id="XLSX_ORDERS" type="SPREADSHEET_WRITER" writeMode="OVERWRITE_SHEET_IN_MEMORY"/>
```

---

## MAPPING SKELETON — ALL ELEMENTS

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>   <!-- VERTICAL or HORIZONTAL -->
        <step>1</step>                        <!-- row/column step between records; use >1 for gaps or HORIZONTAL columns-per-record -->
        <writeHeader>true</writeHeader>       <!-- true = write field label to leading cell before data -->
    </globalAttributes>
    <defaultSkip>1</defaultSkip>              <!-- rows to skip before first data row (1 = leave room for header) -->
    <headerGroups>
        <headerGroup skip="1">               <!-- local skip for this column -->
            <cloverField>FieldName</cloverField>
            <headerRanges>
                <headerRange begin="A1"/>    <!-- leading cell: where the header/data column starts -->
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
```

**`writeHeader` behavior:**
- `true` + `defaultSkip=1`: field label written to leading cell (e.g. A1), data starts one row below (A2)
- `false` + `defaultSkip=0`: data written directly into leading cell, no header row
- `true` + `defaultSkip=0`: header written but `data offset=0` means data overwrites the header — **avoid this combination**

---

## COMPLETE EXAMPLES

### Example 1 — Simplest: no mapping, implicit auto-map

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/orders.xlsx" guiName="XLSX (Orders)" guiX="395" guiY="375" id="XLSX_ORDERS" type="SPREADSHEET_WRITER" writeMode="OVERWRITE_SHEET_IN_MEMORY"/>
```

All input fields written in metadata order, header in row 1, data from row 2.

---

### Example 2 — Explicit field mapping, streaming (most common production pattern)

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/output.xlsx" guiName="OrdersWriter" guiX="400" guiY="80" id="ORDERS_WRITER" makeDirs="true" sheet="Orders" type="SPREADSHEET_WRITER" writeMode="CREATE_FILE_IN_STREAM">
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
            <cloverField>Order_Id</cloverField>
            <headerRanges><headerRange begin="A1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Order_Date</cloverField>
            <headerRanges><headerRange begin="B1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Product_Code</cloverField>
            <headerRanges><headerRange begin="C1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Unit_Price</cloverField>
            <headerRanges><headerRange begin="D1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Total_Price</cloverField>
            <headerRanges><headerRange begin="E1"/></headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

---

### Example 3 — File partitioning by key field (one file per STATE_DESCRIPTION)

Output files named `stat_Alabama.xlsx`, `stat_California.xlsx`, etc. Each file further partitioned into sheets by `ENTERPRISE_EMPLOYMENT_SIZE` field value.

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/stats/stat_#.xlsx" guiName="SpreadsheetDataWriter" guiX="1045" guiY="675" id="SPREADSHEET_WRITER0" makeDirs="true" partitionFileTag="keyNameFileTag" partitionKey="STATE_DESCRIPTION" sheet="$ENTERPRISE_EMPLOYMENT_SIZE" type="SPREADSHEET_WRITER" writeMode="CREATE_FILE_IN_STREAM">
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
            <cloverField>FIPS_COUNTY_CODE</cloverField>
            <headerRanges><headerRange begin="A1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>COUNTY_DESCRIPTION</cloverField>
            <headerRanges><headerRange begin="B1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>NUMBER_OF_FIRMS</cloverField>
            <headerRanges><headerRange begin="C1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>NUMBER_OF_ESTABLISHMENTS</cloverField>
            <headerRanges><headerRange begin="D1"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>EMPLOYMENT</cloverField>
            <headerRanges><headerRange begin="E1"/></headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Key attributes for this pattern:**
- `fileURL="${DATAOUT_DIR}/stats/stat_#.xlsx"` — `#` is replaced by key value or sequence number
- `partitionKey="STATE_DESCRIPTION"` — field that determines which file a record goes to
- `partitionFileTag="keyNameFileTag"` — use the key value (not a number) in the filename
- `sheet="$ENTERPRISE_EMPLOYMENT_SIZE"` — `$` prefix means dynamic sheet name from field value

---

### Example 4 — Sheet partitioning only (one sheet per country, single file)

```xml
<Node enabled="enabled" existingSheetsActions="CLEAR_SHEETS" fileURL="${DATAOUT_DIR}/ordersByCountry.xlsx" guiName="Orders by Country" guiX="1045" guiY="175" id="ORDERS_BY_COUNTRY" sheet="$ShipCountry" type="SPREADSHEET_WRITER" writeMode="OVERWRITE_SHEET_IN_MEMORY"/>
```

No mapping needed — implicit. `sheet="$ShipCountry"` routes each record to a sheet named after its `ShipCountry` field value. `existingSheetsActions="CLEAR_SHEETS"` ensures sheets are fresh on each run.

---

### Example 5 — Template-based writing

Copies template file to output, then inserts data rows. Template preserves header, footer, and formatting.

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/sortedByTotalTax.xlsx" guiName="SpreadsheetDataWriter" guiX="920" guiY="300" id="SPREADSHEET_WRITER1" sheet="Taxes" templateFileURL="${DATAIN_DIR}/others/10staxss_template.xlsx" type="SPREADSHEET_WRITER" writeMode="INSERT_INTO_SHEET_IN_MEMORY">
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
            <cloverField>State</cloverField>
            <headerRanges><headerRange begin="A4"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Total_taxes</cloverField>
            <headerRanges><headerRange begin="C4"/></headerRanges>
        </headerGroup>
        <headerGroup skip="1">
            <cloverField>Individual_income</cloverField>
            <headerRanges><headerRange begin="F4"/></headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Required template settings:**
- `writeMode="INSERT_INTO_SHEET_IN_MEMORY"` — inserts rows, does not overwrite template structure
- `existingSheetsActions="DO_NOTHING"` — preserve template content
- `sheet` — must name a sheet that exists in the template
- Leading cells point to the **template row** (the first data row in the template, e.g. row 4), not row 1
- `templateFileURL` — the template is **copied** to `fileURL`; the original template is never modified

---

### Example 6 — Form filling (data offset 0, no header)

Write exactly one record into fixed cells of a pre-designed form.

```xml
<Node enabled="enabled" existingSheetsActions="DO_NOTHING" fileURL="${DATAOUT_DIR}/tax_form_output.xlsx" guiName="FillTaxForm" guiX="400" guiY="80" id="FILL_FORM" sheet="Form" templateFileURL="${DATAIN_DIR}/tax_form_template.xlsx" type="SPREADSHEET_WRITER" writeMode="OVERWRITE_IN_SHEET_IN_MEMORY">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>
        <step>1</step>
        <writeHeader>false</writeHeader>
    </globalAttributes>
    <defaultSkip>0</defaultSkip>
    <headerGroups>
        <headerGroup skip="0">
            <cloverField>Taxpayer_Surname</cloverField>
            <headerRanges><headerRange begin="C5"/></headerRanges>
        </headerGroup>
        <headerGroup skip="0">
            <cloverField>Tax_identification_number</cloverField>
            <headerRanges><headerRange begin="C3"/></headerRanges>
        </headerGroup>
        <headerGroup skip="0">
            <cloverField>Year</cloverField>
            <headerRanges><headerRange begin="I3"/></headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Form filling settings:**
- `writeHeader="false"` — no column header row
- `defaultSkip=0` and `headerGroup skip="0"` — data written directly into the leading cell
- Each field mapped to its specific form cell by address
- `writeMode="OVERWRITE_IN_SHEET_IN_MEMORY"` — fills existing cells without restructuring

---

## DYNAMIC SHEET NAMING

Use `$FIELD_NAME` in the `sheet` attribute to name each sheet after a field value:

```xml
sheet="$ShipCountry"          <!-- one sheet per unique ShipCountry value -->
sheet="$Year;$Month"          <!-- one sheet per Year+Month combination -->
```

The `$` prefix is the syntax — no braces, no quotes. This is how sheet partitioning works. The component creates a new sheet the first time it encounters each unique value.

---

## FILE PARTITIONING

For partitioning records into multiple **files** (not just sheets):

```xml
fileURL="${DATAOUT_DIR}/output_#.xlsx"   <!-- # replaced by key value or sequence number -->
partitionKey="STATE_DESCRIPTION"          <!-- field driving the split -->
partitionFileTag="keyNameFileTag"         <!-- use key value in filename (not a number) -->
```

With `partitionFileTag="keyNameFileTag"`, `#` in the filename is replaced by the actual key value (e.g. `output_Alabama.xlsx`).
Without it (or `numberFileTag`), `#` is replaced by a sequence number.

**Note:** All output files are open simultaneously by default. For thousands of partition files, sort input by the partition key first and add `sortedInput="true"` to prevent running out of file handles.

---

## CELL FORMATTING

### Format in metadata (per-column)

Set the `format` attribute on the metadata `<Field>` element with `excel:` prefix:

```xml
<Field format="excel:#,##0.00" name="Amount" type="decimal"/>
<Field format="excel:DD/MM/YY" name="OrderDate" type="date"/>
<Field format="excel:@" name="Code" type="string"/>    <!-- @ = text format -->
```

The `excel:` prefix is required — formats without it are ignored by the writer.

### Format in data (per-cell, via field)

Map a second string field as the format source for a cell. The format field must NOT have the `excel:` prefix — it's passed as raw Excel format string.

This is configured in the visual mapping editor (**Field with format** property on the leading cell) and serializes into the mapping XML. Example data: `"#,##0.00"` in the format field, `100.5` in the value field.

### Priority

1. If **Field with format** is mapped and the field value is non-empty → use that value
2. Else if the metadata `Format` has `excel:` prefix → use that
3. Else → `General` format

---

## FORMULAS

To write a formula, the input field contains the formula string (e.g. `=SUM(A2:A10)`). In the visual editor, set **Is Formula = Yes** on the leading cell.

**Streaming mode caveat:** formulas are pre-evaluated only if all referenced cells are within the streaming window (last 10 rows by default). Outside that window, a placeholder (0 or empty) is written; Excel recalculates on first open.

Set `streamingWindowSize` attribute to increase the window if needed.

---

## HYPERLINKS

Map two fields to the same cell: one for link text, one for the URL/address. In the visual editor, set **Hyperlink type** and **Field with hyperlink address** on the leading cell.

**Hyperlink address formats by type:**

| Type | Example address |
|---|---|
| URL | `http://www.example.com` |
| Email | `mailto:user@company.com` |
| File | `report.txt` or `C:/path/to/file.txt` |
| Document | `K2` or `'my sheet'!K2` |

---

## MULTI-PASS WRITING TO ONE SHEET

Write complex layouts by chaining multiple writers to the same file/sheet in different graph phases:

- Put each writer in a **different phase** — writers to the same file in the same phase cause a write conflict error
- Use `OVERWRITE_IN_SHEET_IN_MEMORY` for all passes after the first
- First pass typically uses `CREATE_FILE_IN_MEMORY` or a template
- Each pass writes to different cell ranges

---

## COMPONENT ATTRIBUTES — COMPLETE REFERENCE

| Attribute (XML) | Description | Default |
|---|---|---|
| `fileURL` | Output file path. `#` replaced by partition key or number. | required |
| `sheet` | Sheet name, 0-based index, `$FIELD` for dynamic, `;`-separated for multiple | auto-named new sheet |
| `writeMode` | Write strategy — see Write Modes table | `OVERWRITE_SHEET_IN_MEMORY` |
| `existingSheetsActions` | Action if sheet exists: `DO_NOTHING`, `CLEAR_SHEETS`, `REPLACE_ALL_SHEETS` | `DO_NOTHING` |
| `templateFileURL` | Template file to copy to output before writing | — |
| `makeDirs` | Auto-create missing directories | `false` |
| `partitionKey` | Field name for file partitioning | — |
| `partitionFileTag` | `keyNameFileTag` or `numberFileTag` | `numberFileTag` |
| `sortedInput` | Input sorted by partition key (enables single-file-at-a-time mode) | `false` |
| `skipRecords` | Records to skip before writing | 0 |
| `numRecords` | Max total records to write | unlimited |
| `recordsPerFile` | Max records per output file | unlimited |
| `formatterType` | `AUTO`, `XLS`, `XLSX` — must set explicitly when writing to dictionary | `AUTO` |
| `createEmptyFiles` | Create output file even when no input records | `true` |
| `streamingWindowSize` | Rows available for formula evaluation in streaming mode | 10 |
| `cacheSize` | Cache size for INSERT_INTO_SHEET_IN_MEMORY (affects performance) | 1000 |
| `evaluateFormulaCell` | Pre-evaluate formula cells when writing | `true` |

---

## EDGE DECLARATIONS

```xml
<Edge fromNode="UPSTREAM:0" id="Edge0" inPort="Port 0 (input)" metadata="MetaMyRecord" outPort="Port 0 (out)" toNode="MY_WRITER:0"/>
```

Note: writer input port label is `Port 0 (input)`, not `Port 0 (in)`.

---

## LIMITATIONS

| Limitation | Detail |
|---|---|
| No error port | Writer has no port 1 — errors are fatal; no per-record error routing |
| No encryption output | Can read encrypted files but cannot write them |
| XLS row limit | Max 65,535 rows and 256 columns per sheet |
| XLSX sheet limit | 16,384 columns; row count unlimited (Excel only displays first 1,048,576) |
| Sheet name length | Excel silently truncates names to 31 chars — unique parts at the end may collide |
| Lists and maps | Cannot be written; lists of string/byte/cbyte are converted to string |
| `excel:raw` format | Ignored by writer — treated as empty format |
| XLTX templates | Not supported for XLSX output — use XLSX as template instead |
| Streaming + formulas | Only pre-evaluated if referenced cells are within streaming window |
| Linux fontconfig | Requires fontconfig library; add `-Djava.awt.headless=true` if still failing |

---

## GENERATION RULES FOR LLM

Always include:
- `type="SPREADSHEET_WRITER"`
- `fileURL`
- `writeMode` (be explicit — default `OVERWRITE_SHEET_IN_MEMORY` is rarely what you want for new files)
- `existingSheetsActions` (include even if `DO_NOTHING` — makes intent clear)

Mapping generation checklist:
- New file, no template, fast → `writeMode="CREATE_FILE_IN_STREAM"`, `writeHeader="true"`, `defaultSkip=1`
- Fill a template → `writeMode="INSERT_INTO_SHEET_IN_MEMORY"`, `existingSheetsActions="DO_NOTHING"`, `templateFileURL=...`, `writeHeader=false` or `true` depending on template, `defaultSkip=0` (data goes directly to template row)
- Form filling → `writeMode="OVERWRITE_IN_SHEET_IN_MEMORY"`, `writeHeader="false"`, `defaultSkip=0`, each field mapped to its exact cell
- Partition into sheets by field → `sheet="$FIELD_NAME"`, `existingSheetsActions="CLEAR_SHEETS"`
- Partition into files by field → `fileURL="path/name_#.xlsx"`, `partitionKey="FIELD"`, `partitionFileTag="keyNameFileTag"`
- Implicit mapping (all fields, default order) → omit `mapping` attribute entirely
- Explicit mapping → one `<headerGroup>` per field with `<cloverField>` and `<headerRange>`

Do NOT:
- Use `writeHeader="true"` with `defaultSkip=0` — header and data would overwrite each other
- Set `existingSheetsActions="REPLACE_ALL_SHEETS"` without intending to wipe the entire file
- Put two writers to the same file in the same phase — use separate phases
- Use XLTX as template for XLSX output — use XLSX instead
- Set `formatterType="AUTO"` when writing to a dictionary — must be explicit XLS or XLSX

---

## COMMON MISTAKES

| Mistake | Correct form |
|---|---|
| `writeHeader="true"` + `defaultSkip=0` | Use `defaultSkip=1` when writing headers |
| `writeMode` not set — defaults to in-memory overwrite | Explicitly set `CREATE_FILE_IN_STREAM` for new large files |
| Sheet name from field missing `$` prefix | `sheet="$CountryField"` not `sheet="CountryField"` |
| Partitioning file without `#` in filename | `fileURL` must contain `#` as the partition placeholder |
| Template write with `CREATE_FILE_IN_STREAM` | Templates require `INSERT_INTO_SHEET_IN_MEMORY` |
| Two writers to same file in same phase | Split into different phases |
| `excel:` prefix in data field format value | Only use `excel:` in metadata Format attribute; pass raw format string in data |
| Format without `excel:` prefix in metadata | Must prefix metadata format with `excel:` or it is ignored |
| `formatterType="AUTO"` writing to dictionary | Must set `formatterType="XLS"` or `"XLSX"` explicitly |
