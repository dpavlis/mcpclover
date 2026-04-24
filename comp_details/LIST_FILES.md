# CloverDX LIST_FILES — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX LIST_FILES (ListFiles).
> Incorporates confirmed working patterns from BasicFeatures and MiscExamples sandboxes.
> LIST_FILES serves two distinct roles: a **data source** in graphs (one output record per
> matched file/directory), and a **token source or presence check** in jobflows
> (one token per match — or zero tokens when nothing matches, which terminates the branch).

---

## WHEN TO USE LIST_FILES VS ALTERNATIVES

| Component | Use when |
|---|---|
| **LIST_FILES** | **Default choice for enumerating files before processing.** Returns file metadata (URL, name, size, lastModified, isDirectory) as records or tokens. Supports wildcards, recursion, archive listing, remote storage (S3, Azure Blob, SFTP). |
| DATA_READER / FLAT_FILE_READER | When you want to read file *contents*, not enumerate file entries. |
| DELETE_FILES | When you want to remove files. Has identical port/mapping model — use LIST_FILES first to find the target paths. |
| CREATE_FILES | When you want to create files or directories. |

**Decision rule:** Use LIST_FILES whenever you need to discover which files exist before deciding what to do with them — whether that is reading them, dispatching one child job per file, checking for presence of a lock file, or verifying that output was produced.

---

## COMPONENT SKELETON

### Minimal — list a directory, no mapping needed

```xml
<Node
  type="LIST_FILES"
  id="LIST_FILES"
  guiName="ListFiles"
  guiX="45" guiY="250"
  fileURL="${DATAIN_DIR}/hl7/oru"/>
```

One output record per entry in the directory. No `standardOutputMapping` required — all
result fields are available on port 0 automatically.

### With wildcard — match specific files

```xml
<Node
  type="LIST_FILES"
  id="FIND_CUSTOMERS"
  guiName="Find customers"
  guiX="-30" guiY="475"
  fileURL="${DATAIN_DIR}/Customers*.csv"/>
```

Wildcard in `fileURL` filters entries by name pattern. Multiple files matching the pattern
each produce one output record.

### Recursive — traverse subdirectories

```xml
<Node
  type="LIST_FILES"
  id="LIST_FILES"
  guiName="ListFiles"
  guiX="45" guiY="450"
  fileURL="${DATAIN_DIR}/Retailers"
  recursive="true"/>
```

### With standardOutputMapping — enrich or rewrite the output record

```xml
<Node
  type="LIST_FILES"
  id="FIND_ORDERS"
  guiName="Find orders"
  guiX="-30" guiY="650"
  fileURL="${DATAIN_DIR}/Orders*.zip">
  <attr name="standardOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;
    $out.0.URL = "zip:(" + $in.1.URL + ")#*.xml";
    return ALL;
}
]]></attr>
</Node>
```

`$in.1` contains all result fields (URL, name, size, …). Use `standardOutputMapping` when
you need to rewrite `URL` (e.g. wrap in an archive scheme) or add computed fields before
the record flows downstream.

### Directory existence check (jobflow pre-flight)

```xml
<Node
  type="LIST_FILES"
  id="CHECK_LOCK"
  guiName="Check lock file"
  guiX="200" guiY="300"
  fileURL="${DATATMP_DIR}/my.lock"
  listDirectoryContents="false"/>
```

`listDirectoryContents="false"` returns information about the path itself, not its contents.
Used to check whether a specific file or directory exists. In jobflows, port 0 = found
(the path exists), port 1 = not found (the path does not exist).

### Remote storage listing (Azure Blob)

```xml
<Node
  type="LIST_FILES"
  id="LIST_FILES"
  guiName="ListFiles"
  guiX="170" guiY="625"
  fileURL="az-blob://${AZURE_ACCOUNT_NAME}:${AZURE_KEY_ESCAPED}@${AZURE_ACCOUNT_NAME}.blob.core.windows.net/${AZURE_CONTAINER}/*"/>
```

Remote storage uses the same component — only `fileURL` scheme differs.

---

## NODE-LEVEL ATTRIBUTES

### Target

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="LIST_FILES"` | yes | Component type |
| `fileURL` | yes* | Path, URL, or glob pattern to list. Supports local paths, `sandbox://`, `sftp://`, `s3://`, `az-blob://`, archive URLs (`zip:(...)`, `tar:(...)`), and wildcards. *Can be omitted if overridden in `inputMapping`. |
| `recursive` | no | Recurse into subdirectories. Default: `false`. Has no effect when `listDirectoryContents="false"`. |
| `listDirectoryContents` | no | `true` (default): return entries inside the target directory. `false`: return information about the directory/file itself — used for existence checks. |

### Error handling

