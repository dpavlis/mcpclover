# CloverDX ROLLUP — LLM Reference

## What it does
Transforms input records into 0..N output records per group. Input can be sorted or unsorted (`sortedInput`). Use for: variable output count per group, routing to multiple output ports, per-record emit, splitting multivalue fields.

Key distinction from DENORMALIZER: ROLLUP emits **0..N records per group**. DENORMALIZER always emits exactly **1**.

## Ports
- Input 0: required (any metadata)
- Output 0: required (any metadata)
- Output 1–N: optional; each port can have different metadata

No metadata propagation. No metadata templates.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `groupKey` | no | Semicolon-separated field names for group boundaries. Omit = all records one group. |
| `groupAccumulator` | no | Metadata ID for the per-group accumulator record. Omit = `VoidMetadata` (no fields). |
| `transform` [attr-cdata] | one of | Inline CTL2 transformation. |
| `transformURL` | one of | External CTL file path. Set `transformSourceCharset` too. |
| `transformClass` | one of | Java class implementing `RecordRollup`. |
| `transformSourceCharset` | no | Encoding of external CTL file. Default: `DEFAULT_SOURCE_CODE_CHARSET`. |
| `sortedInput` | no | Default `true`. `false` = buffer all records internally (memory-intensive). |
| `equalNULL` | no | Default `true`. NULL key values treated as equal. |

## CTL Entry Points

Mandatory: `initGroup`, `updateGroup`, `finishGroup`, and at least one of `updateTransform` / `transform`. Stub the unused output function with `return SKIP`.

**`updateTransform` vs `transform`:**

| | `updateTransform` | `transform` |
|---|---|---|
| Triggered by | `updateGroup()` returning `true` | `finishGroup()` returning `true` |
| Called | Loop per qualifying input record | Loop per group |
| `$in.0` | ✓ triggering record | ✓ last record of group |
| Use for | Emit rows per individual input record | Emit summary rows after full group accumulated |

Both use `counter` (0-based); return `SKIP` to end the loop.

```ctl
//#CTL2

// Use groupAccumulator for group state — no module-level variables needed.
// Module-level variables are valid for graph-wide state (e.g. cross-group counters).

// First record of each group. $in.0 accessible.
function void initGroup(companyCustomers groupAccumulator) {
    groupAccumulator.count = 0;
    groupAccumulator.totalFreight = 0;
}

// Every record (incl. first and last). $in.0 accessible.
// true → call updateTransform(); false → skip per-record output
function boolean updateGroup(companyCustomers groupAccumulator) {
    groupAccumulator.count++;
    groupAccumulator.totalFreight = groupAccumulator.totalFreight + $in.0.Freight;
    return true;
}

// Last record of group. $in.0 accessible.
// true → call transform(); false → skip group output
function boolean finishGroup(companyCustomers groupAccumulator) {
    groupAccumulator.avgFreight = groupAccumulator.totalFreight / groupAccumulator.count;
    return true;
}

// Loop after each updateGroup()=true. counter 0-based. $in.0 + $out.N accessible.
function integer updateTransform(integer counter, companyCustomers groupAccumulator) {
    if (counter > 0) return SKIP;
    $out.0.customer = $in.0.CustomerID;
    $out.0.freight  = $in.0.Freight;
    return ALL;
}

// Loop after finishGroup()=true. counter 0-based. $in.0 (last record) + $out.N accessible.
function integer transform(integer counter, companyCustomers groupAccumulator) {
    if (counter > 0) return SKIP;
    $out.1.ShipCountry = $in.0.ShipCountry;
    $out.1.Count       = groupAccumulator.count;
    $out.1.AvgFreight  = groupAccumulator.avgFreight;
    return ALL;
}

// function boolean init() { return true; }  -- once before first record
// OnError variants — same signature as non-error counterpart + (string errorMessage, string stackTrace):
// function void    initGroupOnError(string errorMessage, string stackTrace, companyCustomers groupAccumulator) {}
// function boolean updateGroupOnError(string errorMessage, string stackTrace, companyCustomers groupAccumulator) { return false; }
// function boolean finishGroupOnError(string errorMessage, string stackTrace, companyCustomers groupAccumulator) { return false; }
// function integer updateTransformOnError(string errorMessage, string stackTrace, integer counter, companyCustomers groupAccumulator) { return SKIP; }
// function integer transformOnError(string errorMessage, string stackTrace, integer counter, companyCustomers groupAccumulator) { return SKIP; }
// function string getMessage() { return "custom error"; }  -- called when any fn returns <= -2
// function void preExecute()  {}
// function void postExecute() {}
```

## Return Values

**Boolean-returning:**

| Function | `true` | `false` |
|---|---|---|
| `updateGroup()` | Call `updateTransform()` | Skip per-record output |
| `updateGroupOnError()` | Call `updateTransform()` | **Jump to `finishGroup()` (skips remaining records)** |
| `finishGroup()` | Call `transform()` | Skip group output, next group |
| `finishGroupOnError()` | Call `transform()` | **Skip to next group (bypasses `transform`)** |

