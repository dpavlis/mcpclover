# CloverDX DB_OUTPUT_TABLE — LLM Reference

## What it does
Writes records into a database table via JDBC. Supports INSERT, UPDATE, DELETE, and multi-statement-per-record patterns.
Also known as **DatabaseWriter** (renamed from DBOutputTable in 5.3.0 — component type string `DB_OUTPUT_TABLE` unchanged).

Supported databases: PostgreSQL, MySQL, Oracle, SQL Server, SQLite, Snowflake, Redshift, DB2, Vertica, Sybase, and any JDBC-compliant database.

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | ✓ | Records to write to DB | Any |
| Output 0 | optional | Rejected records (failed DB operations) | Input 0 + ErrCode + ErrText |
| Output 1 | optional | Auto-generated/returned values from DB | Must match `returning` clause fields |

**Output port 0 metadata:** Propagated from input port 0 with two optional extra fields using autofilling functions `ErrCode` (integer) and `ErrText` (string). Add these fields to the metadata and set their autofilling function — they are populated automatically.

**Output port 1:** Not available in batch mode. Fields must be explicitly mapped in the `returning` clause.

## Three Configuration Modes

`dbTable`, `sqlQuery`, and `url` are mutually exclusive — exactly one must be set.
**Priority if multiple are set:** `url` > `sqlQuery` > `dbTable`.

### Mode 1: dbTable (auto-mapping, simplest)

Set the table name. CloverDX auto-generates the INSERT mapping metadata fields to DB columns.

```xml
<Node batchMode="true" batchSize="1000" commit="2000"
      dbConnection="JDBC0"
      dbTable="payments"
      id="DATABASE_WRITER" type="DB_OUTPUT_TABLE"/>
```

Default mapping behaviour when no `fieldMap`/`cloverFields`/`dbFields` are set:
fields are inserted by **position** — first metadata field → first DB column, etc.

To map by name or handle mismatches, use `fieldMap`:
```xml
fieldMap="$cloverFieldA:=db_col_a;$cloverFieldB:=db_col_b"
```
Or use `cloverFields` + `dbFields` for positional pair mapping, or `cloverFields` alone for positional DB column mapping.

### Mode 2: sqlQuery (full SQL control)

Write any valid SQL with `$fieldName` substitution. Most common for production use when field names differ from column names, or when UPDATE/DELETE/multi-table inserts are needed.

```xml
<Node batchMode="true" batchSize="1000" commit="2000"
      dbConnection="JDBC0"
      id="DATABASE_WRITER" type="DB_OUTPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[INSERT INTO "customers" ("id", "full_name", "email")
VALUES ($id, $fullName, $email)]]></attr>
</Node>
```

**`$fieldName` syntax:** `$` followed by the CloverDX metadata field name — substituted with the field value at runtime. Use for VALUES and WHERE clauses. Column names and table names are plain SQL (quoted with `"` for case-sensitivity).

**`?` placeholder alternative:** Use `?` instead of `$fieldName` and specify mapping via `fieldMap`, `cloverFields`, or `dbFields` attributes. Less common than `$fieldName` form.

### Mode 3: url (external SQL file)

```xml
<Node dbConnection="JDBC0" url="${PROJECT}/sql/insert_products.sql"
      id="DATABASE_WRITER" type="DB_OUTPUT_TABLE"/>
```
Recommended when SQL is long or shared across graphs. Always set `charset` (e.g. `charset="UTF-8"`) with external files.

## Key Attributes

| Attribute (XML) | Default | Description |
|---|---|---|
| `dbConnection` | required | ID of the JDBC connection defined in `<Global>` |
| `dbTable` | — | Table name (auto-generates INSERT) |
| `sqlQuery` [attr-cdata] | — | Inline SQL with `$fieldName` substitution |
| `url` | — | Path to external .sql file |
| `fieldMap` [attr-cdata] | — | `$CloverField:=DBColumn;...` mapping for `dbTable` or `?` mode |
| `cloverFields` | — | Semicolon-separated Clover field names (positional mapping) |
| `dbFields` | — | Semicolon-separated DB column names (paired with `cloverFields`) |
| `batchMode` | `false` | Enable batch mode for performance |
| `batchSize` | `25` | Records per batch (tune upward for large loads) |
| `commit` | `100` | Records between commits. `MAX_INT` = defer to connection close. Ignored when `atomicSQL=true`. |
| `maxErrors` | `0` | Max allowed errors before abort. `-1` = allow all errors. |
| `errorAction` | `COMMIT` | On error threshold: `COMMIT` (default) or `ROLLBACK` |
| `atomicSQL` | `false` | When `true`: all sub-queries for one record executed atomically |
| `charset` | system | Encoding — set explicitly especially for external SQL files |

## sqlQuery Syntax Reference

### INSERT (most common)
```sql
INSERT INTO "schema"."table" ("col1", "col2", "col3")
VALUES ($fieldA, $fieldB, $fieldC)
```
- Column list and table name: plain SQL, quoted with `"` for case-sensitivity
- VALUES: `$fieldName` references metadata field values
- Can mix with SQL constants and functions: `VALUES ($fieldA, now(), 0)`

