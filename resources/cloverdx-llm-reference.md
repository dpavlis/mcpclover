# CloverDX Transformation Graph Reference for LLMs

> **Purpose:** Concise reference for generating valid CloverDX transformation graph XML (`.grf` files). Focuses on structure, syntax, and semantics — not UI/designer workflows.

---

## 1. Graph File Format (.grf)

CloverDX graphs are XML documents. The root element is `<Graph>`. File extension: `.grf` (graphs), `.sgrf` (subgraphs), `.jbf` (jobflows).

### Minimal valid graph skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph author="author" created="2024-01-01" description="Description" guiVersion="6.0.0" id="GRAPH_ID" licenseCode="" name="GraphName" revision="1.0">
  <Global>
    <GraphParameters>
      <GraphParameter name="PROJECT" value="."/>
      <!-- GraphParameterFile links workspace.prm — imports all standard directory params -->
      <GraphParameterFile fileURL="workspace.prm"/>
    </GraphParameters>
    <Metadata id="Metadata0">
      <Record fieldDelimiter=";" name="record_name" recordDelimiter="\n" type="delimited">
        <Field name="field1" type="string"/>
        <Field name="field2" type="integer"/>
      </Record>
    </Metadata>
  </Global>
  <Phase number="0">
    <Node enabled="enabled" guiName="FlatFileReader" guiX="24" guiY="24" id="FLATFILEREADER0" type="DATA_READER">
      <attr name="fileURL"><![CDATA[${DATAIN_DIR}/input.csv]]></attr>
    </Node>
    <Node enabled="enabled" guiName="FlatFileWriter" guiX="300" guiY="24" id="FLATFILEWRITER0" type="DATA_WRITER">
      <attr name="fileURL"><![CDATA[${DATAOUT_DIR}/output.csv]]></attr>
    </Node>
    <Edge fromNode="FLATFILEREADER0:0" guiRouter="Manhattan" id="Edge0" inPort="Port 0 (in)" metadata="Metadata0" outPort="Port 0 (out)" toNode="FLATFILEWRITER0:0"/>
  </Phase>
</Graph>
```

---

## 2. Graph XML Structure

### `<Graph>` Root Attributes

| Attribute | Description |
|-----------|-------------|
| `id` | Unique graph identifier |
| `name` | Human-readable graph name |
| `description` | Graph description |
| `guiVersion` | CloverDX designer version |
| `author` | Author name |
| `created` | Creation date |

### `<Global>` Section

Contains graph-wide elements: `<GraphParameters>`, `<Metadata>`, `<Connection>`, `<LookupTable>`, `<Sequence>`, `<Dictionary>`.

### `<Phase>` Element

```xml
<Phase number="0">
  <!-- Nodes and Edges with the same phase number run in parallel -->
  <!-- Phases execute sequentially: phase 0 completes before phase 1 starts -->
</Phase>
```

- `number` attribute: integer, must be non-decreasing across phases
- All components in same phase run concurrently
- A new phase starts only after the previous one finishes successfully

### `<Node>` Element (Component)

```xml
<Node enabled="enabled" guiName="ComponentLabel" guiX="100" guiY="100"
      id="UNIQUE_NODE_ID" type="COMPONENT_TYPE" phase="0">
  <attr name="attributeName"><![CDATA[value]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.field1 = $in.0.field1;
    return ALL;
}
  ]]></attr>
</Node>
```

Key `<Node>` attributes:
- `id`: unique within graph, conventionally COMPONENTTYPE_N (e.g., `FLATFILEREADER0`)
- `type`: component type string (e.g., `DATA_READER`, `MAP`, `EXT_HASH_JOIN`)
- `enabled`: `enabled` | `disabled` | `passThrough`
- `phase`: integer, which phase this node belongs to (default `0`)
- `guiX`, `guiY`: visual layout coordinates (required for Designer)
- `guiName`: display label

Component-specific attributes go inside `<attr name="...">` child elements using CDATA.

### `<Edge>` Element

```xml
<Edge fromNode="SOURCE_NODE_ID:outputPortNumber"
      toNode="TARGET_NODE_ID:inputPortNumber"
      id="EdgeN"
      metadata="MetadataId"
      guiRouter="Manhattan"
      inPort="Port 0 (in)"
      outPort="Port 0 (out)"/>
```

Key `<Edge>` attributes:
- `fromNode`: `NodeID:portNumber` (output port of source)
- `toNode`: `NodeID:portNumber` (input port of target)
- `id`: unique edge identifier
- `metadata`: references `<Metadata id="...">` — describes data structure flowing through edge
- `edgeType`: *(optional)* CloverDX automatically determines the optimal edge type when it loads and analyses the graph. You do not need to set this attribute manually.

Port numbering starts at `0`. Format: `NODE_ID:0`, `NODE_ID:1`, etc.

---

## 3. Metadata

Metadata describes the record structure flowing through an edge.

### Internal Metadata (defined inside graph)

```xml
<Metadata id="MetadataId">
  <Record fieldDelimiter=";" name="RecordName" recordDelimiter="\n" type="delimited"
          locale="en.US" charset="UTF-8">
    <Field name="firstName" type="string" delimiter=";"/>
    <Field name="salary" type="integer" delimiter="\n"/>
    <Field name="birthDate" type="date" format="yyyy-MM-dd" delimiter=";"/>
    <Field name="amount" type="decimal" length="12" scale="2" delimiter=";"/>
  </Record>
</Metadata>
```

### External (Shared) Metadata

```xml
<Metadata fileURL="${META_DIR}/employees.fmt" id="MetadataId"/>
```

### Record Types

| Type | Description |
|------|-------------|
| `delimited` | Fields separated by delimiters |
| `fixed` | Fixed-width fields (use `size` on `<Field>`) |
| `mixed` | Mix of delimited and fixed fields |

### Field Data Types

| Type | Description | Notes |
|------|-------------|-------|
| `string` | Unicode text | Default for text fields |
| `integer` | 32-bit signed int | Range: -2³¹ to 2³¹-1 |
| `long` | 64-bit signed int | Range: -2⁶³ to 2⁶³-1 |
| `number` | 64-bit IEEE 754 double | |
| `decimal` | Fixed-precision decimal | Use `length` and `scale` attrs |
| `date` | Date/time (ms precision) | Use `format` attr for pattern |
| `boolean` | Boolean | |
| `byte` | Raw bytes | |
| `cbyte` | Compressed bytes | |
| `variant` | Any type incl. lists/maps | |

### Field Attributes

| Attribute | Applies To | Description |
|-----------|-----------|-------------|
| `name` | all | Field name (required) |
| `type` | all | Data type (required) |
| `delimiter` | delimited/mixed | Field delimiter (e.g., `;`, `\n`, `\t`) |
| `size` | fixed/mixed | Field width in characters |
| `format` | date, number, decimal | Format pattern |
| `locale` | date, number | Locale (e.g., `en.US`, `de.DE`) |
| `timezone` | date | Time zone (e.g., `America/New_York`) |
| `nullable` | all | Whether null is allowed (`true`/`false`) |
| `default` | all | Default value if field is null |
| `length` | decimal | Total digit count (default 12) |
| `scale` | decimal | Digits after decimal point (default 2) |
| `autoFilling` | all | Auto-fill function: `global_row_count`, `source_name`, etc. |

### Date Format Patterns (Java-style)

`yyyy-MM-dd`, `yyyy-MM-dd HH:mm:ss`, `dd/MM/yyyy`, `HH:mm:ss.SSS`
Prefix with `joda:` for Joda library; use `iso-8601:dateTime` for ISO 8601.

### Container Types: list and map

CloverDX metadata supports container fields (list and map) using the **`containerType`** attribute on `<Field>`. The `type` attribute specifies the **element type** (scalar type of each item), and `containerType` is set to `"list"` or `"map"`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Metadata id="Metadata0">
  <Record name="CustomerRecord" type="delimited">
    <!-- Standard single-value field -->
    <Field name="customer_id"  type="integer"/>
    <!-- List container type: holds multiple strings (e.g., tags) -->
    <Field name="tags"         type="string"  containerType="list"/>
    <!-- Map container type: holds key-value pairs (key is always string) -->
    <Field name="attributes"   type="string"  containerType="map"/>
  </Record>
</Metadata>
```

> **Key rule:** `containerType="list"` / `containerType="map"` declares a collection field. `type` = the element's scalar type (e.g., `type="integer" containerType="map"` for a map of integers). Do **not** use `type="variant"` for container fields.

In CTL2, typed list and map variables:

```ctl
//#CTL2
function integer transform() {
    // List: declared with element type
    list[string] tags = ["apple", "banana", "cherry"];
    append(tags, "date");          // add to end
    integer len = length(tags);    // 4
    string first = tags[0];        // "apple" (0-indexed)

    // Map: declared with key and value types
    map[string, integer] scores = { "alice" -> 90, "bob" -> 85 };
    scores["charlie"] = 92;
    list[string] keys = getKeys(scores);
    boolean hasKey = containsKey(scores, "alice");  // true

    // Writing to container fields in metadata (containerType="list" / containerType="map")
    $out.0.tags       = ["tag1", "tag2"];                    // list literal → list field
    $out.0.attributes = { "color" -> "red", "size" -> "L" }; // map literal → map field

    // Reading from container fields (or a variant variable)
    variant v = $in.0.payload;   // variant is a CTL2 type for untyped/dynamic values
    variant elem = v[0];          // index into list
    variant val  = v["key"];      // key into map

    return ALL;
}
```

**CTL2 container type syntax:**

| Type | Literal syntax | Access |
|------|---------------|--------|
| `list[T]` | `["a", "b", "c"]` | `myList[0]` (0-indexed) |
| `map[K, V]` | `{"key" -> value, "k2" -> v2}` | `myMap["key"]` |
| `variant` | either form above | `v[0]` or `v["key"]` |

**Key container functions:** `append(list, elem)`, `push(list, elem)`, `pop(list)`, `poll(list)`, `insert(list, idx, elem)`, `remove(list, idx)` / `remove(map, key)`, `clear(container)`, `sort(list)`, `reverse(list)`, `length(container)`, `isEmpty(container)`, `containsValue(container, val)`, `containsKey(map, key)`, `getKeys(map)`, `getValues(map)`, `toMap(keys[], values[])`, `findAllValues(variant, key)`, `in(elem, container)`, `appendAll(target, source)`.

**Nested structures** (JSON-like): `variant` can nest lists-of-maps, maps-of-lists, etc., forming arbitrary tree structures. Use `parseJson()` / `toJson()` to serialise/deserialise.

---

## 4. Graph Parameters

Two distinct XML elements are used inside `<GraphParameters>`:

- **`<GraphParameter name="X" value="Y"/>`** — declares an inline parameter. `name` and `value` are required. Do NOT add `fileURL` to this element.
- **`<GraphParameterFile fileURL="workspace.prm"/>`** — links an external `.prm` file; all parameters defined in that file are imported. This is a **different element** from `<GraphParameter>`.

```xml
<GraphParameters>
  <GraphParameter name="PROJECT" value="."/>
  <GraphParameter name="MY_PARAM" value="some_value"/>
  <!-- Secure parameter: -->
  <GraphParameter name="DB_PASSWORD" secure="true" value="encryptedValue"/>
  <!-- Dynamic CTL2 parameter: -->
  <GraphParameter name="TODAY" dynamicValue="//#CTL2&#10;function string getValue(){return date2str(today(),&quot;yyyy-MM-dd&quot;);}"/>
  <!-- Link workspace.prm (use GraphParameterFile, NOT GraphParameter): -->
  <GraphParameterFile fileURL="workspace.prm"/>
</GraphParameters>
```

> **INVALID — causes "empty graph parameter name" error:** `<GraphParameter/>` with no attributes, or `<GraphParameter name="" value="..."/>`. Never use `<GraphParameter fileURL="..."/>` — the correct element for linking files is `<GraphParameterFile fileURL="..."/>`.

Usage in attributes: `${PARAM_NAME}` — resolved before graph execution.

---

## 5. Connections

### Database Connection

```xml
<Connection dbDriver="com.mysql.cj.jdbc.Driver"
            dbURL="jdbc:mysql://localhost:3306/mydb"
            id="DBConnection0"
            name="MySQL Connection"
            password="****"
            type="JDBC"
            user="root"/>
```

External connection file reference:
```xml
<Connection fileURL="${CONN_DIR}/mydb.cfg" id="DBConnection0"/>
```

