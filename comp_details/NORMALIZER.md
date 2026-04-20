# CloverDX NORMALIZER — LLM Reference

## What it does
Expands 1 input record into N output records. N is determined at runtime by `count()`.
The inverse of DENORMALIZER. Input does **not** need to be sorted.
Use when: unpacking list fields into rows, splitting a delimited string into individual records, repeating a record N times with variations.

## Ports
- Input 0: required — one record in (any metadata)
- Output 0: required — N records out (any metadata)
No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `normalize` [attr-cdata] | one of | Inline CTL2 transformation |
| `normalizeURL` | one of | Path to external CTL file. Also set `normalizeSourceCharset` when using this. |
| `normalizeClass` | one of | Java class implementing RecordNormalize |

**Best practice:** When using `normalizeURL`, always set `normalizeSourceCharset` explicitly (e.g. `UTF-8`).

## Function Call Lifecycle

For each input record:
1. `count()` — called once; returns N (number of output records to produce)
2. `transform(idx)` — called N times, idx from 0 to N-1
3. `clean()` — called once **after** the last `transform()` call for this input record

Global (per graph run):
- `init()` — once before first record
- `preExecute()` — once per run before processing starts
- `postExecute()` — once per run after processing ends

If `count()` returns 0, `transform()` is not called — the input record is skipped.

## CTL Entry Points

`count()` and `transform(integer idx)` are mandatory. All others optional.

```ctl
//#CTL2

// MODULE-LEVEL VARIABLES — set in count(), used in transform().
string[] parts;

// Called once per input record.
// $in.0 accessible here.
// Returns N: the number of output records to produce.
// Return 0 to skip this input record (transform() not called).
function integer count() {
    parts = split($in.0.csvField, ";");  // parse once, cache for transform()
    return length(parts);
}

// Called N times per input record (idx 0 to count()-1).
// $in.0 accessible here. $out.0 accessible here.
// idx is 0-based.
function integer transform(integer idx) {
    $out.0.parentId = $in.0.id;
    $out.0.item = trim(parts[idx]);
    return OK;
}

// Called after the last transform() call for this input record.
// Use to reset module-level variables.
// $in.0 and $out.0 NOT accessible here.
function void clean() {
    clear(parts);
}

// Optional — called once before any record is processed. Return false aborts graph.
// function boolean init() { return true; }

// Optional — called if count() throws an exception.
// Returns: N (same semantics as count() — number of records to produce).
// $in.0 accessible here.
// function integer countOnError(string errorMessage, string stackTrace) { return 0; }

// Optional — called if transform() throws an exception.
// idx parameter present — same as transform(idx).
// $in.0 and $out.0 accessible here.
// function integer transformOnError(string errorMessage, string stackTrace, integer idx) { return SKIP; }

// Optional — called when count/transform/countOnError/transformOnError returns <= -2.
// function string getMessage() { return "custom error message"; }

// Optional — allocate resources per graph run (released in postExecute)
// function void preExecute() {}
// function void postExecute() {}
```

### Critical: `transformOnError` signature includes `idx`

```ctl
// CORRECT — idx is the third parameter:
function integer transformOnError(string errorMessage, string stackTrace, integer idx) {
    $out.0.item = parts[idx];
    $out.0.parentId = $in.0.id;
    return OK;
}

// WRONG — missing idx:
function integer transformOnError(string errorMessage, string stackTrace) { ... }
```

### $in.0 / $out.0 access rules — violations throw NPE at runtime

| Function | `$in.0` | `$out.0` |
|---|---|---|
| `init()` | ✗ | ✗ |
| `count()` | ✓ | ✗ |
| `countOnError()` | ✓ | ✗ |
| `transform(idx)` | ✓ | ✓ |
| `transformOnError(msg, trace, idx)` | ✓ | ✓ |
| `clean()` | ✗ | ✗ |
| `preExecute()` / `postExecute()` | ✗ | ✗ |

### Return value summary

| Function | Meaning |
|---|---|
| `count()` | N ≥ 0: produce N output records. 0 = skip. ≤ -2 = error (calls getMessage()) |
| `countOnError()` | Same semantics as count() — N to produce. Return 1 to produce one fallback record. |
| `transform(idx)` | OK/ALL/0 = emit record; SKIP = skip this record; ≤ -2 = error |
| `transformOnError(msg, trace, idx)` | Same semantics as transform() |

Note: in `transform()`, `ALL` (= 0) is valid and equivalent to `OK`.

## Official Example (from docs)