### INSERT into parameterized table (graph parameter in SQL)
```sql
INSERT INTO "${TARGET_DB_TABLE}" ("col1", "col2")
VALUES ($Field1, $Field2)
```
`${PARAM}` syntax in SQL resolves the graph parameter at runtime.

### UPDATE
```sql
UPDATE "${TARGET_DB_TABLE}"
SET "col1" = $newValue, "col2" = 0
WHERE "_id" = $_id
```

### DELETE
```sql
DELETE FROM "mytable"
WHERE "id" = $id AND "status" = $status
```

### Multi-statement per record (two tables, one record)
Separate statements with `;`:
```sql
INSERT INTO "audit_log" ("id", "amount", "ts")
VALUES ($id, $amount, now());
INSERT INTO "orders" ("id", "amount")
VALUES ($id, $amount)
```
Use with `atomicSQL="true"` to make both statements atomic per record.

### INSERT with returning clause (output port 1)
```sql
-- MySQL / SQL Server style (auto_generated virtual field)
INSERT INTO "products" ("name", "price")
VALUES ($name, $price)
returning $generatedId := auto_generated

-- PostgreSQL / Oracle style (return DB column values)
INSERT INTO "orders" ("name", "price")
VALUES ($name, $price)
returning $newId := id, $createdAt := created_at
```
Output port 1 metadata must contain `generatedId` / `newId` / `createdAt` fields.
**Not available in batch mode.**

## Batch Mode and Performance

```xml
<Node batchMode="true" batchSize="1000" commit="2000"
      dbConnection="JDBC0" dbTable="orders"
      id="WRITER" type="DB_OUTPUT_TABLE"/>
```

- `batchMode="true"` groups multiple operations into one DB round-trip — significantly faster for bulk loads
- `batchSize`: tune based on row size and DB limits; typical production values: 500–5000
- `commit`: how often to commit. Lower = more checkpoints (safer); higher = fewer round-trips (faster)
- `batchSize` and `commit` are independent — e.g. batches of 1000 with commit every 5000 records

**Note:** Some databases send successfully inserted records to the rejected port when in batch mode — this is a known DB driver behavior, not a CloverDX bug.

## Error Handling

### Default behavior (maxErrors=0)
Fails on the very first DB error. Nothing written is rolled back (already-committed records stay committed).

### Allow errors, capture rejected records
```xml
<Node dbConnection="JDBC0" dbTable="products" maxErrors="-1"
      errorAction="ROLLBACK" id="WRITER" type="DB_OUTPUT_TABLE"/>
<!-- Connect output port 0 to receive rejected records -->
```
With `maxErrors="-1"`, processing continues on all errors. Rejected records flow to port 0 with `ErrCode` and `ErrText` fields populated.

### errorAction semantics
| `errorAction` | When error threshold exceeded |
|---|---|
| `COMMIT` (default) | Commits already-processed records, then stops. Behavior varies by DB. |
| `ROLLBACK` | Rolls back the last non-committed batch in all DBs consistently. Already-committed records cannot be rolled back. |

**Production recommendation:** Always use `errorAction="ROLLBACK"` — the DWHExample sandbox uses ROLLBACK consistently on all DB writes.

### atomicSQL
When `sqlQuery` contains multiple `;`-separated statements for one record, `atomicSQL="true"` ensures all succeed or all fail together. Commit interval is ignored — commits after each record.

## Output Port 0 Metadata — ErrCode / ErrText

To capture error details, add these fields to the metadata on output port 0 and set their autofilling:

```xml
<Metadata id="MetaProducts">
    <Record name="products" type="delimited">
        <Field name="id"       type="integer"/>
        <Field name="name"     type="string"/>
        <Field name="price"    type="decimal"/>
        <!-- Error capture fields — names can be anything, autofilling is the key -->
        <Field auto_filling="ErrCode" name="dbErrorCode" type="integer"/>
        <Field auto_filling="ErrText" name="dbErrorText" type="string"/>
    </Record>
</Metadata>
```

## Real Sandbox Examples

### QuickStartGuide — dbTable mode (auto-mapping, field names match columns)
```xml
<Node batchMode="true" batchSize="1000" commit="2000"
      dbConnection="JDBC0"
      dbTable="payments"
      guiName="DatabaseWriter"
      id="DATABASE_WRITER" type="DB_OUTPUT_TABLE"/>
```
No SQL needed. CloverDX auto-generates INSERT mapping fields to columns by position.

### QuickStartGuide — sqlQuery INSERT (field names differ from column names)
```xml
<Node batchMode="true" batchSize="1000" commit="2000"
      dbConnection="JDBC0"
      guiName="store in db"
      id="DATABASE_WRITER" type="DB_OUTPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[INSERT INTO "customers" ("id", "full_name", "street_address", "city", "postal_code", "state", "country", "email", "phone", "account_created", "is_active")
VALUES ($id, $fullName, $streetAddress, $city, $postalCode, $state, $country, $email, $phone, $accountCreated, $isActive)]]></attr>
</Node>
```
CloverDX fields (`$fullName`, `$streetAddress`) map to DB columns (`full_name`, `street_address`) explicitly via the VALUES clause — no `fieldMap` needed.