### Connection Types

| `type` | Description |
|--------|-------------|
| `JDBC` | Generic JDBC database |
| `JNDI` | JNDI data source |
| `JMS` | Java Message Service |
| `HADOOP` | Hadoop HDFS |
| `KAFKA` | Apache Kafka |
| `MONGODB` | MongoDB |
| `SALESFORCE` | Salesforce |
| `QUICKBASE` | QuickBase |

---

## 6. Lookup Tables

```xml
<!-- Simple (in-memory) lookup table -->
<LookupTable charset="UTF-8" id="LookupTable0" initialSize="512" key="id"
             metadata="Metadata0" name="myLookup" type="simpleLookup">
  <attr name="fileURL"><![CDATA[${DATAIN_DIR}/lookup_data.csv]]></attr>
</LookupTable>

<!-- Database lookup table -->
<LookupTable dbConnection="DBConnection0" id="LookupTable1"
             metadata="Metadata1" name="dbLookup" type="dbLookup">
  <attr name="sqlQuery"><![CDATA[SELECT * FROM table WHERE id = ?]]></attr>
</LookupTable>
```

### Lookup Table Types

| Type | Storage | Duplicates | Notes |
|------|---------|-----------|-------|
| `simpleLookup` | Memory | Yes | Fast; whole table in RAM |
| `dbLookup` | Database (with cache) | Yes | Query-based |
| `rangeLookup` | Memory | No (overlapping OK) | For interval-based lookups |
| `persistentLookup` | Disk (B+Tree) + cache | Optional | Large datasets |
| `aspellLookup` | Memory | Yes | Fuzzy/spelling match |

---

## 7. Sequences

```xml
<!-- Non-persistent (resets each run) -->
<Sequence id="Sequence0" name="mySeq" start="1" step="1" type="SIMPLE_SEQUENCE"/>

<!-- Persistent (survives restarts) -->
<Sequence fileURL="${SEQ_DIR}/mySeq.seq" id="Sequence0" name="mySeq"
          start="1" step="1" type="SIMPLE_SEQUENCE"/>
```

Usage in CTL: `nextval("Sequence0")`, `currentval("Sequence0")`, `resetval("Sequence0")`

---

## 8. CTL2 Transformation Language

Used in component `transform`, `filterExpression`, `aggregationMapping`, and other code attributes.

### Basic transform template (Map, Joiners)

```ctl
//#CTL2

// Called once before processing
function void init() {
}

// Called for each record; return port number or ALL
function integer transform() {
    $out.0.outputField = $in.0.inputField;
    $out.0.fullName = $in.0.firstName + " " + $in.0.lastName;
    return ALL;  // send to all output ports; or return 0, 1, etc.
}

// Called on error
function void transformOnError(string errorMessage, string stackTrace) {
}
```

### Field access syntax

```ctl
$in.0.fieldName     // input port 0, field "fieldName"
$in.1.fieldName     // input port 1
$out.0.fieldName    // output port 0
$out.0.* = $in.0.*  // copy all fields by name
```

### Common CTL2 functions

```ctl
// String
length($in.0.s)
substring($in.0.s, 0, 5)
trim($in.0.s)
uppercase($in.0.s)
lowercase($in.0.s)
concat($in.0.a, " ", $in.0.b)
replace($in.0.s, "old", "new")
split($in.0.s, ";")           // returns list
contains($in.0.s, "substr")

// Numeric
abs($in.0.n)
round($in.0.n)
min($in.0.a, $in.0.b)
max($in.0.a, $in.0.b)

// Date
today()                          // current date
now()                            // current datetime
date2str($in.0.d, "yyyy-MM-dd")
str2date($in.0.s, "yyyy-MM-dd")
addDay($in.0.d, 7)

// Type conversion
num2str($in.0.n)
str2integer($in.0.s)
str2double($in.0.s)
str2date($in.0.s, "yyyy-MM-dd")

// Null checks
isNull($in.0.field)
iif($in.0.field == null, "default", $in.0.field)

// Sequences
nextval("SequenceId")

// Lookup
lookup("LookupId").get("keyValue").fieldName
```

### Denormalizer/Rollup/Normalizer templates differ — use `append()`, `transform()`, `count()` pattern.

---

## 9. Component Reference

### Component Type String Conventions

The `type` attribute on `<Node>` uses the internal component type identifier (ALL_CAPS with underscores). Common examples below.

---

### Data Policy (Readers)

`dataPolicy` controls behaviour when a record field has incorrect/unparseable value:

| Value | Behaviour | Error port |
|-------|-----------|------------|
| `strict` | **Default.** Abort on first bad record. Graph fails. | — |
| `controlled` | Log each error; skip bad record; continue processing. Bad records sent to port 1 (if connected) on: FlatFileReader, ParallelReader, JSONReader, SpreadsheetDataReader. Other readers only log to stdout. | Optional port 1 |
| `lenient` | Silently skip bad records and continue. No logging. | — |

Supported on: `DATA_READER`, `DB_INPUT_TABLE`, `JSON_READER`, `XML_READER`, `XML_XPATH_READER`, `COMPLEX_DATA_READER`, `MULTI_LEVEL_READER`, `PARALLEL_READER`, `DBF_DATA_READER`.

```xml
<Node type="DATA_READER" id="R0">
  <attr name="fileURL"><![CDATA[${DATAIN_DIR}/input.csv]]></attr>
  <attr name="dataPolicy"><![CDATA[controlled]]></attr>
</Node>
<!-- Port 0: good records; Port 1: rejected records (for DATA_READER) -->
<Edge fromNode="R0:0" id="E_good"     metadata="GoodMeta"     toNode="NEXT:0"/>
<Edge fromNode="R0:1" id="E_rejected" metadata="RejectedMeta" toNode="TRASH0:0"/>
```

The **error metadata** (port 1) for `DATA_READER` contains: all original fields plus `ErrCode` (integer) and `ErrText` (string) autofilling fields describing the parse error.

---

### READERS — Summary Table

| Component (type) | Source | In ports | Out ports | Key attributes |
|-----------------|--------|----------|-----------|----------------|
| `DATA_READER` FlatFileReader | flat file | 0–1 | 1–2 | `fileURL`, `charset`, `dataPolicy`, `skipRows`, `numRecords`, `trim` |
| `DB_INPUT_TABLE` DatabaseReader | JDBC DB | 0 | 1–n | `dbConnection`, `sqlQuery` / `queryURL`, `fetchSize` |
| `JSON_READER` JSONReader | JSON file | 0–1 | 1–n | `fileURL`, `mapping` (XML) |
| `JSON_EXTRACT` JSONExtract | JSON file | 0–1 | 1–n | `fileURL`, `mapping` (XML) |
| `XML_READER` XMLReader | XML file | 0–1 | 1–n | `sourceUri`, `mapping` (XML) |
| `XML_EXTRACT` XMLExtract | XML file | 0–1 | 1–n | `sourceUri`, `mapping` (XML) |
| `XML_XPATH_READER` XMLXPathReader | XML file | 0–1 | 1–n | `sourceUri`, `mapping` (XML) |
| `SPREADSHEET_READER` SpreadsheetDataReader | XLS/XLSX | 0–1 | 1–2 | `fileURL`, `sheetName`, `startRow`, `startColumn` |
| `CLOVER_DATA_READER` CloverDataReader | CloverDX binary | 0 | 1–n | `fileURL` |
| `DATA_GENERATOR` DataGenerator | generated | 0 | 1–n | `recordsNumber`, `transform` (CTL `generate()`) |
| `PARQUET_READER` ParquetReader | Parquet file | 0–1 | 1–2 | `fileURL` |
| `KAFKA_READER` KafkaReader | Kafka | 0 | 1 | `connection`, `topic`, `transform` |
| `MONGODB_READER` MongoDBReader | MongoDB | 0–1 | 1–2 | `connectionURL`, `collectionName`, `query`, `transform` |
| `SALESFORCE_READER` SalesforceReader | Salesforce | 0 | 1 | `connection`, `soqlQuery`, `transform` |
| `SALESFORCE_BULK_READER` SalesforceBulkReader | Salesforce | 0 | 1 | `connection`, `soqlQuery`, `transform` |
| `COMPLEX_DATA_READER` ComplexDataReader | binary flat file | 1 | 1–n | `fileURL`, `transform` (required) |
| `MULTI_LEVEL_READER` MultiLevelReader | flat file | 1 | 1–n | `fileURL`, `transform` (required) |
| `EMAIL_READER` EmailReader | email (IMAP) | 0 | 1 | `connection`, `folder`, `transform` |
| `JMS_READER` JMSReader | JMS | 0 | 1 | `connection`, `transform` |
| `LDAP_READER` LDAPReader | LDAP | 0 | 1–n | `ldapUrl`, `base`, `filter` |
| `QUICKBASE_RECORD_READER` QuickBaseRecordReader | QuickBase | 0–1 | 1–2 | `connection`, `tableId` |
| `DBF_DATA_READER` DBFDataReader | dBase file | 0–1 | 1–n | `fileURL` |

---

### WRITERS — Summary Table

| Component (type) | Target | In ports | Out ports | Key attributes |
|-----------------|--------|----------|-----------|----------------|
| `DATA_WRITER` FlatFileWriter | flat file | 1 | 0–1 | `fileURL`, `charset`, `append`, `excludeFields` |
| `DB_OUTPUT_TABLE` DatabaseWriter | JDBC DB | 1 | 0–2 | `dbConnection`, `sqlQuery` / `dbTable`, `batchMode`, `batchSize`, `commit` |
| `JSON_WRITER` JSONWriter | JSON file | 1–n | 0–1 | `fileURL`, `mapping` (XML) |
| `EXT_XML_WRITER` XMLWriter | XML file | 1–n | 0–1 | `fileURL`, `mapping` (XML) |
| `SPREADSHEET_WRITER` SpreadsheetDataWriter | XLS/XLSX | 1 | 0–1 | `fileURL`, `sheetName`, `mappingType` |
| `CLOVER_DATA_WRITER` CloverDataWriter | CloverDX binary | 1 | 0–1 | `fileURL`, `compressLevel` |
| `TRASH` Trash | none (discard) | 1 | 0 | — |
| `PARQUET_WRITER` ParquetWriter | Parquet file | 1 | 0–1 | `fileURL` |
| `KAFKA_WRITER` KafkaWriter | Kafka | 1 | 0–2 | `connection`, `topic`, `transform` |
| `MONGODB_WRITER` MongoDBWriter | MongoDB | 1 | 0–2 | `connectionURL`, `collectionName`, `transform` (required) |
| `EMAIL_SENDER` EmailSender | email | 0–1 | 0–2 | `smtpHost`, `to`, `subject`, `body` |
| `SALESFORCE_WRITER` SalesforceWriter | Salesforce | 1 | 2 | `connection`, `sobjectType`, `operation`, `transform` |
| `SALESFORCE_BULK_WRITER` SalesforceBulkWriter | Salesforce | 1 | 2 | `connection`, `sobjectType`, `operation`, `transform` |
| `DB2_DATA_WRITER` DB2BulkWriter | DB2 | 0–1 | 0–1 | `dbConnection`, `table`, `fileURL` |
| `MSSQL_DATA_WRITER` MSSQLBulkWriter | MSSQL | 0–1 | 0–1 | `dbConnection`, `table` |
| `MYSQL_DATA_WRITER` MySQLBulkWriter | MySQL | 0–1 | 0–1 | `dbConnection`, `table` |
| `ORACLE_DATA_WRITER` OracleBulkWriter | Oracle | 0–1 | 0–1 | `dbConnection`, `table` |
| `POSTGRESQL_DATA_WRITER` PostgreSQLBulkWriter | PostgreSQL | 0–1 | 0 | `dbConnection`, `table` |
| `SNOWFLAKE_BULK_WRITER` SnowflakeBulkWriter | Snowflake | 1 | 0–1 | `connection`, `table` |
| `JMS_WRITER` JMSWriter | JMS | 1 | 0 | `connection`, `transform` |
| `LDAP_WRITER` LDAPWriter | LDAP | 1 | 0–1 | `ldapUrl`, `action` |
| `STRUCTURED_DATA_WRITER` StructuredDataWriter | structured flat file | 1–3 | 0–1 | `fileURL`, `mask` |

---

### TRANSFORMERS — Summary Table

