# CloverDX Database Connections — LLM Generation Reference

> Graph-level asset in `<Global>`, not a component. Components reference it via `dbConnection="<id>"`.

---

## CONNECTION MODES

| Mode | Use when |
|---|---|
| **External `.cfg`** (`dbConfig="${CONN_DIR}/X.cfg"`) | Default for any reused or environment-varying connection. |
| **Inline** (all attrs on `<Connection>`) | Single-use throwaway graphs only. Never for production. |
| **Parameter-driven** (`dbConfig="${DB_CONNECTION}"`) | Same graph, different DB per environment — swap `.cfg` via param. |
| **JNDI** | **Preferred on Server (production).** Credentials and pool live in Tomcat, not in sandbox. Ops rotates without touching graphs. |
| **MongoDB** (`type="MONGODB"`) | MongoDB only — separate type, separate components. See MongoDB section. |

Designer/dev → external `.cfg` + secure params. Server/prod → JNDI.

---

## SKELETONS

**External (dominant pattern):**
```xml
<Connection dbConfig="${CONN_DIR}/TrainingDB.cfg" id="JDBC0" type="JDBC"/>
```

**Parameter-driven path:**
```xml
<Connection dbConfig="${DB_CONNECTION}" id="JDBC0" type="JDBC"/>
```

**Inline — PostgreSQL:**
```xml
<Connection type="JDBC" id="JDBC0" name="NewConnection"
  database="POSTGRE" jdbcSpecific="POSTGRE"
  dbURL="jdbc:postgresql://server/northwind"
  user="clover" password="${DB_PASSWORD}"/>
```

**Inline — SQLite (no credentials):**
```xml
<Connection type="JDBC" id="JDBC0" name="NewConnection"
  database="SQLITE" jdbcSpecific="SQLITE"
  dbURL="jdbc:sqlite:${DB_SQLITE_FILE}"/>
```

**JNDI (inline):**
```xml
<Connection type="JNDI" id="JDBC0" name="DWHProduction"
  jndiName="java:comp/env/jdbc/DWH" jdbcSpecific="POSTGRE"/>
```

**JNDI (external `.cfg`):**
```
type=JNDI
name=DWHProduction
jndiName=java\:comp/env/jdbc/DWH
jdbcSpecific=POSTGRE
```
```xml
<Connection dbConfig="${CONN_DIR}/DWHProduction.cfg" id="JDBC0" type="JNDI"/>
```

**MongoDB:**
```xml
<Connection dbConfig="${CONN_DIR}/MongoDBDemo.cfg" id="MONGO0" type="MONGODB"/>
```

---

## `<Connection>` XML ATTRIBUTES

| Attribute | Mode | Req | Description |
|---|---|---|---|
| `type` | all | yes | `JDBC` (relational), `JNDI`, `MONGODB`, `JMS`. |
| `id` | all | yes | Referenced by `dbConnection` on components. Convention: `JDBC0`, `JDBC1`. |
| `dbConfig` | external | yes | Path to `.cfg`. Use `${CONN_DIR}/...`. |
| `name` | inline | yes | Display label only. |
| `database` | inline JDBC | yes | Driver code — see table below. Usually same as `jdbcSpecific`. |
| `jdbcSpecific` | inline JDBC + JNDI | yes | SQL dialect — controls quoting, semicolons, isolation defaults. Must match driver. |
| `dbURL` | inline JDBC | yes | JDBC URL — driver-specific format. |
| `user` / `password` | inline JDBC | no | Omit for file-based DBs. Use `${PARAM}` for password. |
| `driverLibrary` | inline JDBC | no | Semicolon-separated JAR paths for non-bundled drivers. |
| `jndiName` | JNDI | yes | Full JNDI path. Typical: `java:comp/env/jdbc/<n>`. |

---

## SUPPORTED DATABASES

| Code (`database` + `jdbcSpecific`) | JDBC URL pattern |
|---|---|
| `POSTGRE` | `jdbc:postgresql://host[:5432]/dbname` |
| `MYSQL` | `jdbc:mysql://host[:3306]/dbname` |
| `ORACLE` | `jdbc:oracle:thin:@host:1521:SID` |
| `MSSQL` | `jdbc:sqlserver://host:1433;databaseName=dbname` — encryption enforced since 6.4 |
| `MSSQL_LEGACY` | jTDS driver — deprecated, use `MSSQL` |
| `SQLITE` | `jdbc:sqlite:/path/to/file.db` — no credentials |
| `DERBY` | `jdbc:derby://host:1527/dbname` (remote) |
| `REDSHIFT` | `jdbc:redshift://host:5439/dbname` |
| `SNOWFLAKE` | `jdbc:snowflake://account.region.snowflakecomputing.com/?db=...` — key-pair auth required |
| `SYBASE` / `VERTICA` | — |
| `GENERIC` | Custom JAR via `driverLibrary` |

