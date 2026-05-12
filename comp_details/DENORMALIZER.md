# CloverDX DENORMALIZER — LLM Reference

## What it does
Collapses N consecutive same-key input records into exactly 1 output record. Input MUST be sorted on key field(s). Use for: string concatenation across rows, value collection per group, pivoting repeated rows into columns.

## Ports
- Input 0: required — sorted records (any metadata)
- Output 0: required — one record per group (any metadata)

No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `key` | one of | Semicolon/colon/pipe-separated field names defining group boundaries. |
| `groupSize` | one of | Fixed integer — every N records form one group. Takes priority over `key` if both set. Input count must be multiple of groupSize unless `incompleteGroupAllowed="true"`. |
| `denormalize` [attr-cdata] | one of | Inline CTL2 transformation. |
| `denormalizeURL` | one of | Path to external CTL file. Set `denormalizeSourceCharset` too. |
| `order` | no | `Auto` (default) / `Asc` / `Desc` / `Ignore`. `Ignore` = contiguous but not globally sorted. |
| `equalNULL` | no | Default `true`. NULL key values treated as equal. |
| `incompleteGroupAllowed` | no | Default `false`. Allow last group shorter than `groupSize`. |

If neither `key` nor `groupSize` is set, all records form one group.

## CTL Entry Points

`append()` and `transform()` are mandatory. `clean()` is mandatory when using module-level variables.

```ctl
//#CTL2

// Module-level variables persist across append() calls within a group. Reset in clean().
string[] products = [];
string companyName;

// Called once per input record. $in.0 accessible here only.
function integer append() {
    append(products, $in.0.product);
    companyName = $in.0.companyName;
    return OK;
}

// Called once after all append() calls for the group. $out.0 accessible here only.
function integer transform() {
    $out.0.companyName = companyName;
    $out.0.products = join(",", products);
    return OK;
}

// Called after transform(). Reset all module-level variables here.
function void clean() {
    clear(products);
    companyName = null;
}

// function boolean init() { return true; }  -- once before first record
// function integer appendOnError(string errorMessage, string stackTrace) { return OK; }
//   returns: positive = ignored; 0 = continue (to next record, or transform() if last of group); negative = error
// function integer transformOnError(string errorMessage, string stackTrace) { return OK; }
// function string getMessage() { return "custom error"; }  -- called when any fn returns <= -2
// function void preExecute() {}  -- once per run before processing
// function void postExecute() {} -- once per run after all groups
```

## Return Values

| Function | Non-negative | SKIP | <= -2 |
|---|---|---|---|
| `append()` | Continue accumulating | — | Abort (calls `getMessage()`) |
| `transform()` | Emit output record | Suppress output, continue | Abort (calls `getMessage()`) |
| `appendOnError()` | Positive = ignored; 0 = continue | — | Error |
| `transformOnError()` | Emit output record | Suppress output | Error |

`ALL` (= 0) in `transform()` is equivalent to `OK`.

## $in.0 / $out.0 Access — violations throw NPE

| Function | `$in.0` | `$out.0` |
|---|---|---|
| `init()` | ✗ | ✗ |
| `append()` | ✓ | ✗ |
| `appendOnError()` | ✓ | ✗ |
| `transform()` | ✗ | ✓ |
| `transformOnError()` | ✗ | ✓ |
| `clean()` | ✗ | ✗ |

## Examples

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
`key="companyName"`. Input sorted by companyName.

### groupSize — fixed N records per group
```ctl
//#CTL2
integer groupNumber;
string[] names;

function boolean init() {
    groupNumber = 1;    // runs once — use for one-time initialization
    return true;
}
function integer append() {
    append(names, $in.0.name);
    return OK;
}
function integer transform() {
    $out.0.groupNo = groupNumber;
    $out.0.members = join(",", names);
    groupNumber++;      // increment in transform(), not clean()
    return OK;
}
function void clean() {
    clear(names);       // groupNumber intentionally not reset here
}
```
`groupSize="3"` + `incompleteGroupAllowed="true"`.

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

### MiscExamples — capture base record, mark failing fields
```xml
<Node id="DENORMALIZER" key="id(a)" type="DENORMALIZER">
    <attr name="denormalize"><![CDATA[//#CTL2
rejected_contacts_csv inputR;
list[string] validationErrors;

function integer append() {
    if (isNull(inputR, "id")) {
        inputR.* = $in.0.*;
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
key="fieldName"
key="field1;field2"       -- composite (semicolon, colon, or pipe)
key="recordNo(a)"         -- (a) ascending / (d) descending — must match upstream sortKey
```

## Upstream Sort Requirement

Same-key records must be **adjacent**. Non-contiguous same-key runs produce **separate output records** — most common silent correctness bug.

```xml
<Node id="SORT"         sortKey="recordNo(a)" type="FAST_SORT"/>
<Node id="DENORMALIZER" key="recordNo(a)"     type="DENORMALIZER"/>
```

`order="Ignore"` — use when groups are naturally contiguous but not globally sorted.

## Validator Error Collapse Pattern

```
READER → VALIDATOR(root lazyEvaluation=false, sub-group lazyEvaluation=true)
  port 1 (invalid) → FAST_SORT(sortKey="recordNo(a)") → DENORMALIZER(key="recordNo(a)") → ERROR_WRITER
```

## Decision Guide

| Need | Use |
|---|---|
| N same-key rows → 1 row | DENORMALIZER `key` |
| Every N rows → 1 row | DENORMALIZER `groupSize` |
| All rows → 1 row | DENORMALIZER (neither) |
| 1 group → M rows | ROLLUP |

## Mistakes

| Wrong | Correct |
|---|---|
| Module-level variables without `clean()` | State bleeds between groups |
| `$out.0` in `append()` | NPE — only in `transform()` |
| `$in.0` in `transform()` | NPE — only in `append()` |
| `$in.0` or `$out.0` in `clean()` | NPE — neither accessible |
| Input not sorted on key | Add FAST_SORT upstream with matching `sortKey` |
| Same-key records not adjacent | Sort input; non-contiguous runs → separate output records |
| `key` and `groupSize` both set | `groupSize` takes priority |
| `incompleteGroupAllowed` omitted with `groupSize` | Graph fails if count not multiple of groupSize |
| Counter incremented in `clean()` | Increment in `transform()` — `clean()` resets accumulated values only |
| External CTL without `denormalizeSourceCharset` | Always set charset explicitly |