| Component (type) | What it does | In | Out | Key attributes / Notes |
|-----------------|-------------|----|----|------------------------|
| `REFORMAT` Map/Reformat | Field-level transform via CTL | 1 | 1–n | `transform` (CTL), `transformURL`. Returns port number or `ALL`. |
| `EXT_FILTER` Filter | Keep/reject records | 1 | 1–2 | `filterExpression` (CTL boolean). Port 0=accepted, port 1=rejected. |
| `EXT_SORT` ExtSort | Disk-based sort | 1 | 1–n | `sortKey` (`field(a);field2(d)`), `bufferCapacity` |
| `FAST_SORT` FastSort | In-memory sort | 1 | 1–n | `sortKey` (`field(a);field2(d)`) |
| `SORT_WITHIN_GROUPS` SortWithinGroups | Sort within groups (sorted input required) | 1 | 1–n | `sortKey`, `groupKeyFields` |
| `AGGREGATE` Aggregate | Group + aggregate | 1 | 1 | `aggregateKey`, `mapping` (agg expressions) |
| `SIMPLE_COPY` SimpleCopy | Copy to ALL outputs | 1 | 1–n | — |
| `SIMPLE_GATHER` SimpleGather | Merge N inputs (same metadata) | 1–n | 1 | — |
| `CONCATENATE` Concatenate | Merge N inputs (same metadata), order preserved | 1–n | 1 | — |
| `MERGE` Merge | Merge N sorted inputs into one sorted output | 2–n | 1 | `joinKey` (sort key) — inputs must be sorted |
| `DEDUP` Dedup | Remove consecutive duplicates (sorted input) | 1 | 1–2 | `key`, `keep` (`First`\|`Last`\|`Unique`) |
| `PARTITION` Partition | Route to different output ports | 1 | 1–n | `ranges` (XML), `partitionKey` (hash), or CTL `transform` |
| `LOAD_BALANCING_PARTITION` LoadBalancingPartition | Round-robin distribution | 1 | 1–n | — |
| `NORMALIZER` Normalizer | 1 input record → N output records | 1 | 1 | `transform` (CTL: `count()` + `transform(idx)`) |
| `DENORMALIZER` Denormalizer | N input records → 1 output (sorted groups) | 1 | 1 | `key`, `transform` (CTL: `append()` + `transform()`) |
| `ROLLUP` Rollup | Group processing with full CTL control | 1 | 1–n | `groupKeyFields`, `transform` (CTL: `initGroup`, `updateGroup`, `finishGroup`) |
| `DATA_INTERSECTION` DataIntersection | Intersect/diff two sorted inputs | 2 | 3 | `joinKey`, `transform` — inputs must be sorted |
| `DATA_SAMPLER` DataSampler | Statistical sampling | 1 | n | `samplingFactor`, `sampleSize` |
| `META_PIVOT` MetaPivot | Pivot rows to columns based on metadata | 1 | 1 | `masterKey`, `pivotKey`, `valueField` |
| `PIVOT` Pivot | Pivot with CTL | 1 | 1 | `transform` (required) |
| `XSL_TRANSFORMER` XSLTransformer | XSLT transformation | 0–1 | 0–2 | `xslFile`, `inputField`, `outputField` |
| `BARRIER` Barrier | Synchronises parallel flows (waits for all) | — | — | `guiName`, used between phases |

---

### JOINERS — Summary Table

All joiners: **Port 0 = master (driver)**, **Port 1+ = slave(s)**. Output port 0 = joined result, output port 1 (where present) = unmatched master records.

| Component (type) | Join type | Sorted? | Slaves | Key attributes |
|-----------------|-----------|---------|--------|----------------|
| `EXT_HASH_JOIN` ExtHashJoin | equality, hash-based | No | 1–n | `joinKey` (`$0.f=$1.f#...`), `joinType` (`inner`\|`leftOuter`\|`fullOuter`), `transform`, `allowSlaveDuplicates` |
| `EXT_MERGE_JOIN` ExtMergeJoin | equality, merge | Yes (both) | 1–n | `joinKey`, `joinType`, `transform` |
| `LOOKUP_JOIN` LookupJoin | equality, lookup table | No | virtual | `lookupTable`, `joinKey`, `transform` |
| `DB_JOIN` DBJoin | equality, DB query | No | virtual (DB) | `dbConnection`, `sqlQuery` (? params), `joinKey`, `transform` |
| `RELATIONAL_JOIN` RelationalJoin | non-equality conditions | Yes | 1 | `joinCondition` (CTL boolean), `transform` |
| `CROSS_JOIN` CrossJoin | cartesian product | No | 0–n | `transform` |
| `COMBINE` Combine | custom combination | No | 1–n | `transform` (required) |

**joinKey format for EXT_HASH_JOIN / EXT_MERGE_JOIN:** `$masterPort.field=$slavePort.field#$masterPort.field2=$slavePort.field2`
Example: `$0.customerId=$1.id#$0.type=$1.type`

---

### READERS

#### DATA_READER (FlatFileReader / UniversalDataReader)

Reads CSV, TSV, fixed-width, and mixed text files.

```xml
<Node enabled="enabled" guiName="FlatFileReader" guiX="24" guiY="24"
      id="DATA_READER0" type="DATA_READER">
  <attr name="fileURL"><![CDATA[${DATAIN_DIR}/input.csv]]></attr>
  <attr name="charset"><![CDATA[UTF-8]]></attr>
  <attr name="dataPolicy"><![CDATA[strict]]></attr>
  <!-- Optional: -->
  <attr name="skipRows"><![CDATA[1]]></attr>       <!-- skip header row -->
  <attr name="numRecords"><![CDATA[1000]]></attr>  <!-- max records -->
  <attr name="trim"><![CDATA[true]]></attr>
</Node>
```

Ports: Input 0 (optional, for port-reading), Output 0 (data), Output 1 (parse errors when `dataPolicy="controlled"`).

---

#### DB_INPUT_TABLE (DatabaseReader)

Reads from database via JDBC.

```xml
<Node dbConnection="DBConnection0" enabled="enabled" guiName="DatabaseReader"
      guiX="24" guiY="24" id="DB_INPUT_TABLE0" type="DB_INPUT_TABLE">
  <attr name="sqlQuery"><![CDATA[SELECT id, name, salary FROM employees WHERE active = 1]]></attr>
  <!-- Or use queryURL for external SQL file -->
</Node>
```

Use `sqlQuery` for inline SQL or `queryURL` for external `.sql` file. `fetchSize` controls batch fetch size (default 20).

---

#### JSON_READER (JSONReader)

```xml
<Node enabled="enabled" guiName="JSONReader" guiX="24" guiY="24"
      id="JSON_READER0" type="JSON_READER">
  <attr name="fileURL"><![CDATA[${DATAIN_DIR}/data.json]]></attr>
  <attr name="mapping"><![CDATA[
    <Mappings>
      <Mapping element="element/path" outPort="0">
        <Mapping element="field1" outPort="0" cloverField="field1"/>
      </Mapping>
    </Mappings>
  ]]></attr>
</Node>
```

---

#### XML_EXTRACT (XMLExtract)

```xml
<Node enabled="enabled" guiName="XMLExtract" guiX="24" guiY="24"
      id="XML_EXTRACT0" type="XML_EXTRACT">
  <attr name="sourceUri"><![CDATA[${DATAIN_DIR}/data.xml]]></attr>
  <attr name="mapping"><![CDATA[
    <Mappings>
      <Mapping element="root/record" outPort="0">
        <Mapping element="@id" cloverField="id"/>
        <Mapping element="name" cloverField="name"/>
      </Mapping>
    </Mappings>
  ]]></attr>
</Node>
```

---

### XML Readers: XML_EXTRACT vs XML_READER

CloverDX provides two XML reader components with different parsing strategies:

| | `XML_EXTRACT` (XMLExtract) | `XML_READER` (XMLReader) |
|---|---|---|
| **Parsing model** | SAX (streaming, event-driven) | DOM (loads full document into memory) |
| **Mapping syntax** | CloverDX `<Mappings>` XML — element paths mapped to `cloverField` | XPath expressions on output fields |
| **Memory usage** | Low — processes one record at a time | Higher — entire XML document in RAM |
| **Multi-port output** | Yes — `parentKey`/`generatedKey` to fan-out hierarchies across ports | Yes, via separate XPath queries per port |
| **Best for** | Large files; hierarchical extraction to multiple DB tables; post-processing pipelines | Smaller/medium files with complex structure where XPath is more expressive |

**Use `XML_EXTRACT` when:**
- The source file is large (streaming avoids memory pressure)
- You need to extract parent/child hierarchies into separate output ports (using `parentKey`/`generatedKey` — see the XML→DB example)
- The document structure maps naturally to the CloverDX `<Mappings>` syntax

**Use `XML_READER` when:**
- The file is small to medium in size
- The XML structure is complex or irregular and XPath expressions are clearer than the `<Mappings>` format
- You want to reuse existing XPath knowledge

---

### JSON Readers: JSON_EXTRACT vs JSON_READER

The same SAX vs DOM distinction applies to JSON:

| | `JSON_EXTRACT` (JSONExtract) | `JSON_READER` (JSONReader) |
|---|---|---|
| **Parsing model** | SAX (streaming) | DOM (in-memory) |
| **Mapping syntax** | CloverDX `<Mappings>` XML | XPath / JSONPath expressions |
| **Memory usage** | Low | Higher |
| **Best for** | Large JSON files; hierarchical extraction to multiple ports | Smaller/complex JSON where path expressions are cleaner |

The same selection rule applies as for XML: prefer `JSON_EXTRACT` for large files and multi-port fan-outs; prefer `JSON_READER` for smaller or structurally complex documents where the path-based mapping is more convenient.

---

#### SPREADSHEET_READER (SpreadsheetDataReader)

```xml
<Node enabled="enabled" guiName="SpreadsheetDataReader" guiX="24" guiY="24"
      id="SPREADSHEET_READER0" type="SPREADSHEET_READER">
  <attr name="fileURL"><![CDATA[${DATAIN_DIR}/data.xlsx]]></attr>
  <attr name="sheetName"><![CDATA[Sheet1]]></attr>
  <attr name="startRow"><![CDATA[1]]></attr>   <!-- 0-indexed, skip header -->
</Node>
```

---

#### DATA_GENERATOR (DataGenerator)

Generates synthetic data using CTL transform.

```xml
<Node enabled="enabled" guiName="DataGenerator" guiX="24" guiY="24"
      id="DATA_GENERATOR0" type="DATA_GENERATOR">
  <attr name="recordsNumber"><![CDATA[100]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function integer generate() {
    $out.0.id = nextval("Sequence0");
    $out.0.name = "Record_" + num2str($out.0.id);
    return 0;
}
  ]]></attr>
</Node>
```

---

### WRITERS

#### DATA_WRITER (FlatFileWriter / UniversalDataWriter)

```xml
<Node enabled="enabled" guiName="FlatFileWriter" guiX="300" guiY="24"
      id="DATA_WRITER0" type="DATA_WRITER">
  <attr name="fileURL"><![CDATA[${DATAOUT_DIR}/output.csv]]></attr>
  <attr name="charset"><![CDATA[UTF-8]]></attr>
  <attr name="append"><![CDATA[false]]></attr>
  <!-- Optional: -->
  <attr name="excludeFields"><![CDATA[field_to_exclude]]></attr>
</Node>
```

Key attrs: `fileURL` (required), `charset` (default UTF-8), `append` (`true`/`false`, default false), `excludeFields`.

---

#### DB_OUTPUT_TABLE (DatabaseWriter)

```xml
<Node dbConnection="DBConnection0" enabled="enabled" guiName="DatabaseWriter"
      guiX="300" guiY="24" id="DB_OUTPUT_TABLE0" type="DB_OUTPUT_TABLE">
  <attr name="sqlQuery"><![CDATA[insert into employees (id, name) values ($id:=id, $name:=name)]]></attr>
  <!-- Or use dbTable for auto-mapping by field name: -->
  <!-- <attr name="dbTable"><![CDATA[employees]]></attr> -->
</Node>
```

SQL query mapping syntax: `$cloverField:=dbColumn`. Use `sqlQuery` (inline), `queryURL` (external), or `dbTable` (auto-map by field name). Key attrs: `batchMode`, `batchSize` (default 25), `commit` (default 100).

Ports: Input 0 (data), Output 0 (rejected records, optional), Output 1 (auto-generated keys, optional).

---

#### TRASH (Trash)

Discards all incoming records. 1 input, 0 outputs. No configuration required.