| Attribute (XML) | Default | Description |
|---|---|---|
| `stopOnFail` | `true` | `true`: failure on one input record stops all subsequent records and sends them to the error port. `false`: processing continues. Only effective when an error port edge is connected. |
| `redirectErrorOutput` | `false` | `true`: errors are emitted to port 0 (standard output) instead of port 1. Distinguish by `$in.1.result == false` in `standardOutputMapping`. |

### Mappings

| Attribute (XML) | Description |
|---|---|
| `inputMapping` | CTL2/CDATA. Override `fileURL` and `recursive` per input record from the upstream edge. See Input Mapping section. |
| `standardOutputMapping` | CTL2/CDATA. Map result fields and input fields to the output record on port 0. If absent, result fields are auto-mapped by name. |
| `errorOutputMapping` | CTL2/CDATA. Map error fields to port 1. If absent, error fields are auto-mapped by name. |

---

## MAPPINGS — THE CORE CONCEPT

LIST_FILES mappings follow the same `$in` / `$out` pattern as other file operation components,
but the record numbering is specific to this component.

### Port numbering in mappings

**inputMapping — `$out` records written by the LLM:**

| Record | Meaning | Key fields |
|---|---|---|
| `$out.0` | Component Attributes — override per input record | `fileURL` (string), `recursive` (boolean), `listDirectoryContents` (boolean) |

**inputMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming record from port 0 — all user-defined fields |

**standardOutputMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming record from the input port (pass-through from upstream) |
| `$in.1` | Result record — all file metadata fields (see Result Fields below) |

**standardOutputMapping — `$out` records written by the LLM:**

| Record | Meaning |
|---|---|
| `$out.0` | Output record emitted on port 0 |

**errorOutputMapping — `$in` and `$out`:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming record from input port |
| `$in.1` | Error record — `result`, `errorMessage`, `stackTrace` |
| `$out.0` | Output record emitted on error port 1 |

---

## INPUT MAPPING

Overrides `fileURL`, `recursive`, or `listDirectoryContents` from values in the incoming
record. The component then lists one path per input token.

### Dynamic fileURL from upstream record

```ctl
//#CTL2
function integer transform() {
    $out.0.fileURL = $in.0.sourceDirectory + "/*.csv";
    return ALL;
}
```

### Conditional recursion

```ctl
//#CTL2
function integer transform() {
    $out.0.fileURL    = $in.0.rootPath;
    $out.0.recursive  = $in.0.includeSubdirs;
    return ALL;
}
```

When `inputMapping` is used, a `fileURL` attribute on the `<Node>` element is still
required for design-time validation (or set `skipCheckConfig="true"`).

---

## STANDARD OUTPUT MAPPING

### Default behaviour (no mapping)

When `standardOutputMapping` is absent, all result fields (`URL`, `name`, `size`, etc.)
are auto-mapped by name to the output record on port 0. This is sufficient for most cases.

### Passing result fields through with URL rewrite

```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;
    $out.0.URL = "zip:(" + $in.1.URL + ")#*.xml";
    return ALL;
}
```

`$out.0.* = $in.1.*;` copies all result fields first, then the URL field is overwritten
with the archive-wrapped version. This is the standard pattern when LIST_FILES is used to
locate zip files that will be opened with an archive URL scheme by a downstream reader.

### Merging input fields with result fields

```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;     // result fields (URL, name, size, …)
    $out.0.batchId = $in.0.batchId;  // pass-through from upstream token
    return ALL;
}
```

When LIST_FILES has an input port connected, use `$in.0` for upstream fields and
`$in.1` for the file result fields.

---

## RESULT FIELDS (port 0 — output record)

| Field | Type | Description |
|---|---|---|
| `URL` | string | Full URL of the file or directory entry. Use this in downstream readers — not `name`. |
| `name` | string | File or directory name only (no path). |
| `isDirectory` | boolean | `true` if the entry is a directory. |
| `isFile` | boolean | `true` if the entry is a regular file. |
| `isHidden` | boolean | `true` if the entry is hidden. |
| `size` | long | File size in bytes. |
| `lastModified` | date | Last modification time. |
| `canRead` | boolean | `true` if the file can be read. |
| `canWrite` | boolean | `true` if the file can be modified. |
| `canExecute` | boolean | `true` if the file can be executed. |
| `result` | boolean | `true` if the operation succeeded. `false` when `redirectErrorOutput="true"` and an error occurred. |
| `errorMessage` | string | Error message when `result=false` and `redirectErrorOutput="true"`. |
| `stackTrace` | string | Stack trace when `result=false` and `redirectErrorOutput="true"`. |

**Use `URL`, not `name`, as the file path in downstream readers.** `name` is the bare
filename without the directory path. `URL` is the fully qualified path suitable for
`fileURL` attributes on reader/writer components.