---

## `.cfg` FILE FORMAT

Java Properties format. Colons and special chars in values must be backslash-escaped.

**PostgreSQL (`BasicFeatures/conn/TrainingDB.cfg`):**
```
password=clover
database=POSTGRE
name=TrainingDB
jdbcSpecific=POSTGRE
user=clover
dbURL=jdbc\:postgresql\://localhost/basic_features
```

**SQLite with param in URL (`DWHExample/conn/DWHConnection.cfg`):**
```
user=
password=
database=SQLITE
jdbcSpecific=SQLITE
name=NewConnection
dbURL=jdbc\:sqlite\:${DB_SQLITE_FILE}
```

**Escaping (hand-edits only — Designer writes these automatically):**

| Char | In `.cfg` |
|---|---|
| `:` | `\:` |
| `=` | `\=` |
| `!` | `\!` |
| `#` | `\#` |
| `\` | `\\` |

---

## HOW COMPONENTS REFERENCE A CONNECTION

`dbConnection="<id>"` on any DB component. Value must exactly match the `<Connection>` id.

```xml
<Node type="DB_EXECUTE"      dbConnection="JDBC0" .../>
<Node type="DB_INPUT_TABLE"  dbConnection="JDBC0" .../>
<Node type="DB_OUTPUT_TABLE" dbConnection="JDBC0" dbTable="customers" batchMode="true" .../>
```

| Component | Purpose |
|---|---|
| `DB_INPUT_TABLE` | SQL query → records |
| `DB_OUTPUT_TABLE` | Records → insert/upsert into table |
| `DB_EXECUTE` | DDL, procedures, arbitrary SQL |
| `LOOKUP_TABLE` (type `dbLookup`) | Lookup from DB table |
| Bulk writers (`ORACLE_DATA_WRITER`, `POSTGRESQL_DATA_WRITER`, `SNOWFLAKE_BULK_WRITER`, …) | High-throughput load; needs DB client on host |

Components referencing the same connection share config; each gets its own physical connection per thread (`threadSafeConnections=true` default).

---

## JNDI (Server-preferred mode)

CloverDX Server runs as a Tomcat webapp. Tomcat manages the connection pool (`javax.sql.DataSource`) via a JNDI resource. Graphs reference only the logical name — credentials and pool config never enter sandbox files.

**Tomcat `server.xml` / `context.xml`:**
```xml
<Resource
  name="jdbc/DWH"
  auth="Container"
  type="javax.sql.DataSource"
  factory="org.apache.tomcat.jdbc.pool.DataSourceFactory"
  driverClassName="org.postgresql.Driver"
  url="jdbc:postgresql://dwh-prod.internal:5432/analytics"
  username="cloverdx_app"
  password="${dwh.password}"
  maxActive="20"
  maxIdle="5"
  maxWait="10000"
  validationQuery="SELECT 1"
  testOnBorrow="true"/>
