# CloverDX DENORMALIZER — LLM Reference

## What it does
Collapses N consecutive input records with the same key value into exactly 1 output record.
Input MUST be sorted on the key field(s). Use for: concatenating strings across rows, collecting values per group, pivoting repeated rows into columns.

## Ports
- Input 0: required — sorted input records (any metadata)
- Output 0: required — one output record per group (any metadata)
No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `key` | one of | Field names defining group boundaries. Adjacent records with the same key value form one group. Separator: semicolon, colon, or pipe. |
| `groupSize` | one of | Fixed integer — every N records form one group. Mutually exclusive with `key`. `groupSize` takes priority if both set. Input count must be multiple of groupSize unless `incompleteGroupAllowed="true"`. |
| `denormalize` [attr-cdata] | one of | Inline CTL2 transformation |
| `denormalizeURL` | one of | Path to external CTL file. Also set `denormalizeSourceCharset` when using this. |
| `order` | no | `Auto` (default) / `Asc` / `Desc` / `Ignore`. Expected sort order of input groups. `Ignore` = groups contiguous but not globally sorted. |
| `equalNULL` | no | Default `true`. NULL key values treated as equal (same group). |
| `incompleteGroupAllowed` | no | Default `false`. Allow last group to have fewer records than `groupSize`. |

**Key or groupSize:** if neither is set, all records form one single group.

## Function Call Lifecycle

For each group of input records:
1. `append()` — called once per input record
2. `transform()` — called once after all `append()` calls for the group
3. `clean()` — called **after** `transform()` to reset state for next group

Global (per graph run):
- `init()` — once before first record
- `preExecute()` — once per run before processing starts
- `postExecute()` — once per run after processing ends

## CTL Entry Points

`append()` and `transform()` are mandatory. `clean()` is mandatory whenever you use module-level (global) variables.

```ctl
//#CTL2

// MODULE-LEVEL VARIABLES — persist across function calls within a group.
// Must be reset in clean() for each group.
string[] products = [];
string companyName;

// Called once per input record within the current group.
// $in.0 accessible here only (NOT in transform/clean).
// Returns: non-negative = OK; <= -2 = error (calls getMessage())
function integer append() {
    append(products, $in.0.product);
    companyName = $in.0.companyName;
    return OK;
}

// Called once after all append() calls for the group.
// $out.0 accessible here only (NOT in append/clean).
// Returns: OK/ALL/0 = emit record; SKIP = skip output; <= -2 = error
function integer transform() {
    $out.0.companyName = companyName;
    $out.0.products = join(",", products);
    return OK;
}

// Called after transform() for each group.
// MANDATORY when using module-level variables — state bleeds without it.
// $in.0 and $out.0 NOT accessible here.
function void clean() {
    clear(products);
    companyName = null;
}

// Optional — called once before any record is processed. Return false aborts graph.
// function boolean init() { return true; }

// Optional — called if append() throws an exception.
// Returns: positive = ignored; 0 = continue; negative = error
// function integer appendOnError(string errorMessage, string stackTrace) { return OK; }

// Optional — called if transform() throws an exception.
// function integer transformOnError(string errorMessage, string stackTrace) { return OK; }

// Optional — called when any function returns <= -2 (provides custom error message)
// function string getMessage() { return "custom error"; }

// Optional — allocate resources per graph run (released in postExecute)
// function void preExecute() {}
// function void postExecute() {}
```

### Return value summary

| Function | Non-negative (OK/ALL) | SKIP | <= -2 |
|---|---|---|---|
| `append()` | Continue accumulating | — | Abort (calls getMessage()) |
| `transform()` | Emit output record | Suppress output, continue | Abort (calls getMessage()) |
| `appendOnError()` | Positive ignored; 0 = continue | — | Error |
| `transformOnError()` | Emit output record | Suppress output | Error |

Note: in `transform()`, `ALL` (= 0) is valid and equivalent to `OK`.

### $in.0 / $out.0 access rules — violations throw NPE at runtime

| Function | `$in.0` | `$out.0` |
|---|---|---|
| `init()` | ✗ | ✗ |
| `append()` | ✓ | ✗ |
| `appendOnError()` | ✓ | ✗ |
| `transform()` | ✗ | ✓ |
| `transformOnError()` | ✗ | ✓ |
| `clean()` | ✗ | ✗ |

## Official Examples (from docs)

### Key-based — group by companyName, collect products
```ctl
//#CTL2
string[] products;
string companyName;

function integer append() {
    append(products, $in.0.product);
    companyName = $in.0.companyName;
    return OK;
}

function integer transform() {
    $out.0.companyName = companyName;
    $out.0.products = join(",", products);
    return OK;
}

function void clean() {
    clear(products);
}
```
Node: `key="companyName"`. Input sorted by companyName.
Output: `Denormalizer Limited|chocolate,coffee,pizza` / `ZXCV International|coffee`

