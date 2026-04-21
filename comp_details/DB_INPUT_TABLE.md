# CloverDX DB_INPUT_TABLE — LLM Reference

## What it does
Reads records from a database via JDBC using a SQL query. Streams results to one or more output ports.
Also known as **DatabaseReader** (renamed from DBInputTable in 5.3.0 — component type string `DB_INPUT_TABLE` unchanged).

Supports all JDBC-compliant databases: PostgreSQL, MySQL, Oracle, SQL Server, SQLite, Snowflake, Redshift, DB2, Vertica, Sybase, and others.

No transformation — records are mapped from DB result set to output metadata either positionally or by explicit field-name mapping in the SQL.

## Ports

| Port | Required | Description | Metadata |
|---|---|---|---|
| Input 0 | optional | Query string to execute (read from upstream record field via `queryURL="port:$0.fieldName:discrete"`) | One field (`string` or `byte`) |
| Output 0 | ✓ | Query result records | Any |
| Output 1-N | optional | Same records also sent here (fan-out) | Same as output 0 |

**Fan-out:** Records are sent to **all** connected output ports simultaneously — not partitioned. Connect multiple output ports to duplicate the stream to different destinations in the same phase.

No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Default | Description |
|---|---|---|
| `dbConnection` | required | ID of the JDBC connection defined in `<Global>` |
| `sqlQuery` [attr-cdata] | one of | Inline SQL SELECT statement |
| `queryURL` | one of | Path to external `.sql` file, or `port:$0.fieldName:discrete` to read from input port. If both set, `queryURL` takes precedence. |
| `charset` | system | Encoding — set explicitly, especially for double-quoted identifiers or external files |
| `fetchSize` | `20` | Records fetched from DB per round-trip. Tune upward for large reads. |
| `dataPolicy` | `strict` | `strict` (fail on error) / `controlled` (log errors, continue — no reject port) / `lenient` |
| `printStatement` | `false` | Log the SQL statement to the execution log — useful for debugging parameterized queries |
| `autoCommit` | `true` | Set `false` when multiple operations share one transaction |
| `incrementalFile` | — | Path to file storing incremental read state |
| `incrementalKey` | — | Key variable tracking last-read position (e.g. `key01="LAST(id)!5"`) |

## sqlQuery Syntax

### Simple SELECT — positional mapping
The most common form. Output metadata fields are mapped from result set columns by position (left to right).

```sql
SELECT col1, col2, col3
FROM "schema"."table"
WHERE "status" = 'active'
```

Output metadata field 0 ← col1, field 1 ← col2, field 2 ← col3.

### SELECT with WHERE filter
```sql
SELECT "_id", "_natural_key_id", "_natural_key_hash"
FROM "product_dim"
WHERE "_is_active" = 1
```

### Parameterized table name
Use `"${GRAPH_PARAM}"` inside the SQL for dynamic table names:
```sql
SELECT "d"."_id", "d"."_natural_key_hash", "d"."_checksum"
FROM "${TARGET_DB_TABLE}" AS d
JOIN "${TEMPORARY_TABLE_NAME}" AS t ON "d"."_natural_key_hash" = "t"."_natural_key_hash"
WHERE "d"."_is_active" = 1
```

### Multi-table JOIN (explicit JOIN syntax)
```sql
SELECT "d"."_id", "d"."_natural_key_id", "d"."_natural_key_hash", "d"."_checksum"
FROM "${TARGET_DB_TABLE}" AS d
JOIN "${TEMPORARY_TABLE_NAME}" AS t ON "d"."_natural_key_hash" = "t"."_natural_key_hash"
WHERE "d"."_is_active" = 1
```

### Multi-table JOIN (WHERE-clause syntax)
```sql
SELECT * FROM "orders", "order_details"
WHERE "orders"."order_id" = "order_details"."order_id"
${LIMIT_CLAUSE}
```

### Aggregate query with GROUP BY
```sql
SELECT "orders"."customer_id",
       COUNT("order_details"."product_id") AS num_products,
       SUM("order_details"."unit_price" * "order_details"."quantity") AS order_total_value
FROM "orders", "order_details"
WHERE "orders"."order_id" = "order_details"."order_id"
GROUP BY "orders"."customer_id", "orders"."order_id"
${LIMIT_CLAUSE}
```