### Expand list field — one record per group member
```ctl
//#CTL2

function integer count() {
    return length($in.0.users);  // list field — each element becomes one output record
}

function integer transform(integer idx) {
    $out.0.group = $in.0.group;
    $out.0.user = $in.0.users[idx];  // index into list field directly
    return OK;
}
```
Input `accounting | [johnsmith, elisabethtaylor]` →
Output `accounting|johnsmith` + `accounting|elisabethtaylor`

No `clean()` needed here — no module-level variables are used.

## Real Sandbox Examples

### DWHExample — expand each order into N line items (random count, uses helper function)
```xml
<Node guiName="Generate line items" id="GENERATE_LINE_ITEMS" type="NORMALIZER">
    <attr name="normalize"><![CDATA[//#CTL2

function integer count() {
    return getRandomIntGaussian(${MIN_ITEMS_PER_ORDER}, ${MAX_ITEMS_PER_ORDER});
}

function integer transform(integer i) {   // parameter name can be anything; position matters
    $out.0.* = $in.0.*;
    Product prod = getRandomProduct();
    $out.0.Product_Code = prod.productCode;
    $out.0.Unit_Price = prod.unitPrice;
    $out.0.Unit_Quantity = randomInteger(1, 10);
    $out.0.Total_Price = $out.0.Unit_Quantity * $out.0.Unit_Price;
    dictionary.itemCount += 1;
    return OK;
}
]]></attr>
</Node>
```

### DWHExample — dynamic count with skip (return 0 for unknown status)
```ctl
//#CTL2
string[] queries;

function integer count() {
    clear(queries);   // reset list for each input record
    switch (upperCase(dictionary.logData['status'])) {
        case 'STARTED':
            // build and append SQL queries to list...
            break;
        default:
            return 0;   // skip — produce no output records
    }
    return length(queries);
}

function integer transform(integer idx) {
    $out.0.query = queries[idx];
    return OK;
}
```

## Common Patterns

### Expand fixed number of times (generate N copies)
```ctl
function integer count() { return 12; }  // always 12 output records

function integer transform(integer idx) {
    $out.0.* = $in.0.*;
    $out.0.month = idx + 1;   // idx is 0-based → month 1-12
    return OK;
}
```

### Split delimited string field
```ctl
string[] items;

function integer count() {
    items = split($in.0.tags, ",");
    return length(items);
}

function integer transform(integer idx) {
    $out.0.id = $in.0.id;
    $out.0.tag = trim(items[idx]);
    return OK;
}

function void clean() {
    clear(items);
}
```

### Conditional expansion — skip some input records
```ctl
function integer count() {
    if (isnull($in.0.items) || length($in.0.items) == 0) {
        return 0;   // skip records with no items
    }
    return length($in.0.items);
}
```

### Using init() for one-time setup
```ctl
integer expansionFactor;

function boolean init() {
    expansionFactor = str2integer(getParamValue("EXPANSION_FACTOR"));
    return true;    // return false to abort graph
}

function integer count() {
    return expansionFactor;
}
```

## Decision Guide

| Need | Use |
|---|---|
| 1 → N (variable N per record, runtime) | NORMALIZER |
| N → 1 (collapse rows by key) | DENORMALIZER |
| Expand a list-typed metadata field into rows | NORMALIZER with `$in.0.listField[idx]` |
| Split a delimited string into rows | NORMALIZER with `split()` in `count()` |
| Skip certain input records | Return 0 from `count()` |
| Constant expansion (always N copies) | NORMALIZER with `count()` returning constant |

## Mistakes

| Wrong | Correct |
|---|---|
| `function integer transform()` (no idx) | `function integer transform(integer idx)` — mandatory parameter |
| `function integer transformOnError(string msg, string trace)` | Must include `integer idx`: `transformOnError(string msg, string trace, integer idx)` |
| Using idx as 1-based | idx is 0-based: 0 to count()-1 |
| Calling split() or other parsing inside `transform()` | Parse once in `count()`, cache in module-level variable, index in `transform()` |
| `$out.0` accessed in `count()` | Not accessible — NPE; only in `transform()` |
| `$in.0` accessed in `clean()` | Not accessible — NPE |
| Module-level list not cleared between records | Use `clear(list)` in `clean()` — lists persist across input records |
| Returning `ALL` from `transform()` | `ALL` = 0 = OK — valid but prefer `return OK` for clarity |
| External CTL without `normalizeSourceCharset` | Always set charset explicitly for external files |
| `function integer countOnError(string msg, string trace)` not returning count | Must return N (same as `count()`); return 0 to skip, 1 to produce a fallback record |