```xml
<Node enabled="enabled" guiName="Trash" guiX="300" guiY="24" id="TRASH0" type="TRASH"/>
```

**TRASH serves two common purposes:**

**1. Satisfying mandatory port connections.** Many components require every output port to be connected. When you don't need the data from an optional/error port, connect it to TRASH. Examples:
- `EXT_FILTER` port 1 (rejected records) — must be connected or left unconnected only if the component allows it
- `DB_OUTPUT_TABLE` port 0 (rejected rows in `controlled` data policy)
- `EXT_HASH_JOIN` port 1 (unmatched master records in left-outer join)
- `DATA_READER` port 1 (parse errors when `dataPolicy="controlled"`)

**2. Iterative / work-in-progress development.** While building a graph incrementally, use TRASH as a temporary terminal for data that has no final destination yet. By default records are silently discarded; set `debugPrint="true"` to print each record to the graph console for quick inspection:

```xml
<Node enabled="enabled" guiName="Trash" guiX="300" guiY="24" id="TRASH0" type="TRASH">
  <attr name="debugPrint"><![CDATA[true]]></attr>
</Node>
```

---

#### JSON_WRITER / XML_WRITER / SPREADSHEET_WRITER

Similar pattern — `fileURL` is the primary required attribute.

```xml
<Node enabled="enabled" guiName="JSONWriter" id="JSON_WRITER0" type="JSON_WRITER">
  <attr name="fileURL"><![CDATA[${DATAOUT_DIR}/output.json]]></attr>
  <attr name="mapping"><![CDATA[
    <Mapping>
      <ObjectMapping outputKeyName="records">
        <ArrayMapping outputKeyName="items" inPort="0">
          <ObjectMapping>
            <Mapping cloverField="id" outputKeyName="id"/>
            <Mapping cloverField="name" outputKeyName="name"/>
          </ObjectMapping>
        </ArrayMapping>
      </ObjectMapping>
    </Mapping>
  ]]></attr>
</Node>
```

---

### TRANSFORMERS

#### REFORMAT (Map / Reformat)

One input, one or more outputs. Transforms records via CTL or Java.

```xml
<Node enabled="enabled" guiName="Map" guiX="150" guiY="24" id="REFORMAT0" type="REFORMAT">
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;                            // copy all matching fields
    $out.0.fullName = $in.0.first + " " + $in.0.last;
    $out.0.upperName = uppercase($in.0.name);
    if ($in.0.salary > 50000) {
        return 0;   // send to port 0
    } else {
        return 1;   // send to port 1
    }
}
  ]]></attr>
</Node>
```

Return `ALL` to send to all ports; return port number to route selectively.

---

#### EXT_FILTER (Filter)

1 input, up to 2 outputs. Port 0 = accepted, Port 1 = rejected.

```xml
<Node enabled="enabled" guiName="Filter" guiX="150" guiY="24" id="EXT_FILTER0" type="EXT_FILTER">
  <attr name="filterExpression"><![CDATA[//#CTL2
$in.0.salary > 30000 && !isNull($in.0.name)]]></attr>
</Node>
```

---

#### EXT_SORT (ExtSort)

Sort key syntax: `field1(a);field2(d)` — `a` = ascending, `d` = descending.

```xml
<Node enabled="enabled" guiName="ExtSort" guiX="150" guiY="24" id="EXT_SORT0" type="EXT_SORT">
  <attr name="sortKey"><![CDATA[lastName(a);firstName(a)]]></attr>
  <attr name="bufferCapacity"><![CDATA[8000]]></attr>
</Node>
```

---

#### FAST_SORT (FastSort)

In-memory sort, faster than ExtSort for datasets fitting in memory.

```xml
<Node enabled="enabled" guiName="FastSort" guiX="150" guiY="24" id="FAST_SORT0" type="FAST_SORT">
  <attr name="sortKey"><![CDATA[date(d);amount(d)]]></attr>
</Node>
```

---

#### AGGREGATE (Aggregate)

Groups and aggregates records.

```xml
<Node enabled="enabled" guiName="Aggregate" guiX="150" guiY="24" id="AGGREGATE0" type="AGGREGATE">
  <attr name="aggregateKey"><![CDATA[department]]></attr>
  <attr name="mapping"><![CDATA[
$out.0.department:=$in.0.department;
$out.0.count:=count($in.0.id);
$out.0.totalSalary:=sum($in.0.salary);
$out.0.avgSalary:=avg($in.0.salary);
$out.0.maxSalary:=max($in.0.salary);
$out.0.minSalary:=min($in.0.salary);
  ]]></attr>
  <attr name="sortedInput"><![CDATA[false]]></attr>
</Node>
```

Aggregate functions: `count()`, `sum()`, `avg()`, `min()`, `max()`, `first()`, `last()`, `countDistinct()`.

---

#### SIMPLE_COPY (SimpleCopy)

Copies each record to ALL connected output ports. 1 input, N outputs.

```xml
<Node enabled="enabled" guiName="SimpleCopy" guiX="150" guiY="24" id="SIMPLE_COPY0" type="SIMPLE_COPY"/>
```

---

#### SIMPLE_GATHER (SimpleGather) / CONCATENATE (Concatenate)

Merges multiple inputs (same metadata) into single output. N inputs, 1 output.

```xml
<Node enabled="enabled" guiName="SimpleGather" guiX="150" guiY="24" id="SIMPLE_GATHER0" type="SIMPLE_GATHER"/>
```

---

#### DEDUP (Dedup)

Removes consecutive duplicate records. Input must be sorted. 1 input, 1-2 outputs.

```xml
<Node enabled="enabled" guiName="Dedup" guiX="150" guiY="24" id="DEDUP0" type="DEDUP">
  <attr name="key"><![CDATA[id]]></attr>
  <attr name="keep"><![CDATA[First]]></attr>  <!-- First | Last | Unique -->
</Node>
```

---

#### PARTITION (Partition)

Routes records to different output ports. 1 input, N outputs.

```xml
<Node enabled="enabled" guiName="Partition" guiX="150" guiY="24" id="PARTITION0" type="PARTITION">
  <!-- Option A: ranges -->
  <attr name="ranges"><![CDATA[<Ranges>
    <Range fromValue="0" toValue="30000" portIndex="0"/>
    <Range fromValue="30000" portIndex="1"/>
  </Ranges>]]></attr>
  <!-- Option B: partition key (hash-based) -->
  <!-- <attr name="partitionKey"><![CDATA[customerId]]></attr> -->
  <!-- Option C: CTL transform returning port number -->
</Node>
```

---

#### NORMALIZER (Normalizer)

One input record → multiple output records. 1 input, 1 output.

```xml
<Node enabled="enabled" guiName="Normalizer" guiX="150" guiY="24" id="NORMALIZER0" type="NORMALIZER">
  <attr name="transform"><![CDATA[
//#CTL2
integer count;
function integer count() {
    count = length($in.0.items);
    return count;
}
function integer transform(integer idx) {
    $out.0.parentId = $in.0.id;
    $out.0.item = $in.0.items[idx];
    return ALL;
}
  ]]></attr>
</Node>
```

---

#### DENORMALIZER (Denormalizer)

Multiple input records → one output record. Requires sorted input. 1 input, 1 output.

```xml
<Node enabled="enabled" guiName="Denormalizer" guiX="150" guiY="24" id="DENORMALIZER0" type="DENORMALIZER">
  <attr name="key"><![CDATA[customerId]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function void append() {
    // called for each input record
    $out.0.customerId = $in.0.customerId;
    $out.0.totalAmount = $out.0.totalAmount + $in.0.amount;
    $out.0.orderCount = $out.0.orderCount + 1;
}
function integer transform() {
    // called once per group at group boundary
    return ALL;
}
  ]]></attr>
</Node>
```

---

#### ROLLUP (Rollup)

Grouped aggregation with full CTL control. 1 input, N outputs.

```xml
<Node enabled="enabled" guiName="Rollup" guiX="150" guiY="24" id="ROLLUP0" type="ROLLUP">
  <attr name="groupKeyFields"><![CDATA[department]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function void initGroup(DataRecord group) {
    // initialize group state
}
function boolean updateGroup(DataRecord group) {
    // called for each record; group = accumulator
    return false;  // return true to send intermediate results
}
function boolean finishGroup(DataRecord group) {
    $out.0.* = group.*;
    return true;  // return true to send this record
}
  ]]></attr>
</Node>
```

---

### JOINERS

All joiners: Port 0 = master (driver), Port 1+ = slave(s).

#### EXT_HASH_JOIN (ExtHashJoin)

General-purpose in-memory join on equality key. Unsorted input.

```xml
<Node enabled="enabled" guiName="ExtHashJoin" guiX="200" guiY="24" id="EXT_HASH_JOIN0" type="EXT_HASH_JOIN">
  <attr name="joinKey"><![CDATA[$0.customerId=$1.id]]></attr>
  <attr name="joinType"><![CDATA[inner]]></attr>   <!-- inner | leftOuter | fullOuter -->
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.customerName = $in.1.name;
    $out.0.city = $in.1.city;
    return ALL;
}
  ]]></attr>
</Node>
```

Join key format: `$masterPort.fieldName=$slavePort.fieldName` — multiple keys separated by `#`.
Multiple slave ports: `$0.id=$1.customerId#$0.type=$1.type`.

---

#### EXT_MERGE_JOIN (ExtMergeJoin)

Join on sorted data. Both master and slave must be pre-sorted on join key.

```xml
<Node enabled="enabled" guiName="ExtMergeJoin" guiX="200" guiY="24" id="EXT_MERGE_JOIN0" type="EXT_MERGE_JOIN">
  <attr name="joinKey"><![CDATA[$0.id=$1.customerId]]></attr>
  <attr name="joinType"><![CDATA[inner]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.name = $in.1.name;
    return ALL;
}
  ]]></attr>
</Node>
```

---

#### LOOKUP_JOIN (LookupJoin)

Join with a lookup table (acts as virtual slave). 1-2 outputs: port 0 = matched, port 1 = unmatched master.

```xml
<Node enabled="enabled" guiName="LookupJoin" guiX="200" guiY="24" id="LOOKUP_JOIN0" type="LOOKUP_JOIN">
  <attr name="joinKey"><![CDATA[customerId]]></attr>
  <attr name="lookupTable"><![CDATA[LookupTable0]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.customerName = $in.1.name;  // $in.1 = lookup table record
    return ALL;
}
  ]]></attr>
</Node>
```

---

#### DB_JOIN (DBJoin)

Join with database table (acts as virtual slave via SQL). 1-2 outputs.

```xml
<Node dbConnection="DBConnection0" enabled="enabled" guiName="DBJoin"
      guiX="200" guiY="24" id="DB_JOIN0" type="DB_JOIN">
  <attr name="sqlQuery"><![CDATA[SELECT name, city FROM customers WHERE id = ?]]></attr>
  <attr name="joinKey"><![CDATA[customerId]]></attr>
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.customerName = $in.1.name;
    return ALL;
}
  ]]></attr>
</Node>
```

---

#### CROSS_JOIN (CrossJoin)

Cartesian product of all inputs. All input combinations → output.

```xml
<Node enabled="enabled" guiName="CrossJoin" guiX="200" guiY="24" id="CROSS_JOIN0" type="CROSS_JOIN">
  <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    $out.0.* = $in.1.*;
    return ALL;
}
  ]]></attr>
</Node>
```

---

### JOB CONTROL

#### EXECUTE_GRAPH (ExecuteGraph)

Runs another graph as a child process.

```xml
<Node enabled="enabled" guiName="ExecuteGraph" guiX="150" guiY="24" id="EXECUTE_GRAPH0" type="EXECUTE_GRAPH">
  <attr name="graphName"><![CDATA[${GRAPH_DIR}/child_graph.grf]]></attr>
  <!-- Optional parameter overrides: -->
  <attr name="params"><![CDATA[PARAM1=value1;PARAM2=value2]]></attr>
</Node>
```

---

#### SUBGRAPH (Subgraph component inside a graph)

```xml
<Node enabled="enabled" guiName="MySubgraph" guiX="150" guiY="24" id="SUBGRAPH0" type="SUBGRAPH">
  <attr name="graphURL"><![CDATA[${SUBGRAPH_DIR}/my-subgraph.sgrf]]></attr>
</Node>
```

---

### OTHERS

#### HTTP_CONNECTOR (HTTPConnector)

