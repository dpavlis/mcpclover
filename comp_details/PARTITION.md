# CloverDX PARTITION — LLM Reference

## What it does
Routes each input record **unchanged** to exactly one output port. Three routing modes:
1. **CTL** (`partitionSource`) — custom `getOutputPort()` logic
2. **Ranges + Partition key** — value-range routing or hash routing
3. **RoundRobin** — when no configuration is set at all

**High-performance constraint:** PARTITION does NOT transform records. Input and output records must be **identical in fields** (names can differ, but field structure must match). Attempting to modify records results in a runtime error. Use REFORMAT/Map instead if modification is needed.

## Ports
- Input 0: required
- Output 0: required. Output 1-N: optional.
Metadata **auto-propagated** in both directions. Input and output metadata must have identical fields (record name can differ).

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `partitionSource` [attr-cdata] | one of | Inline CTL2 — `getOutputPort()` returns port number |
| `partitionURL` | one of | External CTL file. Set `partitionSourceCharset` when using this. |
| `partitionClass` | one of | Java class implementing `PartitionFunction` |
| `ranges` | one of | Value ranges — see Ranges section |
| `partitionKey` | one of | Field name(s) for hash-based routing |

**Priority:** CTL transformation (`partitionSource`/`partitionURL`/`partitionClass`) takes precedence — when any CTL attribute is set, `ranges` and `partitionKey` are **ignored**.

## Routing Modes

### Mode 1: CTL (`partitionSource`)

Define routing logic in `getOutputPort()`. Most flexible — handles any conditional routing.

```ctl
//#CTL2

// Called once per input record.
// $in.0 accessible here. $out.N NOT accessible (records routed unchanged).
// Returns: port number (0-based), or -1 (SKIP = discard), or <= -2 (error)
function integer getOutputPort() {
    switch ($in.0.logType) {
        case 'JOB_STATUS': return 0;
        case 'JOB_AUDIT':  return 1;
        default:           return 2;
    }
}

// Optional — called if getOutputPort() throws an exception.
// Returns: port number (same semantics as getOutputPort()).
// $in.0 accessible here.
function integer getOutputPortOnError(string errorMessage, string stackTrace) {
    printErr(errorMessage);
    return 2;   // fallback port
}

// Optional — called once before any record is processed. Receives port count.
// function void init(integer partitionCount) {}

// Optional — called when getOutputPort() or getOutputPortOnError() returns <= -2.
// function string getMessage() { return "custom error"; }

// Optional — allocate resources per graph run (released in postExecute)
// function void preExecute() {}
// function void postExecute() {}
```

### Function signatures and access rules

| Function | `$in.0` | `$out.N` | Notes |
|---|---|---|---|
| `init(integer partitionCount)` | ✗ | ✗ | `partitionCount` = number of output ports |
| `getOutputPort()` | ✓ | ✗ | Mandatory |
| `getOutputPortOnError(msg, trace)` | ✓ | ✗ | Optional error handler |
| `getMessage()` | ✗ | ✗ | Called when return ≤ -2 |
| `preExecute()` / `postExecute()` | ✗ | ✗ | Resource lifecycle |

**`$out.N` is not accessible in any function** — records are routed as-is, never modified.

### Return values for `getOutputPort()`

| Return | Meaning |
|---|---|
| 0, 1, 2, ... | Route to that output port number |
| Port number with no connected edge | Record **silently discarded** (no error) |
| `-1` (SKIP) | Discard record |
| `<= -2` | Error — calls `getMessage()` if defined |

### Mode 2: Ranges

Route records by field value ranges without CTL. Requires both `ranges` and `partitionKey` to be set together.

**Bracket notation:**
- `<` = inclusive lower bound (≥)
- `>` = inclusive upper bound (≤)
- `(` = exclusive lower bound (>)
- `)` = exclusive upper bound (<)
- `,` as the first or last character inside a range means unbounded (−∞ or +∞)

```
ranges="<1,9)(,31.12.2008);<1,9)<31.12.2008,);<9,)(,31.12.2008);<9,)<31.12.2008)"
```
Each semicolon-separated block defines one output port (port 0, 1, 2, ...). Within a block, individual field intervals are concatenated without delimiters.

`partitionKey` specifies which fields the range intervals apply to (semicolon-separated). Range field order must match `partitionKey` field order.

### Mode 3: Partition key only (hash routing)

When `partitionKey` is set but `ranges` is not, records are distributed by hash:

```xml
<Node id="PARTITION" type="PARTITION" partitionKey="customerId"/>
```