### Correlated subquery per row
```sql
SELECT empl."employee_id", empl."last_name", empl."first_name",
       (SELECT SUM(od."unit_price" * od."quantity")
        FROM "orders" o, "order_details" od
        WHERE o."order_id" = od."order_id"
          AND o."employee_id" = empl."employee_id") AS total_revenue
FROM "public"."employees" empl
```

### Explicit field-name mapping (`$cloverField:=dbColumn`)
Use when output metadata field names differ from DB column names:
```sql
SELECT $productId:=product_id, $productName:=product_name, $unitCost:=unit_price
FROM "products"
```
`$cloverField:=` prefix binds the result column to the named metadata field by name rather than position.

### `${LIMIT_CLAUSE}` pattern for dev/preview throttling
Append `${LIMIT_CLAUSE}` at the end of any SELECT. In production the parameter is empty string; during development set it to `LIMIT 100` to avoid reading millions of rows:
```sql
SELECT * FROM "customers" ${LIMIT_CLAUSE}
```

## Column Quoting Styles (DB-dependent)

| Style | Syntax | Use with |
|---|---|---|
| Double-quote | `"schema"."table"."column"` | PostgreSQL, Oracle, DB2, Snowflake — preserves case |
| Backtick | `` `table`.`column` `` | MySQL, MariaDB |
| No quoting | `table.column` | Case-insensitive identifiers, simple schemas |
| Schema-qualified | `"public"."customers"."city"` | PostgreSQL when schema is not the search path default |

Use double-quoted identifiers whenever column/table names are mixed-case, start with `_`, or are reserved words.

## Real Sandbox Examples

### DWHExample — read active dimension records (MySQL, backtick quoting, parameterized fetchSize)
```xml
<Node dbConnection="JDBC0" fetchSize="${DB_FETCH_SIZE}"
      guiName="product dim" id="PRODUCT_DIM"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[select `_id`,`_natural_key_id`,`_natural_key_hash`
from `product_dim`
where `_is_active` = 1]]></attr>
</Node>
```
Note: backtick quoting = MySQL backend. `fetchSize` always parameterized via `${DB_FETCH_SIZE}`.

### DWHExample — JOIN target with temp table for SCD2 comparison (PostgreSQL, double-quote, parameterized tables)
```xml
<Node charset="UTF-8" dbConnection="JDBC0" fetchSize="${DB_FETCH_SIZE}"
      guiName="Get Records from target" id="GET_RECORDS_FROM_TARGET"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[select "d"."_id","d"."_natural_key_id","d"."_natural_key_hash","d"."_checksum"
from "${TARGET_DB_TABLE}" as d
join "${TEMPORARY_TABLE_NAME}" as t on "d"."_natural_key_hash"="t"."_natural_key_hash"
where "d"."_is_active"=1]]></attr>
</Node>
```
Note: `charset="UTF-8"` set with double-quote quoting; both table names are graph parameters.

### NorthwindDBDemoLib — schema-qualified SELECT with LIMIT_CLAUSE
```xml
<Node dbConnection="JDBC1" guiName="ReadCustomers" id="READ_CUSTOMERS"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[select "public"."customers"."customer_id",
       "public"."customers"."company_name",
       "public"."customers"."contact_name",
       "public"."customers"."address",
       "public"."customers"."city",
       "public"."customers"."country"
from "public"."customers" ${LIMIT_CLAUSE}]]></attr>
</Node>
```

### NorthwindDBDemoLib — multi-table join with aggregation (GROUP BY + COUNT/SUM)
```xml
<Node dbConnection="JDBC0" guiName="TotalOrdersByCustomers" id="TOTAL_ORDERS_BY_CUSTOMERS"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[select "public"."orders"."order_id",
       "public"."orders"."customer_id",
       count("public"."order_details"."product_id") as num_products,
       sum("public"."order_details"."unit_price" * "public"."order_details"."quantity") as order_total_value
from "orders", "order_details"
where "orders"."order_id" = "order_details"."order_id"
group by "public"."orders"."order_id", "public"."orders"."customer_id"
${LIMIT_CLAUSE}]]></attr>
</Node>
```

### NorthwindDBDemoLib — correlated subqueries per row (revenue per employee)
```xml
<Node dbConnection="JDBC0" guiName="ReadEmployees" id="READ_EMPLOYEES"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[select empl."employee_id", empl."last_name", empl."first_name",
       (select sum(("public"."order_details"."unit_price" - "public"."order_details"."discount")
                   * "public"."order_details"."quantity")
        from "public"."orders", "public"."order_details"
        where "public"."orders"."order_id" = "public"."order_details"."order_id"
          and "public"."orders"."employee_id" = empl."employee_id"
        group by "public"."orders"."employee_id") as total_revenue
from "public"."employees" empl]]></attr>
</Node>
```