```xml
<Node enabled="enabled" guiName="HTTPConnector" guiX="150" guiY="24" id="HTTP_CONNECTOR0" type="HTTP_CONNECTOR">
  <attr name="url"><![CDATA[https://api.example.com/data]]></attr>
  <attr name="method"><![CDATA[GET]]></attr>
  <attr name="outputField"><![CDATA[responseBody]]></attr>
</Node>
```

---

#### DB_EXECUTE (DBExecute)

Executes arbitrary SQL (DDL, stored procedures, etc.) 0-1 input, 0-1 output.

```xml
<Node dbConnection="DBConnection0" enabled="enabled" guiName="DBExecute"
      guiX="150" guiY="24" id="DB_EXECUTE0" type="DB_EXECUTE">
  <attr name="sqlQuery"><![CDATA[TRUNCATE TABLE staging_table]]></attr>
</Node>
```

---

## 10. Complete Example: CSV to DB with Join and Filter

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph description="Read CSV, join with DB lookup, filter, write to DB"
       guiVersion="6.0.0" id="GRAPH1" name="CSVToDBWithJoin">
  <Global>
    <GraphParameters>
      <GraphParameter name="PROJECT" value="."/>
      <GraphParameter name="DATAIN_DIR" value="${PROJECT}/data-in"/>
      <GraphParameter name="CONN_DIR" value="${PROJECT}/conn"/>
    </GraphParameters>
    <Metadata id="OrdersMeta">
      <Record fieldDelimiter=";" name="orders" recordDelimiter="\n" type="delimited">
        <Field name="orderId" type="integer"/>
        <Field name="customerId" type="integer"/>
        <Field name="amount" type="decimal" length="10" scale="2"/>
        <Field name="orderDate" type="date" format="yyyy-MM-dd"/>
      </Record>
    </Metadata>
    <Metadata id="CustomerMeta">
      <Record name="customer" type="delimited" fieldDelimiter="\n">
        <Field name="id" type="integer"/>
        <Field name="name" type="string"/>
        <Field name="tier" type="string"/>
      </Record>
    </Metadata>
    <Metadata id="OutputMeta">
      <Record name="output" type="delimited" fieldDelimiter="\n">
        <Field name="orderId" type="integer"/>
        <Field name="customerName" type="string"/>
        <Field name="amount" type="decimal" length="10" scale="2"/>
        <Field name="tier" type="string"/>
      </Record>
    </Metadata>
    <Connection dbDriver="com.mysql.cj.jdbc.Driver" dbURL="jdbc:mysql://localhost/orders"
                id="CONN0" name="OrdersDB" password="****" type="JDBC" user="app"/>
  </Global>

  <Phase number="0">
    <!-- Read CSV orders -->
    <Node enabled="enabled" guiName="ReadOrders" guiX="24" guiY="50"
          id="DATA_READER0" type="DATA_READER">
      <attr name="fileURL"><![CDATA[${DATAIN_DIR}/orders.csv]]></attr>
      <attr name="skipRows"><![CDATA[1]]></attr>
    </Node>

    <!-- Read customers from DB -->
    <Node dbConnection="CONN0" enabled="enabled" guiName="ReadCustomers"
          guiX="24" guiY="150" id="DB_INPUT_TABLE0" type="DB_INPUT_TABLE">
      <attr name="sqlQuery"><![CDATA[SELECT id, name, tier FROM customers]]></attr>
    </Node>

    <!-- Join orders with customers (hash join, unsorted) -->
    <Node enabled="enabled" guiName="JoinWithCustomers" guiX="250" guiY="80"
          id="EXT_HASH_JOIN0" type="EXT_HASH_JOIN">
      <attr name="joinKey"><![CDATA[$0.customerId=$1.id]]></attr>
      <attr name="joinType"><![CDATA[leftOuter]]></attr>
      <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.orderId = $in.0.orderId;
    $out.0.customerName = iif(isNull($in.1.name), "Unknown", $in.1.name);
    $out.0.amount = $in.0.amount;
    $out.0.tier = iif(isNull($in.1.tier), "standard", $in.1.tier);
    return ALL;
}
      ]]></attr>
    </Node>

    <!-- Filter: only premium tier -->
    <Node enabled="enabled" guiName="FilterPremium" guiX="450" guiY="80"
          id="EXT_FILTER0" type="EXT_FILTER">
      <attr name="filterExpression"><![CDATA[//#CTL2
$in.0.tier == "premium" && $in.0.amount > 100]]></attr>
    </Node>

    <!-- Write to DB -->
    <Node dbConnection="CONN0" enabled="enabled" guiName="WriteToDB"
          guiX="650" guiY="80" id="DB_OUTPUT_TABLE0" type="DB_OUTPUT_TABLE">
      <attr name="sqlQuery"><![CDATA[
insert into premium_orders(order_id, customer_name, amount, tier)
values ($orderId:=order_id, $customerName:=customer_name, $amount:=amount, $tier:=tier)
      ]]></attr>
    </Node>

    <!-- Discard filtered-out records -->
    <Node enabled="enabled" guiName="Trash" guiX="450" guiY="200" id="TRASH0" type="TRASH"/>

    <!-- Edges -->
    <Edge fromNode="DATA_READER0:0" id="E0" metadata="OrdersMeta" toNode="EXT_HASH_JOIN0:0"/>
    <Edge fromNode="DB_INPUT_TABLE0:0" id="E1" metadata="CustomerMeta" toNode="EXT_HASH_JOIN0:1"/>
    <Edge fromNode="EXT_HASH_JOIN0:0" id="E2" metadata="OutputMeta" toNode="EXT_FILTER0:0"/>
    <Edge fromNode="EXT_FILTER0:0" id="E3" metadata="OutputMeta" toNode="DB_OUTPUT_TABLE0:0"/>
    <Edge fromNode="EXT_FILTER0:1" id="E4" metadata="OutputMeta" toNode="TRASH0:0"/>
  </Phase>
</Graph>
```

---

## 11. Example: DB to CSV Export

Reads from a database, transforms/formats fields, writes to a delimited CSV file.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph description="Export employees from DB to CSV" guiVersion="6.0.0"
       id="DB_TO_CSV" name="DBToCSV">
  <Global>
    <GraphParameters>
      <GraphParameter name="PROJECT" value="."/>
      <GraphParameterFile fileURL="workspace.prm"/>
    </GraphParameters>

    <!-- Source metadata (matches DB columns) -->
    <Metadata id="EmployeeDBMeta">
      <Record name="employee_db" type="delimited" fieldDelimiter="\n">
        <Field name="emp_id"      type="integer"/>
        <Field name="first_name"  type="string"/>
        <Field name="last_name"   type="string"/>
        <Field name="salary"      type="decimal" length="12" scale="2"/>
        <Field name="hire_date"   type="date"    format="yyyy-MM-dd"/>
        <Field name="dept_code"   type="string"/>
        <Field name="is_active"   type="boolean"/>
      </Record>
    </Metadata>

    <!-- Output metadata (CSV format with header row) -->
    <Metadata id="EmployeeCSVMeta">
      <Record name="employee_csv" type="delimited" fieldDelimiter="," recordDelimiter="\n"
              charset="UTF-8" locale="en.US">
        <Field name="EmployeeID"   type="integer"  delimiter=","/>
        <Field name="FullName"     type="string"   delimiter=","/>
        <Field name="Salary"       type="string"   delimiter=","/>   <!-- formatted as "$12,345.67" -->
        <Field name="HireDate"     type="string"   delimiter=","/>   <!-- formatted as "dd/MM/yyyy" -->
        <Field name="Department"   type="string"   delimiter=","/>
        <Field name="Status"       type="string"   delimiter="\n"/>  <!-- "Active" / "Inactive" -->
      </Record>
    </Metadata>

    <Connection dbDriver="com.mysql.cj.jdbc.Driver"
                dbURL="jdbc:mysql://dbhost:3306/hr"
                id="HRDB" name="HR Database"
                password="secret" type="JDBC" user="hr_user"/>
  </Global>

  <Phase number="0">
    <!-- Read all active employees from DB -->
    <Node dbConnection="HRDB" enabled="enabled" guiName="ReadEmployees"
          guiX="24" guiY="50" id="DB_INPUT_TABLE0" type="DB_INPUT_TABLE">
      <attr name="sqlQuery"><![CDATA[
SELECT emp_id, first_name, last_name, salary, hire_date, dept_code, is_active
FROM employees
ORDER BY last_name, first_name
      ]]></attr>
    </Node>

    <!-- Transform: format fields for CSV output -->
        <Node enabled="enabled" guiName="FormatForCSV" guiX="250" guiY="50"
          id="REFORMAT0" type="REFORMAT">
      <attr name="transform"><![CDATA[
//#CTL2
function integer transform() {
    $out.0.EmployeeID = $in.0.emp_id;
    $out.0.FullName   = $in.0.first_name + " " + $in.0.last_name;
    // Format salary as currency string
    $out.0.Salary     = "$" + num2str($in.0.salary, "#,##0.00", "en.US");
    // Re-format date from yyyy-MM-dd (DB) to dd/MM/yyyy (CSV)
    $out.0.HireDate   = date2str($in.0.hire_date, "dd/MM/yyyy");
    $out.0.Department = $in.0.dept_code;
    $out.0.Status     = iif($in.0.is_active, "Active", "Inactive");
    return ALL;
}
      ]]></attr>
    </Node>

    <!-- Write CSV with header row -->
    <Node enabled="enabled" guiName="WriteCSV" guiX="480" guiY="50"
          id="DATA_WRITER0" type="DATA_WRITER">
      <attr name="fileURL"><![CDATA[${DATAOUT_DIR}/employees_export.csv]]></attr>
      <attr name="charset"><![CDATA[UTF-8]]></attr>
      <attr name="append"><![CDATA[false]]></attr>
      <!-- Write header row using field names from output metadata -->
      <attr name="printHeader"><![CDATA[true]]></attr>
    </Node>

    <Edge fromNode="DB_INPUT_TABLE0:0" id="E0" metadata="EmployeeDBMeta" toNode="MAP0:0"/>
    <Edge fromNode="MAP0:0"            id="E1" metadata="EmployeeCSVMeta" toNode="DATA_WRITER0:0"/>
  </Phase>
</Graph>
```

---

## 12. Example: XML Hierarchy to DB (Preserving Relationships)

Reads a multi-level XML file, extracts records at each hierarchy level, propagates parent keys to child records, then writes each level to its own database table.

**Sample XML structure:**
```xml
<orders>
  <order orderId="O-001" customerId="C-42" orderDate="2024-03-15">
    <header region="EMEA" priority="high"/>
    <items>
      <item lineNo="1" productCode="P-100" qty="3" unitPrice="29.99"/>
      <item lineNo="2" productCode="P-201" qty="1" unitPrice="149.00"/>
    </items>
  </order>
  <order orderId="O-002" customerId="C-17" orderDate="2024-03-16">
    <header region="APAC" priority="normal"/>
    <items>
      <item lineNo="1" productCode="P-100" qty="2" unitPrice="29.99"/>
    </items>
  </order>
</orders>
```

