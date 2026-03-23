# CloverDX SPREADSHEET_READER — LLM Reference (7.3.x)

## SKELETON

```xml
<Node dataPolicy="controlled" enabled="enabled" fileURL="${DATAIN_DIR}/input.xlsx"
      id="SPREADSHEET_READER0" sheet="Sheet1" type="SPREADSHEET_READER">
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

- Reads XLS (Excel 97/2003 BIFF8) and XLSX (Excel 2007+)
- Input port 0 optional (byte/cbyte field containing file contents)
- Output port 0 `Port 0 (output)` — valid records; port 1 `Port 1 (output)` — errors (optional)
- Omit `<attr name="mapping">` entirely for auto mode (first row = headers, mapped by name)

## NODE ATTRIBUTES

| Attr | Default | Notes |
|---|---|---|
| `fileURL` | required | Path, `${DATAIN_DIR}/file.xlsx`. Glob: `O*.xls`. Port: `port:$0.filePath` |
| `sheet` | first sheet | Name, 0-based index, `*` (all), comma-separated list, wildcards `Q?_*` |
| `attitude` | `IN_MEMORY` | `IN_MEMORY` or `STREAM`. IN_MEMORY required for formula reading. |
| `dataPolicy` | strict | **Deprecated** — connect port 1 instead. `strict`/`controlled`/`lenient` |
| `numRecords` | — | Max total records across all sources |
| `skipRecords` | — | Records to skip globally |
| `maxRecordsPerSource` | — | Max records per file (use `1` for form/template extraction) |
| `skipRecordsPerSource` | — | Records to skip per file |
| `maxRecordsPerSpreadsheet` | — | Max records per sheet |
| `skipRecordsPerSpreadsheet` | — | Records to skip per sheet |
| `maxErrorCount` | unlimited | Max errors before failure in controlled mode |
| `password` | — | Decryption password for protected files |
| `incrementalFile` | — | Path to incremental state file |
| `incrementalKey` | — | Field name for incremental tracking |

**Error handling:** connecting an edge to port 1 enables controlled behavior automatically. `dataPolicy` attribute is deprecated — prefer port 1 edge.

## MAPPING XML STRUCTURE

Goes inside `<attr name="mapping"><![CDATA[ ... ]]></attr>`. Always include the `<?xml ... ?>` declaration.

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes>
        <orientation>VERTICAL</orientation>   <!-- VERTICAL (rows) or HORIZONTAL (columns) -->
        <step>1</step>                         <!-- VERTICAL: always 1. HORIZONTAL: columns per record -->
        <writeHeader>true</writeHeader>        <!-- always true for reader -->
    </globalAttributes>
    <defaultSkip>1</defaultSkip>              <!-- rows/cols between header cell and first data cell -->
    <headerGroups>
        <!-- one or more headerGroup elements -->
    </headerGroups>
</mapping>
```

## HEADERGROUP — TWO STRATEGIES

`autoMappingType` and `cloverField` are **mutually exclusive** within one `headerGroup`.

**Strategy A — autoMappingType** (batch, all cells share same mapping strategy):
```xml
<headerGroup skip="1">
    <autoMappingType>NAME</autoMappingType>   <!-- NAME: match by field name | ORDER: map by position -->
    <headerRanges>
        <headerRange begin="A1"/>
        <headerRange begin="B1"/>
        <headerRange begin="C1"/>
    </headerRanges>
</headerGroup>
```

**Strategy B — cloverField** (explicit, one group per field; use for non-contiguous or excluded columns):
```xml
<headerGroup skip="1">
    <cloverField>Order_Id</cloverField>
    <headerRanges><headerRange begin="A1"/></headerRanges>
</headerGroup>
<headerGroup skip="1">
    <cloverField>Customer_Name</cloverField>
    <headerRanges><headerRange begin="C1"/></headerRanges>   <!-- B1 skipped -->
</headerGroup>
```

- `skip` on `headerGroup` — local override of `defaultSkip` for this group
- `headerRange begin` — A1-notation cell address. VERTICAL: reading advances down. HORIZONTAL: reading advances right.

## SKIP / OFFSET

`defaultSkip` = global default; `skip` on `headerGroup` = per-group override. Set both to the same value in typical use.

| Header row | Data starts | defaultSkip / skip |
|---|---|---|
| Row 1 | Row 2 | `1` |
| Row 1 | Row 4 | `3` |
| Row 5 | Row 8 | `3` (with `begin="A5"`) |

## EXAMPLES

**Standard table, header row 1, name mapping:**
```xml
<Node fileURL="${DATAIN_DIR}/orders.xlsx" id="READER0" sheet="Sheet0" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes><orientation>VERTICAL</orientation><step>1</step><writeHeader>true</writeHeader></globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A1"/><headerRange begin="B1"/><headerRange begin="C1"/>
                <headerRange begin="D1"/><headerRange begin="E1"/><headerRange begin="F1"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Header at row 5, data starts row 8 (defaultSkip=3):**
```xml
<Node fileURL="${DATAIN_DIR}/county_totals.xls" id="READER0" sheet="County" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes><orientation>VERTICAL</orientation><step>1</step><writeHeader>true</writeHeader></globalAttributes>
    <defaultSkip>3</defaultSkip>
    <headerGroups>
        <headerGroup skip="3">
            <autoMappingType>NAME</autoMappingType>
            <headerRanges>
                <headerRange begin="A5"/><headerRange begin="B5"/><headerRange begin="C5"/>
            </headerRanges>
        </headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**Non-contiguous columns with cloverField (B, C, E — skipping A and D):**