---

## ERROR FIELDS (port 1 — error record)

| Field | Type | Description |
|---|---|---|
| `result` | boolean | Always `false`. |
| `errorMessage` | string | The error message. |
| `stackTrace` | string | The stack trace. |

---

## PORTS

| Port | Direction | XML string | Description |
|---|---|---|---|
| Port 0 | in (optional) | `Port 0 (in)` | Input records. One listing per record. When absent, component lists once using static `fileURL`. |
| Port 0 | out (required) | `Port 0 (out)` | One record per matched file or directory entry. Zero records if nothing matches. |
| Port 1 | out (optional) | `Port 1 (out)` | Error records. |

**Jobflow note — port semantics are inverted from what you might expect:**
In a jobflow used as a lock/presence check, `Port 0 (out)` emits a token when
the target **exists** (found), and emits nothing (zero tokens) when it does **not** exist.
A downstream `CONDITION` or the implicit zero-token termination handles the "not found" branch.
There is no dedicated "not found" port — an empty result simply produces no tokens.

---

## ARCHIVE LISTING

LIST_FILES can enumerate the contents of archive files when an **archive URL** is used as `fileURL`.
The `recursive` and `listDirectoryContents` attributes apply to the archive contents.

| URL form | Behaviour |
|---|---|
| `zip:(sandbox://data/archive.zip)` | Lists entries inside the zip |
| `sandbox://data/archive.zip` | Lists the zip file itself (not its contents) |
| `tar:(zip:(sandbox://data/archive.zip)!inner.tar)` | Lists contents of the nested tar inside the zip |

**Archive URL since 6.4:** Inner and outer archive paths are separated by `!` (previously `#`).

Some archives have no directory entries — only file entries with full paths. Listing a
directory path within such an archive returns no results.

---

## TYPICAL PATTERNS

### File iteration — one token per file into EXECUTE_GRAPH (MiscExamples/ProcessMultipleFiles.jbf)

The most common jobflow pattern. LIST_FILES emits one token per matched file; each token
drives one EXECUTE_GRAPH child:

```xml
<Node type="LIST_FILES" id="LIST_FILES"
      guiName="ListFiles" guiX="45" guiY="450"
      fileURL="${DATAIN_DIR}/Retailers"
      recursive="true"/>
```

```
LIST_FILES → [filter/enrich] → EXECUTE_GRAPH(executorsNumber=N) → [aggregate results]
```

Downstream `EXECUTE_GRAPH` receives `$in.0.URL` which is used as the child's input parameter.

### URL rewrite for archive contents (BasicFeatures/01 - Load online store.jbf)

LIST_FILES finds `.zip` files; `standardOutputMapping` rewrites the URL to an archive URL
scheme so that a downstream reader can access the zip contents directly:

```xml
<Node type="LIST_FILES" id="FIND_ORDERS"
      guiName="Find orders"
      fileURL="${DATAIN_DIR}/Orders*.zip">
  <attr name="standardOutputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.1.*;
    $out.0.URL = "zip:(" + $in.1.URL + ")#*.xml";
    return ALL;
}
]]></attr>
</Node>
```

### Simple directory listing in a graph (BasicFeatures/18 - HL7 processing.grf)

In a data graph, LIST_FILES works as a data source — output records flow into downstream
transformation components rather than into EXECUTE_GRAPH:

```xml
<Node type="LIST_FILES" id="LIST_FILES"
      guiName="ListFiles" guiX="45" guiY="250"
      fileURL="${DATAIN_DIR}/hl7/oru"/>
```

```
LIST_FILES → [reader per URL] → [transform] → [writer]
```

### Remote storage listing (BasicFeatures/23 - AzureBlobWrite.grf)

```xml
<Node type="LIST_FILES" id="LIST_FILES" guiName="ListFiles"
      fileURL="az-blob://${AZURE_ACCOUNT_NAME}:${AZURE_KEY_ESCAPED}@${AZURE_ACCOUNT_NAME}.blob.core.windows.net/${AZURE_CONTAINER}/*"/>
```

Same component and mapping model regardless of storage backend. S3, SFTP, and other
supported URL schemes work identically.

### Lock-file pre-flight check (jobflow guard pattern)

Check whether a lock file exists before starting work. `listDirectoryContents="false"`
returns information about the path itself:

```xml
<Node type="LIST_FILES" id="CHECK_LOCK"
      guiName="Check lock file"
      fileURL="${DATATMP_DIR}/my.lock"
      listDirectoryContents="false"
      stopOnFail="false"/>
```

```
CHECK_LOCK port 0 (found)     → [lock exists — abort or wait]
CHECK_LOCK zero output tokens → [lock absent — proceed]
```