**Graph:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph description="Parse hierarchical XML and load to DB"
       guiVersion="6.0.0" id="XML_TO_DB" name="XMLHierarchyToDB">
  <Global>
    <GraphParameters>
      <GraphParameter name="PROJECT" value="."/>
      <GraphParameterFile fileURL="workspace.prm"/>
    </GraphParameters>

    <!-- Level 1: order header -->
    <Metadata id="OrderMeta">
      <Record name="order" type="delimited" fieldDelimiter="\n">
        <Field name="orderId"    type="string"/>
        <Field name="customerId" type="string"/>
        <Field name="orderDate"  type="date" format="yyyy-MM-dd"/>
        <Field name="region"     type="string"/>
        <Field name="priority"   type="string"/>
      </Record>
    </Metadata>

    <!-- Level 2: order line items -->
    <!-- generatedKey copies orderId from parent into this record -->
    <Metadata id="ItemMeta">
      <Record name="item" type="delimited" fieldDelimiter="\n">
        <Field name="orderId"     type="string"/>  <!-- FK — copied from parent via generatedKey -->
        <Field name="lineNo"      type="integer"/>
        <Field name="productCode" type="string"/>
        <Field name="qty"         type="integer"/>
        <Field name="unitPrice"   type="decimal" length="10" scale="2"/>
      </Record>
    </Metadata>

    <Connection dbDriver="com.mysql.cj.jdbc.Driver"
                dbURL="jdbc:mysql://dbhost:3306/orders_db"
                id="ORDERSDB" name="Orders DB"
                password="secret" type="JDBC" user="orders_user"/>
  </Global>

  <Phase number="0">
    <!-- XMLExtract: maps hierarchy levels to separate output ports.
         parentKey/generatedKey copy the orderId FK from order level to item level. -->
    <Node enabled="enabled" guiName="ParseXML" guiX="24" guiY="80"
          id="XML_EXTRACT0" type="XML_EXTRACT">
      <attr name="sourceUri"><![CDATA[${DATAIN_DIR}/orders.xml]]></attr>
      <attr name="mapping"><![CDATA[
<Mappings>
  <!-- Top-level order element → port 0 (OrderMeta) -->
  <Mapping element="order" outPort="0"
           xmlFields="orderId;customerId;orderDate"
           cloverFields="orderId;customerId;orderDate">

    <!-- header is a child of order; use useParentRecord to add its fields
         into the same port 0 record (no separate record per header) -->
    <Mapping element="header" useParentRecord="true"
             xmlFields="region;priority"
             cloverFields="region;priority"/>

    <!-- items/item → port 1 (ItemMeta).
         parentKey: field(s) in parent (port 0) record that identify the parent.
         generatedKey: field(s) in child (port 1) record that receive the parent's key values.
         This copies orderId from the order record into each item record. -->
    <Mapping element="items">
      <Mapping element="item" outPort="1"
               parentKey="orderId"
               generatedKey="orderId"
               xmlFields="lineNo;productCode;qty;unitPrice"
               cloverFields="lineNo;productCode;qty;unitPrice"/>
    </Mapping>
  </Mapping>
</Mappings>
      ]]></attr>
    </Node>

    <!-- Write orders table -->
    <Node dbConnection="ORDERSDB" enabled="enabled" guiName="WriteOrders"
          guiX="300" guiY="30" id="DB_OUTPUT_TABLE0" type="DB_OUTPUT_TABLE">
      <attr name="sqlQuery"><![CDATA[
INSERT INTO orders (order_id, customer_id, order_date, region, priority)
VALUES ($orderId:=order_id, $customerId:=customer_id, $orderDate:=order_date,
        $region:=region, $priority:=priority)
      ]]></attr>
    </Node>

    <!-- Write line items table (orderId FK already in record from generatedKey) -->
    <Node dbConnection="ORDERSDB" enabled="enabled" guiName="WriteItems"
          guiX="300" guiY="150" id="DB_OUTPUT_TABLE1" type="DB_OUTPUT_TABLE">
      <attr name="sqlQuery"><![CDATA[
INSERT INTO order_items (order_id, line_no, product_code, qty, unit_price)
VALUES ($orderId:=order_id, $lineNo:=line_no, $productCode:=product_code,
        $qty:=qty, $unitPrice:=unit_price)
      ]]></attr>
    </Node>

    <Edge fromNode="XML_EXTRACT0:0" id="E0" metadata="OrderMeta" toNode="DB_OUTPUT_TABLE0:0"/>
    <Edge fromNode="XML_EXTRACT0:1" id="E1" metadata="ItemMeta"  toNode="DB_OUTPUT_TABLE1:0"/>
  </Phase>
</Graph>
```

**XMLExtract mapping key attributes for parent-child relationships:**

| Attribute | On element | Purpose |
|-----------|-----------|---------|
| `outPort` | child Mapping | Which output port this level's records go to |
| `parentKey` | child Mapping | Field name(s) in the **parent** record holding the parent identifier |
| `generatedKey` | child Mapping | Field name(s) in the **child** record that receive the copied parent identifier |
| `useParentRecord` | nested Mapping | `true` = merge this element's fields into the parent's record (no new record) |
| `xmlFields` | any Mapping | XML attribute/element names to read (semicolon-separated) |
| `cloverFields` | any Mapping | Corresponding CloverDX field names in output metadata |
| `sequenceField` | child Mapping | Field populated with an auto-increment value to uniquely identify multiple children |
| `sequenceId` | child Mapping | Sequence to use for `sequenceField` values |

**Important:** For three levels of nesting (order → section → item), chain parentKey/generatedKey:
- order → section: `parentKey="orderId"` / `generatedKey="orderId"`
- section → item: `parentKey="sectionId"` / `generatedKey="sectionId"` (where sectionId flows from order via its own parentKey/generatedKey pair, or via a `sequenceField`)

---

## 13. Multi-Phase Example

```xml
<!-- Phase 0: truncate target, load lookup -->
<Phase number="0">
  <Node dbConnection="CONN0" guiName="TruncateTarget" id="DB_EXECUTE0" type="DB_EXECUTE">
    <attr name="sqlQuery"><![CDATA[TRUNCATE TABLE target]]></attr>
  </Node>
</Phase>

<!-- Phase 1: process data (runs after phase 0 completes) -->
<Phase number="1">
  <Node guiName="ReadData" id="DATA_READER0" type="DATA_READER">
    <attr name="fileURL"><![CDATA[${DATAIN_DIR}/data.csv]]></attr>
  </Node>
  <Node guiName="WriteData" id="DB_OUTPUT_TABLE0" type="DB_OUTPUT_TABLE">
    <!-- ... -->
  </Node>
  <Edge fromNode="DATA_READER0:0" id="E0" metadata="Meta0" toNode="DB_OUTPUT_TABLE0:0"/>
</Phase>
```

---

## 14. Subgraphs (.sgrf)

A **subgraph** is a reusable, user-defined component with its logic in a separate `.sgrf` file. It appears as a regular component (`SUBGRAPH`) in a parent graph, automatically exposing input/output ports.

### Key facts
- File extension: `.sgrf` (stored in `graph/subgraph/` by convention, `${SUBGRAPH_DIR}`)
- Can be tested standalone (run as a graph)
- Can contain any graph elements: components, phases, connections, lookups, metadata, parameters
- Can be nested (subgraphs within subgraphs)
- Parameters declared as `public="true"` become configurable attributes on the `SUBGRAPH` component
- Parameters declared as `required="true"` are mandatory when the subgraph is used as a component
- **Cannot be called recursively** (no cycles allowed)

### Subgraph design patterns

| Pattern | SubgraphInput connected? | SubgraphOutput connected? | Use case |
|---------|--------------------------|---------------------------|----------|
| Reader | No | Yes | Reads data source, streams records out |
| Writer | Yes | No | Receives records, writes to target |
| Transformer | Yes | Yes | Transforms/enriches/filters data |
| Executor | No | No | Utility; orchestrated via Phases |

### Anatomy

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph guiVersion="6.0.0" id="SUBGRAPH1" name="FilterSubgraph">
  <Global>
    <!-- Public parameters become attributes of the SUBGRAPH component in parent graph -->
    <GraphParameters>
      <GraphParameter label="Filter Expression" name="FILTER_EXPR" public="true"
                      required="true" value="true">
        <SingleType name="string"/>
      </GraphParameter>
      <GraphParameter label="Min Amount" name="MIN_AMOUNT" public="true"
                      required="false" value="0">
        <SingleType name="integer"/>
      </GraphParameter>
    </GraphParameters>
    <Metadata id="Meta0">
      <Record fieldDelimiter=";" name="data" recordDelimiter="\n" type="delimited">
        <Field name="id" type="integer"/>
        <Field name="amount" type="decimal" length="10" scale="2"/>
      </Record>
    </Metadata>
  </Global>

  <Phase number="0">
    <!-- SubgraphInput: defines input ports of the subgraph component.
         Each instance is one input port. inputPortIndex is 0-based. -->
    <Node enabled="enabled" guiName="SubgraphInput0" id="SUBGRAPH_INPUT0"
          type="SUBGRAPH_INPUT">
      <attr name="inputPortIndex"><![CDATA[0]]></attr>
    </Node>

    <!-- Body: transformation logic -->
    <Node enabled="enabled" guiName="Filter" id="EXT_FILTER0" type="EXT_FILTER">
      <attr name="filterExpression"><![CDATA[//#CTL2
${FILTER_EXPR} && $in.0.amount >= ${MIN_AMOUNT}]]></attr>
    </Node>

    <!-- SubgraphOutput: defines output ports of the subgraph component.
         Each instance is one output port. outputPortIndex is 0-based. -->
    <Node enabled="enabled" guiName="SubgraphOutput0" id="SUBGRAPH_OUTPUT0"
          type="SUBGRAPH_OUTPUT">
      <attr name="outputPortIndex"><![CDATA[0]]></attr>
    </Node>

    <!-- Debug input: components feeding SubgraphInput during standalone testing.
         Automatically disabled when used from parent graph. -->
    <Node enabled="enabled" guiName="TestData" id="DATA_GENERATOR0" type="DATA_GENERATOR">
      <attr name="recordsNumber"><![CDATA[10]]></attr>
      <attr name="transform"><![CDATA[//#CTL2
function integer generate() {
    $out.0.id = nextval("Sequence0");
    $out.0.amount = 100.00;
    return 0;
}]]></attr>
    </Node>

    <Edge fromNode="DATA_GENERATOR0:0" id="E_DEBUG" metadata="Meta0" toNode="SUBGRAPH_INPUT0:0"/>
    <Edge fromNode="SUBGRAPH_INPUT0:0" id="E0" metadata="Meta0" toNode="EXT_FILTER0:0"/>
    <Edge fromNode="EXT_FILTER0:0" id="E1" metadata="Meta0" toNode="SUBGRAPH_OUTPUT0:0"/>
  </Phase>
</Graph>
```

### Using a subgraph in a parent graph

```xml
<!-- In parent graph's Phase -->
<Node enabled="enabled" guiName="FilterSubgraph" guiX="200" guiY="50"
      id="SUBGRAPH0" type="SUBGRAPH">
  <!-- graphURL points to the .sgrf file -->
  <attr name="graphURL"><![CDATA[${SUBGRAPH_DIR}/FilterSubgraph.sgrf]]></attr>
  <!-- Public parameters from the subgraph appear as attributes here -->
  <attr name="FILTER_EXPR"><![CDATA[//#CTL2
$in.0.id > 0]]></attr>
  <attr name="MIN_AMOUNT"><![CDATA[500]]></attr>
</Node>
```

### Optional ports

Ports of a subgraph can be marked optional (set in the subgraph designer on the port). Three modes:
- **required** — parent must connect an edge
- **optional: edge receives zero records** — behaves as if connected but no data flows
- **optional: edge is removed** — component inside subgraph behaves as if port is absent

### Multiple SubgraphInput / SubgraphOutput instances

Each `SUBGRAPH_INPUT` node with a different `inputPortIndex` creates an additional input port on the component. Same for `SUBGRAPH_OUTPUT`.

```xml
<!-- Two input ports on the subgraph component -->
<Node id="SUBGRAPH_INPUT0" type="SUBGRAPH_INPUT">
  <attr name="inputPortIndex"><![CDATA[0]]></attr>
</Node>
<Node id="SUBGRAPH_INPUT1" type="SUBGRAPH_INPUT">
  <attr name="inputPortIndex"><![CDATA[1]]></attr>
</Node>
```

### Subgraph vs jobflow

| | Subgraph | Jobflow |
|---|---|---|
| Data exchange | Streams records like a component | Passes status/config params only |
| Execution | Parallel with parent graph components | Sequential step-by-step |
| Use when | ETL data transformation | Orchestration / workflow control |

---

## 15. Key Rules and Constraints

1. **Every edge must have metadata assigned** — `metadata` attribute references a `<Metadata id>`.
2. **Port numbers are 0-indexed.** Edge format: `NODE_ID:portNumber`.
3. **Each `<Node>` and `<Edge>` must have a unique `id`** within the graph.
4. **Phase numbers must be non-decreasing** in a data flow path.
5. **Components in the same phase run in parallel.** Data flows continuously between components in the same phase.
6. **Cross-phase edges** are automatically handled by CloverDX — it inserts buffering as needed. Do not set `edgeType` manually.
7. **CTL2 transform must start with `//#CTL2`**.
8. **All component type strings are ALL_CAPS** (e.g., `DATA_READER`, `EXT_HASH_JOIN`, `MAP`).
9. **Metadata `recordDelimiter`**: use `\n` for Unix, `\r\n` for Windows, `\n` is default.
10. **`guiX`/`guiY`** are optional for execution but required for Designer to render properly.
11. **Parameters use `${PARAM_NAME}` syntax**; valid name chars: `A-Z`, `a-z`, `0-9`, `_` (no leading digit).
12. **External element references** use `fileURL` attribute with path to `.fmt` (metadata), `.cfg` (connection), `.lkp` (lookup), `.seq` (sequence), `.prm` (parameters) files.
13. **workspace.prm** is the standard shared parameter file at the project root — link it in every graph via `<GraphParameterFile fileURL="workspace.prm"/>` inside `<GraphParameters>`.
14. **Subgraphs** (`.sgrf`) use `SUBGRAPH_INPUT` / `SUBGRAPH_OUTPUT` boundary nodes; public graph parameters become configurable attributes on the `SUBGRAPH` component.
15. **Container types** (`list`, `map`) are declared on `<Field>` using `containerType="list"` or `containerType="map"`, where `type` is the element's scalar type (e.g., `type="string" containerType="list"`). In CTL2, typed containers are `list[T]` and `map[K,V]`; `variant` is an untyped dynamic value.

