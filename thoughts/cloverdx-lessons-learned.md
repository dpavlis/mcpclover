# CloverDX Graph & Subgraph Development — Lessons Learned

> Compiled from a real development session building a Universal Mapper subgraph.
> Every issue below caused a real failure. Treat each as a mandatory check.

---

## 1. Metadata Design

### 1.1 Never put field delimiters on individual fields in delimited metadata

**What went wrong:** Generated metadata with explicit `delimiter=";"` on every `<Field>` element. This is redundant, fragile, and not how CloverDX metadata is idiomatically defined for CSV-style files.

**Correct pattern:** Set `fieldDelimiter` and `recordDelimiter` on the `<Record>` element. Only override per-field if a specific field truly uses a different delimiter (rare — typically only the last field might use `eofAsDelimiter="true"`).

```xml
<!-- WRONG — verbose and brittle -->
<Record name="data" type="delimited">
  <Field name="col1" type="string" delimiter=";"/>
  <Field name="col2" type="string" delimiter=";"/>
  <Field name="col3" type="string" delimiter="\n"/>
</Record>

<!-- CORRECT — clean and idiomatic -->
<Record fieldDelimiter=";" name="data" recordDelimiter="\n" type="delimited">
  <Field name="col1" type="string"/>
  <Field name="col2" type="string"/>
  <Field name="col3" type="string"/>
</Record>
```

### 1.2 Match metadata to actual file format

When creating metadata for a CSV file, check the actual delimiter in the file. The source file `source_abc.csv` used `;` as delimiter, not `,`. Always read a sample of the file before defining metadata.

---

## 2. Subgraph Architecture

### 2.1 Use debugInput/debugOutput for test data nodes

**What went wrong:** Initially wired the mapping CSV reader as a regular component feeding through `SubgraphInput` port 1, which made port 1 a required external input. This forced the parent graph to supply the mapping data through a second edge, adding unnecessary complexity.

**Correct pattern:** Components that provide test data for standalone subgraph execution should be marked `debugInput="true"` (for data sources) or `debugOutput="true"` (for data sinks like Trash). These components are **automatically stripped** when the subgraph runs as a component inside a parent graph. They exist solely for standalone testing.

```xml
<!-- Debug data source — only active during standalone testing -->
<Node debugInput="true" guiName="TestData" guiX="40" guiY="96"
      id="DATA_GENERATOR0" recordsNumber="5" type="DATA_GENERATOR">
  <attr name="generate"><![CDATA[//#CTL2
function integer generate() {
    $out.0.field1 = "test";
    return ALL;
}]]></attr>
</Node>

<!-- Debug sink — only active during standalone testing -->
<Node debugOutput="true" guiName="DebugTrash" guiX="800" guiY="96"
      id="TRASH_DEBUG" type="TRASH"/>
```

**Key rule:** Internal readers/writers that support standalone testing must be `debugInput`/`debugOutput`. Only expose SubgraphInput/SubgraphOutput ports for data that the parent graph genuinely needs to supply or consume.

### 2.2 Subgraph components use `jobURL`, not `graphURL`

**What went wrong:** Used `<attr name="graphURL">` to reference the subgraph `.sgrf` file. This caused "Missing required job URL attribute" error.

**Correct pattern:** The SUBGRAPH component type uses `jobURL` as a direct XML attribute on the `<Node>` element:

```xml
<!-- WRONG -->
<Node id="SUBGRAPH0" type="SUBGRAPH">
  <attr name="graphURL"><![CDATA[${SUBGRAPH_DIR}/MySubgraph.sgrf]]></attr>
</Node>

<!-- CORRECT -->
<Node id="SUBGRAPH0" jobURL="${SUBGRAPH_DIR}/MySubgraph.sgrf" type="SUBGRAPH"/>
```

### 2.3 Subgraph public parameters: double-underscore prefix and editor types

**What went wrong:** Set the subgraph parameter as `MAPPING_FILE="..."` on the SUBGRAPH node. CloverDX accepted it but placed it under "Custom" component attributes — it was not recognized as a public parameter override. The correct convention is to prefix with **two underscores**: `__MAPPING_FILE`.

**Correct pattern:** In the parent graph, override a subgraph's public parameter using the `__` (double underscore) prefix:

```xml
<!-- WRONG — gets treated as a custom attribute, not a parameter override -->
<Node id="SUBGRAPH0" jobURL="${SUBGRAPH_DIR}/MySubgraph.sgrf"
      MAPPING_FILE="${DATAIN_DIR}/mapping.csv" type="SUBGRAPH"/>

<!-- CORRECT — double underscore prefix maps to the public parameter -->
<Node id="SUBGRAPH0" jobURL="${SUBGRAPH_DIR}/MySubgraph.sgrf"
      __MAPPING_FILE="${DATAIN_DIR}/mapping.csv" type="SUBGRAPH"/>
```