```

Resource naming: `jdbc/<n>` convention. Define globally in `<GlobalNamingResources>` + `<ResourceLink>`, or per-app in `context.xml`.

**Graph `<Connection>`:**
```xml
<Connection type="JNDI" id="JDBC0" jndiName="java:comp/env/jdbc/DWH" jdbcSpecific="POSTGRE"/>
```

`jdbcSpecific` required even for JNDI — CloverDX needs it for dialect behaviour (no access to the actual JDBC URL from Tomcat's pool).

Components use `dbConnection="JDBC0"` identically regardless of JDBC vs JNDI. A graph designed against a `.cfg` connection in Designer runs unchanged against JNDI on Server — only the `<Connection>` element or `.cfg` changes.

**Pool sizing:** Each graph execution borrows connections on first component use, returns on graph end. Set Tomcat's `maxActive` ≥ expected concurrent graphs × DB components per graph.

**Designer validation:** Does not work against JNDI. Test on Server with a minimal DB_EXECUTE graph.

---

## MONGODB CONNECTIONS

MongoDB is not JDBC. `type="MONGODB"` connections use a different attribute set and can only be used by MongoDB-specific components (`MONGODB_READER`, `MONGODB_WRITER`, `MONGODB_EXECUTE`). SQL components (`DB_INPUT_TABLE`, `DB_OUTPUT_TABLE`, `DB_EXECUTE`) will fail config check if pointed at a MongoDB connection, and vice versa.

**`.cfg` (`BasicFeatures/conn/MongoDBDemo.cfg`):**
```
type=MONGODB
name=MongoDBDemo
host=db-mongo
instance=sedemo
username=clover
password=Clover\!23
authenticationDatabase=admin
```

**Graph reference:**
```xml
<Connection dbConfig="${CONN_DIR}/MongoDBDemo.cfg" id="MONGO0" type="MONGODB"/>
```

Use a distinct id (`MONGO0`) when coexisting with JDBC connections in the same graph.

---

## ADVANCED PROPERTIES

### Thread-Safe Connection

Default: `true`. Each calling thread gets its own physical `java.sql.Connection` instance. This is correct for all normal graph execution where multiple components hit the same DB in the same phase — without it they would race on the shared connection.

**Disable only when:** you need manual commit/rollback control across a phase boundary using a `DB_EXECUTE` with `inTransaction=never` in phase N and an explicit `COMMIT`/`ROLLBACK` statement in a later phase. In that pattern, both components must share the same connection object — which requires `threadSafeConnections=false`. This is rare; the default is correct for virtually all other cases.

### Transaction Isolation

Controls what a transaction can see from other concurrent transactions. Map to JDBC constant integers:

| Value | Name | Prevents | Default for |
|---|---|---|---|
| `0` | TRANSACTION_NONE | — | — |
| `1` | READ_UNCOMMITTED | nothing | MySQL, PostgreSQL, MSSQL, SQLite |
| `2` | READ_COMMITTED | dirty reads | Oracle, Vertica, Sybase |
| `4` | REPEATABLE_READ | dirty + non-repeatable reads | — |
| `8` | SERIALIZABLE | dirty + non-repeatable + phantom reads | — |

**Practical guidance:** Leave at the database default (`1` or `2`) unless you have a specific concurrency problem. Raising isolation level (toward `8`) reduces anomalies but increases lock contention and deadlock risk — relevant when a graph reads and writes the same table concurrently, or when it must see a consistent snapshot across multiple queries. For bulk ETL loads (read source, write target) the default is almost always sufficient.

### Holdability

Controls whether database cursors (`ResultSet` objects) survive a `commit()` call.

| Value | Name | Behaviour | Default for |
|---|---|---|---|
| `1` | HOLD_CURSORS_OVER_COMMIT | Cursors stay open after commit | Informix, MSSQL 2008+ |
| `2` | CLOSE_CURSORS_AT_COMMIT | Cursors closed on commit | PostgreSQL, MySQL, Oracle, SQLite, Vertica, Sybase |

**Practical guidance:** Rarely needs changing. Relevant only when a graph streams a large result set (open cursor) while also committing intermediate writes within the same connection — i.e. `threadSafeConnections=false` + incremental commits. If you hit `ResultSet closed` errors mid-stream after a commit, switch to `HOLD_CURSORS_OVER_COMMIT` (`1`). Otherwise leave at the database default.

Custom JDBC properties in `.cfg` (example — Snowflake key-pair):
```
jdbcProperties.private_key_file=/secure/keys/snowflake_rsa.p8
jdbcProperties.private_key_file_pwd=${KEY_PASSWORD}
```

---

## GENERATION RULES

- `<Connection>` must be in `<Global>`, not inside a `<Phase>`.
- `id` must be unique; `dbConnection` on components must exactly match it.
- External mode: only `dbConfig`, `id`, `type` required.
- Inline mode: `database` and `jdbcSpecific` are almost always the same value; both required.
- Password: always `${PARAM}` with `secure="true"` parameter — never literal.
- JNDI: `jdbcSpecific` required even though URL is in Tomcat.
- MongoDB: `type="MONGODB"` + MongoDB components only — never mix with JDBC components.
- Do not combine `dbConfig` and inline attrs (`dbURL`, `user`) on the same `<Connection>`.

---

## COMMON MISTAKES

| Mistake | Fix |
|---|---|
| `dbConnection` doesn't match any `<Connection>` id | Case-sensitive exact match required |
| Unescaped colons in hand-written `.cfg` | `jdbc\:postgresql\://...` |
| Literal password in `.cfg` | `password=${DB_PASSWORD}` with secure parameter |
| Duplicate `id` on two `<Connection>` elements | Each needs a unique id |
| Mixed `dbConfig` + inline attrs on same element | Use one mode only |
| `<Connection>` inside `<Phase>` | Must be in `<Global>` |
| Missing `jdbcSpecific` on custom-driver inline connection | Use `jdbcSpecific="GENERIC"` |
| `MSSQL_LEGACY` for SQL Server 2008+ | Use `MSSQL` |
| Snowflake `password=` in `.cfg` | Key-pair auth via `jdbcProperties.private_key_file` |
| Absolute path in `dbConfig` | Use `${CONN_DIR}/...` |
| MongoDB connection with `type="JDBC"` | `type="MONGODB"` + MongoDB components |
| SQL components against MongoDB connection | Use MONGODB_READER / MONGODB_WRITER / MONGODB_EXECUTE |
| JDBC URL in Server project when JNDI is available | Prefer JNDI on Server |
| Missing `jdbcSpecific` on JNDI connection | Required for dialect behaviour |
| "Validate connection" in Designer for JNDI | Does not work — test on Server |