Because LIST_FILES emits zero tokens when nothing matches, the downstream branch simply
never executes. No explicit "not found" routing is required — the absence of a token
is the signal.

---

## EDGE DECLARATIONS

```xml
<!-- Standard output — one record per file found -->
<Edge fromNode="LIST_FILES:0" id="Edge0"
      outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="NEXT_COMPONENT:0"
      metadata="MetaFileResult"/>

<!-- Error output (optional) -->
<Edge fromNode="LIST_FILES:1" id="Edge1"
      outPort="Port 1 (out)"
      inPort="Port 0 (in)" toNode="ERROR_HANDLER:0"
      metadata="MetaError"/>

<!-- Input port (optional — for dynamic fileURL via inputMapping) -->
<Edge fromNode="UPSTREAM:0" id="Edge2"
      outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="LIST_FILES:0"
      metadata="MetaUpstream"/>
```

---

## RECOMMENDED OUTPUT METADATA

```xml
<Record name="FileResult" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <Field name="URL" type="string"/>
    <Field name="name" type="string"/>
    <Field name="isDirectory" type="boolean" trim="true"/>
    <Field name="isFile" type="boolean" trim="true"/>
    <Field name="size" type="long" trim="true"/>
    <Field name="lastModified" type="date" trim="true" format="yyyy-MM-dd HH:mm:ss"/>
    <!-- Include only if redirectErrorOutput="true": -->
    <Field name="result" type="boolean" trim="true"/>
    <Field name="errorMessage" type="string"/>
</Record>
```

For the error port:
```xml
<Record name="FileError" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <Field name="result" type="boolean" trim="true"/>
    <Field name="errorMessage" type="string"/>
    <Field name="stackTrace" type="string"/>
</Record>
```

---

## GENERATION RULES FOR LLM

Always include:
- `type="LIST_FILES"`
- `fileURL` — use sandbox parameters (`${DATAIN_DIR}/...`, `${DATATMP_DIR}/...`). Wildcards (`*`, `?`) are supported directly in the value.
- Connect port 0 to a downstream component — it is the only required port.

When listing for file iteration in jobflows:
- No `standardOutputMapping` needed unless URL rewriting or field merging is required.
- Pass `$in.0.URL` (not `$in.0.name`) to the downstream `EXECUTE_GRAPH` input mapping as the file path parameter.
- Use `recursive="true"` to traverse subdirectories.

When using `standardOutputMapping`:
- Always start with `$out.0.* = $in.1.*;` to copy all result fields, then selectively override.
- `$in.1` holds the result fields. `$in.0` holds the upstream input record (only present when input port is connected).

When using as a presence/existence check:
- Set `listDirectoryContents="false"` to check whether a specific path exists rather than listing its contents.
- Zero output tokens means "not found" — no explicit routing needed for that branch.
- Use `stopOnFail="false"` when a missing path is expected and should not abort the job.

Archive listing:
- Use archive URL syntax in `fileURL` (e.g. `zip:(${DATAIN_DIR}/archive.zip)`) to list archive contents.
- A plain file URL (e.g. `${DATAIN_DIR}/archive.zip`) lists the archive file itself, not its contents.

Do NOT:
- Use `name` as the file path in downstream readers — use `URL`, which is the fully qualified path.
- Forget that zero matching files produces zero output records, silently terminating any downstream branch that depends on at least one token.
- Set `recursive="true"` together with `listDirectoryContents="false"` — `recursive` has no effect when directory contents are not listed.
- Confuse `$in.0` and `$in.1` in `standardOutputMapping` — `$in.0` is the upstream input record, `$in.1` is the file result.

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| Using `$in.0.name` as the file path for downstream readers | Use `$in.0.URL` (or `$in.1.URL` in `standardOutputMapping`) — `name` is the bare filename with no path |
| Expecting an error when no files match | Zero matching files = zero output records, no error. Handle the empty case with downstream logic or an upstream guard. |
| Listing archive contents with a plain file URL | Use archive URL syntax: `zip:(${DATAIN_DIR}/archive.zip)` to list contents; `${DATAIN_DIR}/archive.zip` lists the file itself |
| Confusing `$in.0` and `$in.1` in `standardOutputMapping` | `$in.1` = file result fields; `$in.0` = upstream input record (only present when input port is connected) |
| Missing `$out.0.* = $in.1.*;` when rewriting a single field | Copy all result fields first, then overwrite the specific field — otherwise only the overwritten field is present on the output record |
| Setting `recursive="true"` with `listDirectoryContents="false"` | `recursive` has no effect when `listDirectoryContents="false"` — the two attributes are independent |
| Assuming port 1 fires when nothing matches | Port 1 is an error port, not a "not found" port. An empty result is not an error — it is zero records on port 0. |