```xml
<headerGroups>
    <headerGroup skip="1"><cloverField>COUNTY</cloverField><headerRanges><headerRange begin="B1"/></headerRanges></headerGroup>
    <headerGroup skip="1"><cloverField>FIRMS</cloverField><headerRanges><headerRange begin="C1"/></headerRanges></headerGroup>
    <headerGroup skip="1"><cloverField>EMPLOYMENT</cloverField><headerRanges><headerRange begin="E1"/></headerRanges></headerGroup>
</headerGroups>
```

**Wildcard files + all sheets, auto mode:**
```xml
<Node fileURL="${DATAIN_DIR}/others/O*.xls" id="READER0" sheet="*" type="SPREADSHEET_READER"/>
```

**Horizontal layout, step=2 (value + note column pairs):**
```xml
<Node attitude="IN_MEMORY" fileURL="${DATAIN_DIR}/stats.xls" id="READER0" sheet="Sheet1" type="SPREADSHEET_READER">
    <attr name="mapping"><![CDATA[<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<mapping>
    <globalAttributes><orientation>HORIZONTAL</orientation><step>2</step><writeHeader>true</writeHeader></globalAttributes>
    <defaultSkip>1</defaultSkip>
    <headerGroups>
        <headerGroup skip="1"><cloverField>Total_taxes</cloverField><headerRanges><headerRange begin="B9"/></headerRanges></headerGroup>
        <headerGroup skip="1"><cloverField>Total_taxes_note</cloverField><headerRanges><headerRange begin="C9"/></headerRanges></headerGroup>
    </headerGroups>
</mapping>
]]></attr>
</Node>
```

**One record per file (form extraction):**
```xml
<Node fileURL="${DATAIN_DIR}/forms/*.xlsx" id="READER0" maxRecordsPerSource="1" sheet="Tax data" type="SPREADSHEET_READER">
```

## AUTOFILLING (sheet name / source info into metadata fields)

Set `auto_filling` on the metadata field — no mapping change needed:

```xml
<Field auto_filling="sheet_name"        name="SheetName"  type="string"/>
<Field auto_filling="source_name"       name="SourceFile" type="string"/>
<Field auto_filling="source_timestamp"  name="FileDate"   type="date"/>
<Field auto_filling="source_size"       name="FileSize"   type="long"/>
```

## ERROR PORT METADATA

When port 1 is connected, each field parse error emits one record:

| Field | Type |
|---|---|
| `recordID` | `integer` — 1-based failed record index |
| `file` | `string` — source filename |
| `sheet` | `string` — sheet name |
| `fieldIndex` | `integer` — 0-based target field index |
| `fieldName` | `string` |
| `cellCoords` | `string` — e.g. `D7` |
| `cellValue` | `string` — raw value that caused error |
| `cellType` | `string` — e.g. `String`, `Numeric` |
| `cellFormat` | `string` — e.g. `#,##0` |
| `message` | `string` |

One error record per bad field. Group by `recordID` to aggregate per source row.

## SPECIAL FEATURES

| Feature | Requirement |
|---|---|
| Read formula string (e.g. `=SUM(A1:A5)`) | `attitude="IN_MEMORY"`, target field type `string` |
| Read Excel format string (e.g. `#,##0`) | None; target field type `string` |
| Read hyperlink URL | None; single-cell only; target field type `string` |
| Raw numeric value (full precision) | Set field format `excel:raw` in metadata |
| Dates | Use `date` typed metadata field; set format to match Excel format e.g. `excel:MM/DD/YY` |

## DECISION GUIDE

| Scenario | Use |
|---|---|
| Standard table, header row 1, names match metadata | `autoMappingType>NAME`, `defaultSkip=1`, `skip="1"` |
| No headers or column order matters | `autoMappingType>ORDER` |
| Header not at row 1 (e.g. row 5) | `begin="A5"`, `defaultSkip=3`, `skip="3"` |
| Non-contiguous columns or skip specific columns | `cloverField` per headerGroup |
| Simple case, names match, no config needed | Omit `<attr name="mapping">` entirely |
| Horizontal layout (fields in rows, records in columns) | `orientation>HORIZONTAL`, `step` = columns per record |
| Formula values needed | `attitude="IN_MEMORY"` |
| One record per file | `maxRecordsPerSource="1"` |
| Sheet name into a field | `auto_filling="sheet_name"` on metadata field |

## MISTAKES

| Wrong | Correct |
|---|---|
| `step=1` in HORIZONTAL mode for paired columns | `step=2` (columns per record) |
| `defaultSkip` and `headerGroup skip` differ | Both must match in typical single-offset layouts |
| `headerRange begin="A1"` when header is at row 5 | `begin="A5"` |
| `attitude` omitted when reading formulas | `attitude="IN_MEMORY"` required |
| Reading dates into `string` fields | Use `date` typed field with matching format |
| `autoMappingType` and `cloverField` in same headerGroup | Mutually exclusive |
| `autoMappingType>NAME` when spreadsheet headers don't match field names | Use `ORDER` or explicit `cloverField` |
| `sheet="*"` with heterogeneous sheet schemas | All sheets must share the same schema |
| Using deprecated `dataPolicy` attribute | Connect edge to port 1 instead |