**Integer-returning** (return value = output port index; `ALL` = 0 = port 0):

| Function | Non-negative | `SKIP` | <= -2 |
|---|---|---|---|
| `updateTransform()` | Emit to port | End loop for this record | Abort (`getMessage()`) |
| `updateTransformOnError()` | Emit to port | **Jump to `finishGroup()`** | Abort |
| `transform()` | Emit to port | End loop for this group | Abort (`getMessage()`) |
| `transformOnError()` | Emit to port | End loop for this group | Abort |

## $in.0 / $out.N / accumulator Access — violations throw NPE

| Function | `$in.0` | `$out.N` | accumulator |
|---|---|---|---|
| `init()` | ✗ | ✗ | ✗ |
| `initGroup()` / `initGroupOnError()` | ✓ | ✗ | ✓ |
| `updateGroup()` / `updateGroupOnError()` | ✓ | ✗ | ✓ |
| `finishGroup()` / `finishGroupOnError()` | ✓ (last record) | ✗ | ✓ |
| `updateTransform()` / `updateTransformOnError()` | ✓ (triggering record) | ✓ | ✓ |
| `transform()` / `transformOnError()` | ✓ (last record) | ✓ | ✓ |
| `preExecute()` / `postExecute()` | ✗ | ✗ | ✗ |

## Examples

### Merging incomplete records — last-write-wins
`groupKey="name"`, `groupAccumulator="updateRecord"` (fields: name, email, phoneNumber)

```ctl
//#CTL2
function void initGroup(updateRecord groupAccumulator) {
    groupAccumulator.* = $in.0.*;
}
function boolean updateGroup(updateRecord groupAccumulator) {
    if (!isnull($in.0.email))       { groupAccumulator.email = $in.0.email; }
    if (!isnull($in.0.phoneNumber)) { groupAccumulator.phoneNumber = $in.0.phoneNumber; }
    return false;
}
function boolean finishGroup(updateRecord groupAccumulator) { return true; }
function integer updateTransform(integer counter, updateRecord groupAccumulator) {
    raiseError("Not implemented");
}
function integer transform(integer counter, updateRecord groupAccumulator) {
    if (counter > 0) return SKIP;
    $out.0.* = groupAccumulator.*;
    return ALL;
}
```

### Splitting multivalue field — fan-out to port 1
`groupKey="name"`, `groupAccumulator="users"` (fields: name, group, email[])
Port 0: name + group (1 row per person). Port 1: name + email (1 row per address).

```ctl
//#CTL2
function void initGroup(users groupAccumulator) { return; }
function boolean updateGroup(users groupAccumulator) {
    groupAccumulator.* = $in.0.*;
    return true;
}
function boolean finishGroup(users groupAccumulator) { return true; }
function integer updateTransform(integer counter, users groupAccumulator) {
    if (counter >= length(groupAccumulator.email)) return SKIP;
    $out.1.name  = $in.0.name;
    $out.1.email = groupAccumulator.email[counter];
    return 1;
}
function integer transform(integer counter, users groupAccumulator) {
    if (counter > 0) return SKIP;
    $out.0.name  = $in.0.name;
    $out.0.group = $in.0.group;
    return 0;
}
```

## Decision Guide

| Need | Use |
|---|---|
| N same-key rows → 1 row | DENORMALIZER `key` |
| Every N rows → 1 row | DENORMALIZER `groupSize` |
| All rows → 1 row | DENORMALIZER (neither) |
| Group → variable rows | **ROLLUP** |
| Per-record output + group summary | **ROLLUP** (`updateTransform` + `transform`) |
| Multiple output ports | **ROLLUP** |

## Sorted vs Unsorted Input

| `sortedInput` | Behavior |
|---|---|
| `true` (default) | Streaming; same-key records must be adjacent |
| `false` | Buffers all records internally; memory-intensive for large datasets |

## Mistakes

| Wrong | Correct |
|---|---|
| Module-level variables for group state | Use accumulator — scoped per group automatically |
| `$out.N` in `initGroup` / `updateGroup` / `finishGroup` | NPE — output only in `updateTransform` / `transform` |
| `groupAccumulator` in `init()` | NPE — not accessible in `init()` |
| No `return SKIP` in `updateTransform` / `transform` | Infinite loop |
| Both `updateTransform` and `transform` unimplemented | Stub unused one with `return SKIP` |
| `updateGroup` always `false` + `finishGroup` always `false` | No output emitted |
| Unsorted input with `sortedInput=true` | Non-adjacent same-key records → separate groups; sort upstream |
| External CTL without `transformSourceCharset` | Always set charset explicitly |
| Return value > connected port count | Graph fails at runtime |
| Manually incrementing `counter` | `counter` is provided automatically — do not increment |