**Additionally:** When declaring a public parameter inside the subgraph, always set the `<SingleType>` editor so that the Designer presents the right UI widget. Common editor types:

| Parameter content | `<SingleType>` declaration |
|---|---|
| File or directory path | `<SingleType multiple="true" name="file" selectionMode="file_or_directory"/>` |
| Single file path | `<SingleType name="file"/>` |
| Sort key | `<SingleType name="sortKey"/>` |
| Plain string (default) | `<SingleType name="string"/>` |
| Boolean | `<SingleType name="bool"/>` |
| Integer | `<SingleType name="int"/>` |

Example of a properly declared file-path parameter in a subgraph:

```xml
<GraphParameter label="Mapping File Path" name="MAPPING_FILE" public="true" required="true"
                value="${DATAIN_DIR}/mapping.csv">
  <attr name="description"><![CDATA[Path to the CSV mapping definition file.]]></attr>
  <SingleType multiple="true" name="file" selectionMode="file_or_directory"/>
</GraphParameter>
```

---

## 3. CTL2 Regex Pitfalls

### 3.1 The `?=` operator is regex, not string contains

**What went wrong:** Used `resolvedRule ?= placeholder` where `placeholder` was `{field1}`. The `?=` operator treats the right operand as a Java regex pattern, and `{` is a regex special character (repetition quantifier), causing `PatternSyntaxException: Illegal repetition`.

**Correct pattern:** Use `indexOf()` for plain string containment checks:

```ctl
// WRONG — regex operator, fails on {, }, ., +, etc.
if (myString ?= searchTerm) { ... }

// CORRECT — plain string search
if (indexOf(myString, searchTerm) >= 0) { ... }
```

### 3.2 The `replace()` function pattern argument is always regex

**What went wrong:** Used `replace(str, "{" + name + "}", value)` — the first pattern argument is always interpreted as Java regex. Curly braces `{}` are regex quantifiers.

**Correct pattern:** For plain string replacement, build a helper function using `indexOf()` + `substring()`:

```ctl
function string replacePlaceholder(string input, string placeholder, string replacement) {
    string result = input;
    integer pos = indexOf(result, placeholder);
    while (pos >= 0) {
        string before = substring(result, 0, pos);
        string after = substring(result, pos + length(placeholder));
        result = before + replacement + after;
        pos = indexOf(result, placeholder);
    }
    return result;
}
```

**General rule:** In CTL2, these operators/functions treat arguments as regex: `?=`, `~=`, `replace()`, `split()`, `find()`, `matches()`, `matchGroups()`, `chop(str, regex)`. When working with user-supplied or dynamic strings, never pass them directly to these functions — special characters like `.`, `{`, `}`, `|`, `(`, `)`, `+`, `*`, `?`, `[`, `]`, `\`, `^`, `$` will break.

---

## 4. Serialization / Deserialization Design

### 4.1 Count successfully parsed entries, not total split results

**What went wrong:** Set `ruleCount = length(rules)` (total number of `||`-delimited entries) *before* the parsing loop. Some entries failed the `length(parts) >= 4` check and were skipped, so the arrays had fewer elements than `ruleCount`. The `transform()` function then looped to `ruleCount` and hit `IndexOutOfBoundsException`.

**Correct pattern:** Increment the count only when an entry is successfully parsed:

```ctl
integer totalEntries = length(rules);
// ruleCount starts at 0, incremented only on successful parse
for (integer i = 0; i < totalEntries; i++) {
    string[] parts = split(rules[i], "~");
    if (length(parts) >= 4) {
        // ... populate arrays ...
        ruleCount++;  // count only valid rules
    }
}
```

### 4.2 Handle delimiter collisions in serialized data

**What went wrong:** Used `~` as the intra-rule field separator in the serialized mapping string. If a transformation rule expression ever contains `~`, the `split(entry, "~")` produces more than 4 parts, breaking field assignment.

**Correct pattern:** When deserializing, treat the *last* part as the target column and rejoin all middle parts as the transformation rule:

```ctl
// Target column is always the LAST part after split
// Transformation rule is everything between parts[1] and parts[N-1]
string xformRule = parts[2];
for (integer p = 3; p < length(parts) - 1; p++) {
    xformRule = xformRule + "~" + parts[p];
}
append(tgtColumns, trim(parts[length(parts) - 1]));
```

**Even better:** Consider using a delimiter that is extremely unlikely to appear in CTL expressions (e.g., `\x01`, `|||`, or a unique multi-character token).

---

## 5. CSV Data Files

### 5.1 Quote any field containing special characters

**What went wrong:** The mapping CSV had a transformation rule `date2str(today(), "yyyy-MM-dd")` in an unquoted field. The embedded `"` characters confused the CSV parser, which saw them mid-field and threw "Bad quote format" error.

**Correct pattern:** Any CSV field containing commas, double quotes, or newlines must be fully wrapped in double quotes, with internal double quotes escaped by doubling:

```csv
WRONG:  ABC,S_KEY1,No,date2str(today(), "yyyy-MM-dd"),XYZ,T_LOAD_DATE
CORRECT: ABC,S_KEY1,No,"date2str(today(), ""yyyy-MM-dd"")",XYZ,T_LOAD_DATE
```

**Rule:** When generating CSV files that contain CTL expressions, always quote the transformation rule column — CTL expressions routinely contain commas and string literals with double quotes.

---

## 6. File Editing Discipline

### 6.1 Prefer full file rewrites over incremental patches for CTL-heavy files

**What went wrong (repeatedly):** Used `patch_file` to edit CTL2 code inside CDATA blocks. Patches left behind orphaned code (duplicate function declarations, stray closing braces, leftover old lines). This happened at least three times, each requiring additional cleanup.

**Root cause:** The `patch_file` tool works on line offsets from anchors, but CDATA blocks containing CTL2 code have complex nesting. Anchor-based patching is fragile when:
- The same anchor text appears in multiple places (e.g., `function void preExecute()` in two components)
- The replacement doesn't exactly cover the old content's line range
- Multiple patches interact in the same region

**Correct pattern:** For any change to a CTL2 transform that is more than a one-line fix, **rewrite the entire file** using `write_file`. This is safe because:
1. The file content is fully in your context (you just read it)
2. A clean rewrite guarantees no orphaned code
3. `validate_graph` immediately catches any mistakes

```
Small change (rename a variable, fix one line) → patch_file OK
Anything touching function structure, adding/removing blocks → write_file the whole .sgrf/.grf
```

### 6.2 Always validate after every write

**Already in the workflow guide but worth restating:** Call `validate_graph` after every `write_file` or `patch_file`. Never present a graph as done without a passing validation.

---

## 7. DENORMALIZER Component Gotcha

### 7.1 The transform attribute is called `denormalize`, not `transform`

**What went wrong:** Attempted to use DENORMALIZER with `<attr name="transform">`. The correct attribute name for DENORMALIZER is `denormalize`. Also, DENORMALIZER requires either a `key` attribute or `groupSize`.

**Lesson:** Always call `get_component_info` before using a component, even for "familiar" ones. The attribute names vary by component type:
- REFORMAT: `transform`
- DENORMALIZER: `denormalize`
- NORMALIZER: `transform`
- ROLLUP: `transform`

---

## 8. Design Decisions to Make Up Front

### 8.1 CTL2 cannot read files — plan the architecture accordingly

**What went wrong:** The initial design assumed the REFORMAT component's `init()` function could read the mapping CSV file directly. CTL2 has no file I/O functions. This required a full architectural redesign to a two-phase approach (Phase 0: read CSV into dictionary; Phase 1: use dictionary data in transform).

**Lesson:** Before writing any code, verify that the planned approach is feasible within CTL2's capabilities. Key CTL2 limitations to remember:
- No file I/O (no reading/writing files)
- `evalExpression()` evaluates CTL expressions but has no access to `$in`/`$out` ports
- No dynamic code execution beyond `evalExpression()`
- No reflection — field access by name requires `getFieldIndex()` / `getValue()` / `setValue()`

### 8.2 `evalExpression()` has no port context

**What went wrong:** Initially assumed `evalExpression()` could access `$in.0.fieldName` inside the evaluated expression. It cannot — it operates in an isolated context.

**Correct pattern:** Substitute actual values into the expression string *before* calling `evalExpression()`. For string values, wrap in quotes. For nulls, insert the literal `null`.

---

## Quick Pre-Flight Checklist

Before writing/deploying any CloverDX graph or subgraph, verify:

- [ ] Metadata: `fieldDelimiter` and `recordDelimiter` on `<Record>`, NOT on individual `<Field>` elements
- [ ] Metadata: field names match the actual column names in the data file
- [ ] Metadata: delimiter in metadata matches delimiter in the actual file
- [ ] Subgraph: test data nodes use `debugInput="true"` / `debugOutput="true"`
- [ ] Subgraph: only ports that the parent graph needs to connect are in `<inputPorts>`/`<outputPorts>`
- [ ] Parent graph: SUBGRAPH node uses `jobURL` attribute (not `<attr name="graphURL">`)
- [ ] Parent graph: subgraph parameter overrides use `__` double-underscore prefix (e.g. `__MAPPING_FILE`)
- [ ] Subgraph: public parameters have appropriate `<SingleType>` editor (e.g. `name="file"` for file paths, `name="sortKey"` for sort keys)
- [ ] CTL2: no `?=` or `replace()` with dynamic strings containing regex special chars
- [ ] CTL2: array iteration count derived from actual array size, not from a pre-filter count
- [ ] CSV data: all fields containing quotes, commas, or newlines are properly quoted and escaped
- [ ] Architecture: CTL2 transform does not assume file I/O or port-context eval
- [ ] Editing: complex CTL changes use full `write_file`, not incremental `patch_file`
- [ ] Validation: `validate_graph` called after every write, result is PASS