- Records with the same `customerId` always go to the same output port (deterministic)
- Distribution is `hash(key fields) % number_of_output_ports`
- Use for load balancing or parallel processing pipelines

### Mode 4: RoundRobin

When **no** CTL attribute, `ranges`, or `partitionKey` is set, PARTITION distributes records using a **round-robin** algorithm — each successive record goes to the next output port in sequence.

```xml
<!-- No attributes needed — just connect multiple output ports -->
<Node id="PARTITION" type="PARTITION"/>
```
Use case: split input equally across N downstream workers/writers.

## Real Sandbox Examples

### DWHExample — route by log type (switch/case CTL)
```xml
<Node guiName="Log type" id="LOG_TYPE" type="PARTITION">
    <attr name="partitionSource"><![CDATA[//#CTL2
function integer getOutputPort() {
    switch ($in.0.logType) {
        case 'JOB_STATUS':  return 0;
        case 'JOB_AUDIT':   return 1;
        default:            return 2;
    }
}
]]></attr>
</Node>
```

### MiscExamples — data quality routing (null check + type check)
```xml
<Node guiName="Route Records by logic" id="ROUTE_RECORDS_BY_LOGIC" type="PARTITION">
    <attr name="partitionSource"><![CDATA[//#CTL2
function integer getOutputPort() {
    if (isnull($in.0.customer_id)) return 0;
    if (isNumber($in.0.original_currency)) return 1;
    return 2;
}
]]></attr>
</Node>
```

### Official example — even/odd routing with error fallback
```ctl
//#CTL2

function integer getOutputPort() {
    return $in.0.id % 2;   // 0 = even, 1 = odd
}

function integer getOutputPortOnError(string errorMessage, string stackTrace) {
    return 2;   // unknown/error → port 2
}
```

## Using PARTITION as a Filter

PARTITION can replace EXT_FILTER when you need more than 2 output paths or more complex routing expressions. Neither PARTITION nor EXT_FILTER allow modifying records.

```ctl
// Route valid records to port 0, invalid to port 1, unknown to port 2
function integer getOutputPort() {
    if (isnull($in.0.email) || !contains($in.0.email, "@")) return 1;
    if (isnull($in.0.country)) return 2;
    return 0;
}
```

## Common Patterns

### Three-way quality split
```
READER → PARTITION → port 0: null customer_id  → ERROR_WRITER
                   → port 1: invalid currency   → LOOKUP_WRITER
                   → port 2: valid              → DWH_WRITER
```

### Equal split for parallel loading (RoundRobin)
```
READER → PARTITION (no config) → port 0: DB_OUTPUT_TABLE (writer 1)
                               → port 1: DB_OUTPUT_TABLE (writer 2)
                               → port 2: DB_OUTPUT_TABLE (writer 3)
```

### Route by field threshold
```ctl
function integer getOutputPort() {
    if ($in.0.score >= 90) return 0;
    if ($in.0.score >= 50) return 1;
    return 2;
}
```

## Edge Port Names
- Input: `Port 0 (in)`
- Outputs: `Port 0 (out)`, `Port 1 (out)`, `Port 2 (out)`, ... (0-based)

## Decision Guide

| Need | Use |
|---|---|
| Route by complex CTL logic | `partitionSource` |
| Route by value ranges | `ranges` + `partitionKey` |
| Load-balance by key field (same key → same port) | `partitionKey` only (hash mode) |
| Distribute records evenly across N outputs | No config (RoundRobin) |
| Two-way split (pass/reject) | EXT_FILTER (simpler for boolean filter) |
| Route AND transform | REFORMAT with multiple return ports |

## Mistakes

| Wrong | Correct |
|---|---|
| `function integer transform()` | `function integer getOutputPort()` — different entry point name |
| Writing `$out.N` in CTL | `$out.N` not accessible in any PARTITION function — it's a high-performance routing component; modifying records causes runtime error |
| Trying to modify records | PARTITION cannot modify records at all; use Map/REFORMAT instead |
| `[` for inclusive lower bound in ranges | Use `<` for inclusive lower bound; `(` for exclusive |
| `]` for inclusive upper bound in ranges | Use `>` for inclusive upper bound; `)` for exclusive |
| Setting both CTL and `ranges`/`partitionKey` | CTL takes priority — `ranges` and `partitionKey` are silently ignored |
| Assuming unconnected port causes error | Records sent to unconnected port are silently discarded |
| Using PARTITION expecting metadata change | Input and output metadata fields must be identical |
| External CTL without `partitionSourceCharset` | Always set charset explicitly for external files |