## Incremental Reading

Read only new records since last run — tracks the high-water mark in a file:

```xml
<Node dbConnection="JDBC0" id="READER"
      incrementalFile="${DATATMP_DIR}/customers_inc_key"
      incrementalKey="key01=&quot;LAST(id)!5&quot;"
      type="DB_INPUT_TABLE">
    <attr name="sqlQuery"><![CDATA[SELECT id, date, first_name, last_name
FROM customers
WHERE id > #key01]]></attr>
</Node>
```

- `incrementalKey`: `key01="LAST(id)!5"` — `LAST(id)` tracks the max `id` seen; `!5` = initial value 5
- `#key01` in WHERE clause replaced by the stored high-water value at runtime
- After each run the file is updated with the new max
- Both `incrementalFile` and `incrementalKey` must be set together

## Reading Query from Input Port

Execute a dynamic SQL query arriving from an upstream component:

```xml
<!-- Upstream produces a string field containing the SQL to execute -->
<Node dbConnection="JDBC0" queryURL="port:$0.sql_query:discrete"
      id="DYNAMIC_READER" type="DB_INPUT_TABLE"/>
```

Input port 0 metadata must contain a single `string` (or `byte`) field. `EOF as delimiter` should be `true` on that metadata. One query is executed per input record.

## Edge Port Names
- Input 0: `Port 0 (in)` (optional)
- Output 0: `Port 0 (out)`
- Output 1+: `Port N (out)`

## Connection Declaration
```xml
<Connection dbDriver="..." dbURL="..." id="JDBC0" name="MyDB" type="JDBC"
            fileURL="${CONN_DIR}/MyConnection.cfg"/>
```
Use `list_linked_assets(asset_type='connection')` to discover existing connections in the sandbox.

## Decision Guide

| Need | Approach |
|---|---|
| Simple table read, field names match | Plain `SELECT col1, col2 FROM table` (positional) |
| Field names differ from DB columns | Use `$cloverField:=dbColumn` aliasing in SELECT |
| Dynamic table name at runtime | `"${GRAPH_PARAM}"` inside SQL string |
| JOIN two tables | Explicit `JOIN ... ON` or WHERE-clause style |
| Aggregate/GROUP BY results | Standard SQL aggregation in `sqlQuery` |
| Dev/test row limiting without graph changes | Append `${LIMIT_CLAUSE}` and set param to `LIMIT 100` |
| Only new records since last run | `incrementalFile` + `incrementalKey` + `WHERE id > #key` |
| SQL shared across graphs | `queryURL` pointing to external `.sql` file |
| Dynamic SQL from upstream component | `queryURL="port:$0.fieldName:discrete"` |
| Duplicate stream to two downstream paths | Connect both output ports (fan-out — same records to all) |

## Mistakes

| Wrong | Correct |
|---|---|
| Relying on column name = field name without checking order | Positional mapping depends on SELECT column order matching metadata field order — verify both |
| `queryURL` and `sqlQuery` both set | `queryURL` takes precedence — remove `sqlQuery` to avoid confusion |
| `${LIMIT_CLAUSE}` without declaring the parameter | Declare `LIMIT_CLAUSE` as a graph parameter (default empty string) |
| Backtick quoting on PostgreSQL | Use `"double_quotes"` for PostgreSQL; backticks are MySQL only |
| `select *` with metadata having fewer fields than DB columns | Positional mapping fails silently or throws — enumerate columns explicitly |
| Using `$field:=column` syntax in WHERE clause | `$field:=` aliasing is only valid in SELECT list, not WHERE |
| `fetchSize` left at default 20 for large reads | Set `fetchSize="${DB_FETCH_SIZE}"` or a larger value (e.g. 1000) for production bulk reads |
| `autoCommit="true"` when running in a shared transaction | Set `autoCommit="false"` when multiple DB operations must share one transaction |
| External SQL file without `charset` | Always set `charset="UTF-8"` with `queryURL` external files |
| Both `incrementalFile` and `incrementalKey` not set together | Both must be specified — one without the other causes a validation error |