### groupSize — fixed N records per group, counter in init()
```ctl
//#CTL2
integer groupNumber;
string[] names;

function boolean init() {
    groupNumber = 1;    // init() runs once before first record — for one-time initialization
    return true;
}

function integer append() {
    append(names, $in.0.name);
    return OK;
}

function integer transform() {
    $out.0.groupNo = groupNumber;
    $out.0.members = join(",", names);
    groupNumber++;      // counter advances in transform(), not clean()
    return OK;
}

function void clean() {
    clear(names);       // only accumulated list is cleared — groupNumber persists
}
```
Node: `groupSize="3"` + `incompleteGroupAllowed="true"`. No `key` or upstream sort needed.
Output: `1|Charlie,Daniel,Agatha` / `2|Henry,Oscar,Kate` / `3|Romeo,Jane`

## Real Sandbox Examples

### DWHExample — collapse VALIDATOR errors per record
```xml
<Node id="DENORMALIZER" key="recordNo(a)" type="DENORMALIZER">
    <attr name="denormalize"><![CDATA[//#CTL2
string[] reasons = [];

function integer append() {
    reasons.append($in.0.rejectReason);
    return OK;
}

function integer transform() {
    $out.0 = $in.0;
    $out.0.rejectReason = join("|", reasons);
    return OK;
}

function void clean() {
    clear(reasons);
}
]]></attr>
</Node>
```

### MiscExamples — accumulate state, mark matching fields
```xml
<Node id="DENORMALIZER" key="id(a)" type="DENORMALIZER">
    <attr name="denormalize"><![CDATA[//#CTL2
rejected_contacts_csv inputR;
list[string] validationErrors;

function integer append() {
    if (isNull(inputR, "id")) {
        inputR.* = $in.0.*;   // capture first record of group as base
    }
    append(validationErrors, $in.0.ruleName);
    return OK;
}

function integer transform() {
    $out.0.* = inputR.*;
    for (integer idx = 0; idx < length($out.0); idx++) {
        if (containsValue(validationErrors, getFieldLabel($out.0, idx))) {
            setStringValue($out.0, idx, "x");
        }
    }
    return OK;
}

function void clean() {
    resetRecord(inputR);
    clear(validationErrors);
}
]]></attr>
</Node>
```

## key Format

```
key="fieldName"           -- single field
key="field1;field2"       -- composite key (semicolon)
key="field1:field2"       -- colon separator also valid
key="field1|field2"       -- pipe separator also valid
key="recordNo(a)"         -- with ascending sort direction annotation
key="recordNo(d)"         -- descending sort direction annotation
```

Sort direction suffix `(a)` / `(d)` must match the upstream FAST_SORT/EXT_SORT `sortKey`.

## Upstream Sort and Adjacency Requirement

Input MUST be sorted so that records with the same key are **adjacent** (contiguous). Records with the same key arriving in non-contiguous runs produce **separate output records per run** — not one merged record. This is the most common silent correctness bug.

```xml
<Node id="SORT"        sortKey="recordNo(a)"  type="FAST_SORT"/>
<Node id="DENORMALIZER" key="recordNo(a)"     type="DENORMALIZER"/>
```

Exception: `order="Ignore"` skips sort-order tracking — use when groups are naturally contiguous (e.g. DB query with GROUP BY-equivalent ordering) but not globally sorted ascending or descending.

## Validator Error Collapse Pattern (canonical use case)

```
READER → VALIDATOR(root lazyEvaluation=false, sub-group lazyEvaluation=true)
  invalid port (1) → FAST_SORT(sortKey="recordNo(a)") → DENORMALIZER(key="recordNo(a)") → ERROR_WRITER
```
VALIDATOR `errorMapping` produces one record per failing rule with `$in.1.recordNo` + `$in.1.validationMessage`. DENORMALIZER collapses all failures per recordNo into one row.

## Decision Guide

| Need | Use |
|---|---|
| N same-key rows → 1 row | DENORMALIZER with `key` |
| Every N rows → 1 row | DENORMALIZER with `groupSize` |
| All rows → 1 row | DENORMALIZER with neither (single group) |
| 1 group → M rows (variable output) | ROLLUP |

## Mistakes

| Wrong | Correct |
|---|---|
| Module-level variables without `clean()` | State bleeds between groups — always implement `clean()` |
| `$out.0` in `append()` | NPE — only accessible in `transform()` |
| `$in.0` in `transform()` | NPE — only accessible in `append()` |
| `$in.0` or `$out.0` in `clean()` | NPE — neither accessible |
| Input not sorted on key | Add FAST_SORT upstream with matching `sortKey` |
| Same-key records not adjacent | Sort the input; non-contiguous same-key records produce multiple output records |
| `key` and `groupSize` both set | `groupSize` takes priority |
| `incompleteGroupAllowed` omitted with groupSize | Graph fails if input count not a multiple of groupSize |
| Counter incremented in `clean()` | Put counter increments in `transform()` — `clean()` is for resetting accumulated values |
| `return ALL` from `transform()` | `ALL` = 0 = OK — valid but prefer `return OK` for clarity |
| External CTL without `denormalizeSourceCharset` | Always set charset explicitly for external files |