---

## 16. Quick Component Type Reference

| Component Name | `type` attribute | Category |
|---------------|-----------------|----------|
| FlatFileReader / UniversalDataReader | `DATA_READER` | Reader |
| DatabaseReader | `DB_INPUT_TABLE` | Reader |
| JSONReader | `JSON_READER` | Reader |
| JSONExtract | `JSON_EXTRACT` | Reader |
| XMLReader | `XML_READER` | Reader |
| XMLExtract | `XML_EXTRACT` | Reader |
| XMLXPathReader | `XML_XPATH_READER` | Reader |
| SpreadsheetDataReader | `SPREADSHEET_READER` | Reader |
| CloverDataReader | `CLOVER_DATA_READER` | Reader |
| DataGenerator | `DATA_GENERATOR` | Reader |
| ParquetReader | `PARQUET_READER` | Reader |
| KafkaReader | `KAFKA_READER` | Reader |
| MongoDBReader | `MONGODB_READER` | Reader |
| SalesforceReader | `SALESFORCE_READER` | Reader |
| FlatFileWriter / UniversalDataWriter | `DATA_WRITER` | Writer |
| DatabaseWriter | `DB_OUTPUT_TABLE` | Writer |
| JSONWriter | `JSON_WRITER` | Writer |
| XMLWriter | `EXT_XML_WRITER` | Writer |
| SpreadsheetDataWriter | `SPREADSHEET_WRITER` | Writer |
| CloverDataWriter | `CLOVER_DATA_WRITER` | Writer |
| Trash | `TRASH` | Writer |
| ParquetWriter | `PARQUET_WRITER` | Writer |
| KafkaWriter | `KAFKA_WRITER` | Writer |
| MongoDBWriter | `MONGODB_WRITER` | Writer |
| EmailSender | `EMAIL_SENDER` | Writer |
| Map (Reformat) | `REFORMAT` | Transformer |
| Filter | `EXT_FILTER` | Transformer |
| ExtSort | `EXT_SORT` | Transformer |
| FastSort | `FAST_SORT` | Transformer |
| Aggregate | `AGGREGATE` | Transformer |
| SimpleCopy | `SIMPLE_COPY` | Transformer |
| SimpleGather | `SIMPLE_GATHER` | Transformer |
| Concatenate | `CONCATENATE` | Transformer |
| Dedup | `DEDUP` | Transformer |
| Partition | `PARTITION` | Transformer |
| Normalizer | `NORMALIZER` | Transformer |
| Denormalizer | `DENORMALIZER` | Transformer |
| Rollup | `ROLLUP` | Transformer |
| DataIntersection | `DATA_INTERSECTION` | Transformer |
| DataSampler | `DATA_SAMPLER` | Transformer |
| SortWithinGroups | `SORT_WITHIN_GROUPS` | Transformer |
| MetaPivot | `META_PIVOT` | Transformer |
| Pivot | `PIVOT` | Transformer |
| LoadBalancingPartition | `LOAD_BALANCING_PARTITION` | Transformer |
| XSLTransformer | `XSL_TRANSFORMER` | Transformer |

> Note: `MAP` is accepted as an alias, but `REFORMAT` is the canonical component type string.
| ExtHashJoin | `EXT_HASH_JOIN` | Joiner |
| ExtMergeJoin | `EXT_MERGE_JOIN` | Joiner |
| LookupJoin | `LOOKUP_JOIN` | Joiner |
| DBJoin | `DB_JOIN` | Joiner |
| RelationalJoin | `RELATIONAL_JOIN` | Joiner |
| CrossJoin | `CROSS_JOIN` | Joiner |
| Combine | `COMBINE` | Joiner |
| DBExecute | `DB_EXECUTE` | Other |
| HTTPConnector | `HTTP_CONNECTOR` | Other |
| ExecuteGraph | `RUN_GRAPH` | Job Control |
| ExecuteJobflow | `RUN_JOBFLOW` | Job Control |
| Subgraph (component) | `SUBGRAPH` | Job Control |
| SubgraphInput | `SUBGRAPH_INPUT` | Job Control |
| SubgraphOutput | `SUBGRAPH_OUTPUT` | Job Control |
| LookupTableReaderWriter | `LOOKUP_TABLE_READER_WRITER` | Other |
| SystemExecute | `SYS_EXECUTE` | Other |
| JavaExecute | `JAVA_EXECUTE` | Other |
| Sleep | `SLEEP` | Other |
| Sequence Checker | `SEQUENCE_CHECKER` | Other |
| Merge | `MERGE` | Transformer |
| Barrier | `BARRIER` | Transformer |

---

## 17. File URL Formats

```
# Local file
${DATAIN_DIR}/input.csv

# Multiple files (wildcard)
${DATAIN_DIR}/*.csv

# Multiple files (list)
${DATAIN_DIR}/file1.csv;${DATAIN_DIR}/file2.csv

# Remote HTTP
https://example.com/data.csv

# FTP
ftp://user:pass@host/path/file.csv

# ZIP archive
zip:(${DATAIN_DIR}/archive.zip)!path/inside/file.csv

# Port reading (reads data from input edge field)
port:$0.urlField:source      # field contains file URL
port:$0.dataField:discrete   # field contains file content (one record per input)
port:$0.dataField:stream     # field contains file content (stream)

# Dictionary entry
dict:dictionaryEntryName

# Sandbox (CloverDX Server)
sandbox://SandboxCode/path/to/file.csv
```

---

## 18. Project Directory Structure (Standard)

```
project/
├── graph/              # .grf transformation graph files
│   └── subgraph/       # .sgrf subgraph files
├── jobflow/            # .jbf jobflow files
├── data-in/            # input data files
├── data-out/           # output data files
├── data-tmp/           # temporary / staging data files
├── meta/               # .fmt external metadata files
├── conn/               # .cfg external connection files
├── lookup/             # .lkp external lookup table files
├── seq/                # .seq external sequence files
├── trans/              # CTL2 / Java transformation source files
├── lib/                # JAR library files
└── workspace.prm       # shared project parameters file (linked by all graphs)
```

Standard parameters (from `workspace.prm`):

| Parameter | Default value | Description |
|-----------|--------------|-------------|
| `PROJECT` | `.` | Project root directory |
| `DATAIN_DIR` | `${PROJECT}/data-in` | Input data directory |
| `DATAOUT_DIR` | `${PROJECT}/data-out` | Output data directory |
| `DATATMP_DIR` | `${PROJECT}/data-tmp` | Temp data directory |
| `META_DIR` | `${PROJECT}/meta` | External metadata files |
| `CONN_DIR` | `${PROJECT}/conn` | External connection files |
| `GRAPH_DIR` | `${PROJECT}/graph` | Graph files |
| `SUBGRAPH_DIR` | `${PROJECT}/graph/subgraph` | Subgraph files |
| `JOBFLOW_DIR` | `${PROJECT}/jobflow` | Jobflow files |
| `SEQ_DIR` | `${PROJECT}/seq` | Sequence files |
| `LOOKUP_DIR` | `${PROJECT}/lookup` | Lookup table files |
| `TRANS_DIR` | `${PROJECT}/trans` | Transformation source files |
| `LIB_DIR` | `${PROJECT}/lib` | Library JARs |

---

## 19. External Graph Elements

Graph elements (metadata, connections, lookup tables, sequences, parameters) can be **internal** (embedded in the graph XML) or **external** (stored in a separate file and referenced by `fileURL`).

External elements are shared across graphs — changing the file updates all graphs that reference it. Graph XML holds only a `fileURL` reference; the actual definition lives in the external file.

### External element reference XML patterns

```xml
<!-- External metadata (.fmt file) -->
<Metadata fileURL="${META_DIR}/employees.fmt" id="EmployeesMeta"/>

<!-- External connection (.cfg file) -->
<Connection fileURL="${CONN_DIR}/production_db.cfg" id="ProdDB"/>

<!-- External lookup table (.lkp file) -->
<LookupTable fileURL="${LOOKUP_DIR}/country_codes.lkp" id="CountryLookup"/>

<!-- External sequence (.seq file) -->
<Sequence fileURL="${SEQ_DIR}/order_seq.seq" id="OrderSeq"/>

<!-- External parameters (.prm file) — use GraphParameterFile, not GraphParameter -->
<GraphParameters>
  <GraphParameter name="PROJECT" value="."/>
  <GraphParameterFile fileURL="workspace.prm"/>          <!-- links all params from file -->
  <GraphParameter name="MY_LOCAL_PARAM" value="value"/>  <!-- local override -->
</GraphParameters>
```

### External file formats and extensions

| Element type | Extension | Description |
|-------------|-----------|-------------|
| Metadata | `.fmt` | Contains `<Record>` XML defining field structure |
| Connection | `.cfg` | Contains `<Connection>` XML with DB URL, driver, credentials |
| Lookup table | `.lkp` | Contains `<LookupTable>` XML |
| Sequence | `.seq` | Contains `<Sequence>` XML |
| Parameters | `.prm` | Contains `<GraphParameters>` XML |
| CTL2 transform | `.ctl` | Referenced via `transformURL` attribute on components |
| SQL query | `.sql` | Referenced via `queryURL` attribute on DB components |

### External metadata file example (`employees.fmt`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Record fieldDelimiter=";" name="employees" recordDelimiter="\n" type="delimited"
        charset="UTF-8" locale="en.US">
  <Field name="id" type="integer" delimiter=";"/>
  <Field name="firstName" type="string" delimiter=";"/>
  <Field name="lastName" type="string" delimiter=";"/>
  <Field name="salary" type="decimal" length="12" scale="2" delimiter=";"/>
  <Field name="hireDate" type="date" format="yyyy-MM-dd" delimiter="\n"/>
</Record>
```

### External connection file example (`mydb.cfg`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Connection dbDriver="com.mysql.cj.jdbc.Driver"
            dbURL="jdbc:mysql://dbhost:3306/mydb"
            id="MyDB"
            name="Production MySQL"
            password="encrypted_or_plain"
            type="JDBC"
            user="app_user"/>
```

### External transform file (`.ctl`) referenced via `transformURL`

```xml
<Node type="MAP" id="MAP0">
  <!-- Instead of inline transform, reference an external CTL file -->
  <attr name="transformURL"><![CDATA[${TRANS_DIR}/enrich_employee.ctl]]></attr>
</Node>
```

### Internal vs external: XML comparison

```xml
<!-- INTERNAL: metadata embedded in graph -->
<Metadata id="EmpMeta">
  <Record ...><Field .../></Record>
</Metadata>

<!-- EXTERNAL: only a reference in graph, actual definition in .fmt file -->
<Metadata fileURL="${META_DIR}/employees.fmt" id="EmpMeta"/>
```

Both forms produce `id="EmpMeta"` that edges can reference with `metadata="EmpMeta"`.

---

## 20. workspace.prm

`workspace.prm` is the standard shared parameter file at the project root, linked by nearly every graph. It centralises all standard directory path parameters so they can be changed in one place.

### Standard workspace.prm content