### DWHExample — parameterized bulk INSERT (SCD2 dimension writer)
```xml
<Node batchMode="${TARGET_DB_BATCH_MODE}" batchSize="${DB_BATCH_SIZE}"
      charset="UTF-8" commit="${DB_COMMIT_SIZE}"
      dbConnection="JDBC0"
      errorAction="ROLLBACK"
      guiName="Insert records"
      id="INSERT_RECORDS" type="DB_OUTPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[INSERT INTO "${TARGET_DB_TABLE}" ("product_code","product_name","unit_price","supplier","profit_margin","_valid_from","_valid_to","_is_active","_natural_key_id","_natural_key_hash","_checksum","_created_at","_created_by","_updated_by")
values ($Product_Code,$Product_Name,$Unit_Price,$Supplier,$Profit_Margin,$_valid_from,$_valid_to,$_is_active,$_natural_key_id,$_natural_key_hash,$_checksum,$_created_at,$_created_by,$_updated_by)]]></attr>
</Node>
```
Key patterns: batch/commit settings parameterized from graph params; `errorAction="ROLLBACK"`; table name via `"${TARGET_DB_TABLE}"`.

### DWHExample — UPDATE for SCD2 expiry
```xml
<Node batchMode="${TARGET_DB_BATCH_MODE}" batchSize="${DB_BATCH_SIZE}"
      charset="UTF-8" commit="${DB_COMMIT_SIZE}"
      dbConnection="JDBC0"
      errorAction="ROLLBACK"
      guiName="Update records"
      id="UPDATE_RECORDS" type="DB_OUTPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[update "${TARGET_DB_TABLE}"
set "_valid_to"=$_valid_from,"_is_active"=0
where "_id"=$_id]]></attr>
</Node>
```
UPDATE uses `$fieldName` in both SET and WHERE clauses.

### DWHExample — single-column temp table INSERT
```xml
<Node batchMode="${TARGET_DB_BATCH_MODE}" batchSize="${DB_BATCH_SIZE}"
      charset="UTF-8" commit="${DB_COMMIT_SIZE}"
      dbConnection="JDBC0"
      errorAction="ROLLBACK"
      guiName="Temporary table"
      id="TEMPORARY_TABLE" type="DB_OUTPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[insert into "${TEMPORARY_TABLE_NAME}" ("_natural_key_hash") values ($_natural_key_hash)]]></attr>
</Node>
```

## Edge Port Names
- Input 0: `Port 0 (in)`
- Output 0: `Port 0 (rejected)`
- Output 1: `Port 1 (autogenerated)`

## Connection Declaration
Connection must be declared in `<Global>` referencing a `.cfg` file:
```xml
<Connection dbDriver="..." dbURL="..." id="JDBC0" name="MyDB" type="JDBC"
            fileURL="${CONN_DIR}/MyConnection.cfg"/>
```
Use `list_linked_assets(asset_type='connection')` to discover existing connections in the sandbox.

## Decision Guide

| Need | Mode |
|---|---|
| Field names match DB column names exactly | `dbTable` (auto-mapping) |
| Field names differ from column names | `sqlQuery` with `$field:=column` positional mapping in VALUES |
| UPDATE or DELETE | `sqlQuery` |
| Two tables per record | `sqlQuery` with `;`-separated statements + `atomicSQL="true"` |
| Shared SQL across multiple graphs | `url` pointing to external `.sql` file |
| Capture rejected records | Connect port 0, set `maxErrors="-1"`, add `ErrCode`/`ErrText` autofilling |
| Capture auto-generated IDs | Connect port 1, use `returning` clause in SQL (not in batch mode) |

## Mistakes

| Wrong | Correct |
|---|---|
| `$fieldName` used in column name list | Only use `$fieldName` in VALUES, SET, and WHERE clauses — column names are plain SQL |
| `errorAction="ROLLBACK"` without `maxErrors` > 0 | `errorAction` only applies when error threshold is exceeded — set `maxErrors` appropriately |
| `returning` clause in batch mode | Not supported — returning requires `batchMode="false"` |
| `atomicSQL="true"` with single-statement SQL | No effect for single statements; only meaningful for multi-statement (`;`-separated) queries |
| Default `batchSize="25"` for large loads | Increase to 500–5000; default is far too small for production bulk inserts |
| Default `errorAction="COMMIT"` in production | Use `errorAction="ROLLBACK"` for consistent behaviour across all JDBC drivers |
| `dbTable` with Clover field names ≠ DB column names | Either use `sqlQuery` with explicit VALUES mapping, or add `fieldMap="$cloverF:=dbCol;..."` |
| Unquoted table or column names with mixed case | Quote names with `"` in SQL to preserve case (e.g. `"MyTable"`, `"_valid_from"`) |
| `url` without `charset` | Always set `charset="UTF-8"` when using external SQL file |
| Writing list or map fields | Not supported — DatabaseWriter cannot serialize list/map types directly |