```xml
<?xml version="1.0" encoding="UTF-8"?>
<GraphParameters>
  <GraphParameter name="PROJECT" value=".">
    <attr name="description">Project root path</attr>
  </GraphParameter>
  <GraphParameter name="CONN_DIR" value="${PROJECT}/conn">
    <attr name="description">Default folder for external connections</attr>
  </GraphParameter>
  <GraphParameter name="DATAIN_DIR" value="${PROJECT}/data-in">
    <attr name="description">Default folder for input data files</attr>
  </GraphParameter>
  <GraphParameter name="DATAOUT_DIR" value="${PROJECT}/data-out">
    <attr name="description">Default folder for output data files</attr>
  </GraphParameter>
  <GraphParameter name="DATATMP_DIR" value="${PROJECT}/data-tmp">
    <attr name="description">Default folder for temporary data files</attr>
  </GraphParameter>
  <GraphParameter name="GRAPH_DIR" value="${PROJECT}/graph">
    <attr name="description">Default folder for transformation graphs</attr>
  </GraphParameter>
  <GraphParameter name="SUBGRAPH_DIR" value="${PROJECT}/graph/subgraph">
    <attr name="description">Default folder for subgraphs</attr>
  </GraphParameter>
  <GraphParameter name="JOBFLOW_DIR" value="${PROJECT}/jobflow">
    <attr name="description">Default folder for jobflows</attr>
  </GraphParameter>
  <GraphParameter name="META_DIR" value="${PROJECT}/meta">
    <attr name="description">Default folder for metadata files</attr>
  </GraphParameter>
  <GraphParameter name="SEQ_DIR" value="${PROJECT}/seq">
    <attr name="description">Default folder for sequence files</attr>
  </GraphParameter>
  <GraphParameter name="LOOKUP_DIR" value="${PROJECT}/lookup">
    <attr name="description">Default folder for lookup table files</attr>
  </GraphParameter>
  <GraphParameter name="LIB_DIR" value="${PROJECT}/lib">
    <attr name="description">Default folder for library JARs</attr>
  </GraphParameter>
  <GraphParameter name="TRANS_DIR" value="${PROJECT}/trans">
    <attr name="description">Default folder for CTL/Java transformation files</attr>
  </GraphParameter>
</GraphParameters>
```

### How workspace.prm is referenced in a graph

```xml
<GraphParameters>
  <GraphParameter name="PROJECT" value="."/>
  <!-- GraphParameterFile links workspace.prm — imports all parameters defined in it -->
  <GraphParameterFile fileURL="workspace.prm"/>
  <!-- Graph-local parameters can override workspace.prm values -->
  <GraphParameter name="DATAIN_DIR" value="/override/input/path"/>
</GraphParameters>
```

**Always link workspace.prm** — if it is missing or unlinked, all `${DATAIN_DIR}`, `${CONN_DIR}`, etc. references will be unresolved. `PROJECT` defaults to `.` (project root); on CloverDX Server it resolves to the sandbox root.

---

## 21. CTL2 Data Types (vs Metadata Types)

| Metadata type | CTL2 type | Notes |
|---------------|-----------|-------|
| `string` | `string` | |
| `integer` | `integer` | |
| `long` | `long` | |
| `number` | `number` | 64-bit double |
| `decimal` | `decimal` | |
| `date` | `date` | |
| `boolean` | `boolean` | |
| `byte` | `byte` | byte array |
| `cbyte` | `cbyte` | compressed byte array |
| `variant` | `object` / any | |
| (list field) | `list[type]` | e.g., `list[string]` |
| (map field) | `map[string, type]` | |

CTL2 also supports: `void`, `null` literal, `integer[]`, `string[]` (arrays).

---

## 22. LLM Guidelines for Generating CloverDX Transformation Graphs

Follow these rules whenever you are tasked with generating a CloverDX graph XML file.

### Before generating — analysis checklist

1. **Identify sources and targets.** For each source, choose the correct reader type (`DATA_READER` for CSV/flat files, `DB_INPUT_TABLE` for JDBC, `JSON_READER` for JSON, `XML_EXTRACT` for XML, etc.). For each target, choose the correct writer.
2. **Map the data flow.** Draw the logical path: source → transform/join/filter steps → target. Each step is one or more `<Node>` elements connected by `<Edge>` elements.
3. **Determine metadata.** Every edge needs metadata. Define `<Metadata>` elements that match the field names and types at each stage of the flow. If an operation changes the record structure (join adds fields, map renames fields), define a new metadata.
4. **Identify joins.** If data from multiple sources must be combined, decide on join type: `EXT_HASH_JOIN` (unsorted, general), `EXT_MERGE_JOIN` (sorted inputs), `LOOKUP_JOIN` (one side is a lookup table), `DB_JOIN` (one side is a DB query).
5. **Decide on phases.** Operations that must complete before others start (e.g., truncate before insert, load lookup before join) go in earlier phases. Components that can run concurrently go in the same phase.
6. **Plan parameters.** Use `${PARAM_NAME}` for all file paths and configurable values. Always link `workspace.prm`.

### XML generation rules — mandatory

- **Always declare `<?xml version="1.0" encoding="UTF-8"?>`** as the first line.
- **Every `<Node>` must have**: `id` (unique, ALLCAPS_N convention), `type` (exact type string), `enabled="enabled"`, `guiName` (human label), `guiX`, `guiY` (layout coords).
- **Every `<Edge>` must have**: `id`, `fromNode` (`NODEID:portNum`), `toNode` (`NODEID:portNum`), `metadata` (references a `<Metadata id>`). Port numbers are 0-based.
- **Wrap all component attribute values in CDATA**: `<attr name="sqlQuery"><![CDATA[SELECT ...]]></attr>`
- **Every metadata `<Record>` must have**: `name`, `type` (`delimited`/`fixed`/`mixed`), and either `fieldDelimiter`+`recordDelimiter` (delimited) or `size` on each field (fixed).
- **Every metadata `<Field>` must have**: `name`, `type`. Add `delimiter` for the last field = record delimiter (e.g., `\n`).
- **CTL2 transforms must start with `//#CTL2`** on the first line inside the CDATA block.
- **Always link `workspace.prm`** using `<GraphParameterFile fileURL="workspace.prm"/>` inside `<GraphParameters>`, and always include `<GraphParameter name="PROJECT" value="."/>`. Note: `<GraphParameterFile>` is a **different element** from `<GraphParameter>` — do not confuse them.
- **Use parameterised paths**: `${DATAIN_DIR}/file.csv` not hardcoded `/data/input/file.csv`.

### Common mistakes to avoid

| Mistake | Correct approach |
|---------|-----------------|
| Using `MAP` as the component type string | `REFORMAT` is canonical; `MAP` is an alias accepted by CloverDX but not the authoritative type |
| Using `<GraphParameter fileURL="..."/>` to link workspace.prm | The correct element is `<GraphParameterFile fileURL="workspace.prm"/>`. `<GraphParameter>` with a `fileURL` attribute (and no `name`) causes "empty graph parameter name" deserialisation failure |
| Bare `<GraphParameter/>` or `<GraphParameter name="" .../>` | Every `<GraphParameter>` must have `name` + `value` attributes. An element with no attributes or an empty name causes "empty graph parameter name" deserialisation failure |
| Edge references non-existent metadata id | Define `<Metadata id="X">` in `<Global>` before referencing `metadata="X"` on edge |
| CTL2 missing `//#CTL2` header | First line of every CTL block must be `//#CTL2` |
| Wrong join port assignment | Joiner port 0 = master (driver), port 1+ = slave. joinKey: `$0.field=$1.field` |
| Missing CDATA wrapper on attribute containing special chars | Always use `<attr name="x"><![CDATA[...]]></attr>` |
| Two nodes at same phase sharing a dependency | If B must wait for A to finish, put A in phase N and B in phase N+1 |
| Same metadata id declared twice | Each `<Metadata id>` must be unique in `<Global>` |
| Manually setting `edgeType` on edges | Do not set `edgeType` — CloverDX automatically determines the optimal edge type (DIRECT, BUFFERED, etc.) when it loads and analyses the graph |
| Forgetting to handle the error/rejected port | Connect `DATA_READER:1` (rejected records in controlled mode) to `TRASH` or error logger |
| `DATA_WRITER` with no output metadata defined | Metadata on the edge going into `DATA_WRITER` defines the columns written |
| `DB_OUTPUT_TABLE` sqlQuery field mapping wrong direction | `$cloverField:=dbColumn` — CloverDX field on the left, DB column on the right |
| Aggregate without input sorted | `AGGREGATE` with `sortedInput="false"` (default) sorts internally; for large data set `sortedInput="true"` and pre-sort with `EXT_SORT` |
| `EXT_MERGE_JOIN` with unsorted input | Both master and slave edges must be sorted on the join key fields; add `EXT_SORT` before the join |
| Subgraph without SubgraphInput/SubgraphOutput | Every `.sgrf` file must have exactly one `SUBGRAPH_INPUT` and one `SUBGRAPH_OUTPUT` node |
| Using hardcoded DB credentials in graph XML | Put password in a connection `.cfg` file referenced by `fileURL`, or use a secure parameter |

### CTL2 code guidelines

- **Always set required output fields explicitly.** Do not rely on implicit field copying unless you use `$out.0.* = $in.0.*` wildcard.
- **Handle nulls explicitly.** Use `isNull($in.0.field)` before using a field value that may be null. Use `iif(isNull($in.0.f), default, $in.0.f)`.
- **return ALL** sends the record to all connected output ports. **return 0** / **return 1** routes to a specific port. **return SKIP** discards the record.
- **Date fields**: always specify format in metadata. For CTL conversion: `str2date(s, "yyyy-MM-dd")`, `date2str(d, "dd/MM/yyyy")`.
- **Decimal formatting**: use `num2str(n, "#,##0.00", "en.US")` for locale-aware formatting.

### Metadata design guidelines

- Define **one metadata per distinct record structure**. Reuse the same metadata id on multiple edges carrying the same structure.
- For join output, define a **new metadata** that combines fields from master and slave.
- For filter/sort/dedup that don't change field structure, **reuse the input metadata** on both input and output edges.
- For container fields (`containerType="list"` or `containerType="map"`): the `type` attribute specifies the element's scalar type (e.g., `type="string"` for a list of strings). Add a comment documenting the CTL2 type (e.g., `list[string]`, `map[string, integer]`) for clarity.
- Use **`decimal`** (not `number`) for monetary amounts. Set `length` and `scale` explicitly.
- Use **`date`** (not `string`) for dates. Always set `format` attribute.

### Phase design guidelines

- **Phase 0**: read-only operations, truncate/prepare targets, load lookup tables.
- **Phase 1+**: write operations that depend on phase 0 completion.
- Components in the same phase must form a DAG (directed acyclic graph) — no cycles.
- A component belongs to exactly one phase. Use the `phase` attribute on `<Node>` or wrap in the correct `<Phase number="N">` block. (Both styles are valid, but inner `<Phase>` is conventional.)
- Edges between phases do not need `edgeType` set — CloverDX automatically determines and applies buffering when it loads the graph.

### Quick type-to-component selection guide

| Task | Use |
|------|-----|
| Read CSV / TSV / fixed-width file | `DATA_READER` |
| Read from any JDBC database | `DB_INPUT_TABLE` |
| Read JSON | `JSON_READER` |
| Read hierarchical XML | `XML_EXTRACT` |
| Read Excel (XLS/XLSX) | `SPREADSHEET_READER` |
| Write CSV / flat file | `DATA_WRITER` |
| Write to JDBC database | `DB_OUTPUT_TABLE` |
| Write JSON | `JSON_WRITER` |
| Write XML | `EXT_XML_WRITER` |
| Write Excel | `SPREADSHEET_WRITER` |
| Field mapping / transformation | `REFORMAT` |
| Filter records | `EXT_FILTER` |
| Join two streams (no sort needed) | `EXT_HASH_JOIN` |
| Join two sorted streams | `EXT_MERGE_JOIN` |
| Join with a static lookup table | `LOOKUP_JOIN` |
| Join with DB query per record | `DB_JOIN` |
| Sort records | `EXT_SORT` (disk) or `FAST_SORT` (memory) |
| Group + aggregate | `AGGREGATE` |
| Flatten 1-to-many (1 in → N out) | `NORMALIZER` |
| Consolidate N-to-1 (N in → 1 out) | `DENORMALIZER` |
| Duplicate stream to N outputs | `SIMPLE_COPY` |
| Merge N streams to 1 | `SIMPLE_GATHER` or `CONCATENATE` |
| Route records by value | `PARTITION` or `EXT_FILTER` |
| Remove consecutive duplicates | `DEDUP` (sort first!) |
| Execute SQL (DDL, stored proc) | `DB_EXECUTE` |
| Run another graph | `EXECUTE_GRAPH` |
| Discard records | `TRASH` |
| Generate test data | `DATA_GENERATOR` |
