# CloverDX EXT_HASH_JOIN — LLM Reference

## What it does
Equality join between a master stream (port 0) and one or more slave streams (ports 1-N).
Slaves are loaded entirely into memory as hash tables; master data is **not** cached.
No sort required on either stream. Best for large master + small-to-medium slave.

**Memory rule:** Slaves must fit in RAM. Always put the larger dataset on the master port (0), smaller datasets as slaves.

## Ports

| Port | Type | Required | Description | Metadata |
|---|---|---|---|---|
| Input 0 | master | ✓ | Drives iteration | Any |
| Input 1 | slave | ✓ | Loaded into hash table | Any |
| Input 2-N | slave | optional | Additional slaves | Any |
| Output 0 | joined | ✓ | Joined records | Any |
| Output 1 | unjoined | optional | Unmatched master records | Must match Input 0 |

**Metadata constraint:** Output port 1 metadata must be identical in field types to input port 0 (master) metadata. Field names may differ. Unmatched master records are passed through to port 1 **unchanged** — they cannot be modified within the EXT_HASH_JOIN transformation.

**Metadata propagation:** EXT_HASH_JOIN propagates metadata between input port 0 and output port 1 in both directions.

## Key Attributes

| Attribute (XML) | Req | Description |
|---|---|---|
| `joinKey` | yes | Join key expression — see format below |
| `joinType` | no | `inner` (default) / `leftOuter` / `fullOuter` |
| `transform` [attr-cdata] | one of | Inline CTL2 transformation |
| `transformURL` | one of | External CTL file. Also set `transformSourceCharset`. |
| `slaveDuplicates` | no | Default `false`. When `false`, only the **first** slave record per key is used; duplicates are silently discarded. Set `true` to allow all duplicate slave records (one output per master+slave pair). |
| `ignoreCase` | no | Default `false`. When `true`, string key field comparisons are case-insensitive (`"Smith"` == `"smith"`). |
| `hashTableSize` | no | Initial hash table capacity. Default 512. Min 512 (lower values silently use 512). Real size = nearest power-of-2 ≥ specified value. Rehashes (doubles) when 75% full. Set higher than expected record count to avoid rehashing. |

**Deprecated attributes:** `leftOuter` and `fullOuter` boolean attributes — use `joinType` instead. If `joinType` is set, it overrides these.

## joinKey Format

```
joinKey="$masterField=$slaveField"
```

The `joinKey` value consists of one block per slave, separated by `#`. Within each block, field pairs are separated by `;`, `:`, or `|` (all valid).

### Single slave
```
joinKey="$Color=$ColorRGB"
joinKey="$currency=$id"
joinKey="$state=$Code"
joinKey="$field1=$slaveField1;$field2=$slaveField2"   -- composite key
```
- `$` prefix required on both sides
- Left side = master field, right side = slave field (in this order)

### Multi-slave (ports 1, 2, ...)
```
joinKey="$masterField=$slave1Field#$masterField=$slave2Field"
```
`#` separates the key specification for each slave. Block order must match slave port order (block 1 → port 1, block 2 → port 2, ...).

If a block is empty or missing for a slave port, the **first slave's key block is reused** for that slave.

### Shorthand notation
Within a key block, two shorthands reduce repetition:

| Shorthand | Meaning |
|---|---|
| `$master=` (empty right side) | Slave field has the same name as the master field |
| `=$slave` (empty left side) | Master field is the one already mapped to `$slave` in the first slave's key block |

```
-- Full form:
joinKey="$first_name=$fname;$last_name=$lname#$last_name=$lname;$salary=$salary;$hire_date=$hdate"

-- Equivalent with shorthands:
joinKey="$first_name=$fname;$last_name=$lname#=$lname;$salary=;$hire_date=$hdate"
```
In the second block: `=$lname` means "use the master field mapped to `$lname` from slave 1" (= `$last_name`); `$salary=` means slave field is also named `$salary`.

**Important:** Different slaves can be joined to the master using **different** master fields.

## CTL Entry Point

`function integer transform()` — standard joiner/reformat signature.

```ctl
//#CTL2

// $in.0 = current master record
// $in.1 = matched slave record (null for all fields if no match in leftOuter)
// $in.2 = matched slave 2 (multi-slave joins)
function integer transform() {
    $out.0.productId = $in.0.ProductID;
    $out.0.colorName = $in.1.ColorName;
    return ALL;
}

// Called if transform() throws
// function integer transformOnError(string errorMessage, string stackTrace) {}
```

### Null-safe slave field access (leftOuter)
In `leftOuter`, `$in.1.*` fields are all null when no matching slave record exists.
Use the CTL ternary (conditional-fail) operator or `nvl()`:

```ctl
$out.0.rate    = $in.1.rate : 1.0;             // ternary: entire expression fails → use 1.0
$out.0.label   = nvl($in.1.label, "unknown");   // explicit null substitute
$out.0.amount  = ($in.0.amount / $in.1.rate) : $in.0.amount;  // guard the whole division
```

## Real Sandbox Examples

### Convert currency — leftOuter, ternary null-safe
```xml
<Node guiName="Convert Currency to Euro"
      id="CONVERT_CURRENCY_TO_EURO"
      joinKey="$currency=$id"
      joinType="leftOuter"
      type="EXT_HASH_JOIN">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    $out.0.customer_id = $in.0.customer_id;
    $out.0.amount_euro = $in.0.amount / $in.1.rate : $in.0.amount;
    $out.0.original_currency = nvl($in.1.currency, toString($in.0.currency));
    return 0;
}
]]></attr>
</Node>
```

### Enrich with reference data — leftOuter, named fields differ
```xml
<Node guiName="Lookup States"
      id="LOOKUP_STATES"
      joinKey="$state=$Code"
      joinType="leftOuter"
      type="EXT_HASH_JOIN">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    $out.0.customerID = $in.0.customerID;
    $out.0.state      = $in.0.state;
    $out.0.region     = $in.1.Region;
    $out.0.stateName  = $in.1.State;
    return ALL;
}
]]></attr>
</Node>
```

## Official Example (from docs)

### Two-stream join — inner join, records without match dropped
```ctl
//#CTL2
function integer transform() {
    $out.0.ProductID = $in.0.ProductID;
    $out.0.ColorName = $in.1.ColorName;
    return ALL;
}
```
`joinKey="$Color=$ColorRGB"`, `joinType="inner"` (default).
Master records with no slave match are dropped. Connect port 1 + set `joinType="leftOuter"` to keep them with null slave fields.

## joinType Behavior

| joinType | Matched master | Unmatched master | Unmatched slave |
|---|---|---|---|
| `inner` (default) | → port 0 | Dropped | Dropped |
| `leftOuter` | → port 0 (slave null if no match) | → port 0 (slave fields null) | Dropped |
| `fullOuter` | → port 0 | → port 0 (slave null) | → port 0 (master null) |

Port 1 (if connected) receives unmatched master records in `leftOuter`/`fullOuter` — they pass through **unchanged from master**, no CTL transformation applied.

## Hash Table Sizing

The hash table is built from slave records before master processing begins.

- Default size 512. Min 512 (lower values rounded up).
- Actual size = nearest power-of-2 ≥ specified value (e.g. `hashTableSize="1000"` → actual 1024).
- When 75% full, table doubles and rehashes — this is expensive.
- **Recommendation:** Set `hashTableSize` to slightly more than the expected slave record count to avoid rehashing. For small datasets the default is fine.

## slaveDuplicates Behavior

| `slaveDuplicates` | Slave has duplicate keys | Effect |
|---|---|---|
| `false` (default) | Yes | Only **first** slave record per key is used; rest silently discarded |
| `true` | Yes | All matching slave records used — one output record per master+slave pair |

When `slaveDuplicates="false"` and slave has duplicates, the choice of which record is "first" depends on arrival order — **not guaranteed to be stable**.

## EXT_HASH_JOIN vs EXT_MERGE_JOIN

| | EXT_HASH_JOIN | EXT_MERGE_JOIN |
|---|---|---|
| Input sort required | No | Yes — both streams |
| Slave memory constraint | Slave must fit in RAM | None — streaming |
| Best for | Large master + small slave, unsorted | Both pre-sorted, or slave too large for memory |

## Edge Port Names
- Input 0: `Port 0 (driver)` *(port label uses "driver"; official docs use "master" — same port)*
- Input 1: `Port 1 (slave)`
- Output 0: `Port 0 (out)`
- Output 1: `Port 1 (unmatched driver)`

## Mistakes

| Wrong | Correct |
|---|---|
| `joinKey="driverField=slaveField"` (no `$`) | `joinKey="$driverField=$slaveField"` — `$` required on both sides |
| `joinKey="$a=$b,$c=$d"` (comma) | Use `;` (or `:` or `\|`) to separate field pairs within a block |
| `joinKey="$a=$b;$c=$d#$e=$f"` thinking multi-slave separator is `;` | `#` separates slaves: `$a=$b#$e=$f`; `;` separates fields within one slave's block |
| Assuming slave port is 0 | Master is port 0; slaves start at port 1 |
| `$in.1.field` in leftOuter without null guard | Use ternary `$in.1.field : default` or `nvl($in.1.field, default)` |
| `slaveDuplicates="false"` expecting all duplicates to join | When false, only **first** matching slave record is used — rest discarded |
| `slaveDuplicates="true"` for "unique only" enforcement | `slaveDuplicates` controls whether duplicates are allowed, not filtered out |
| Large slave dataset | Slave must fit in RAM — put large data on master (port 0), use EXT_MERGE_JOIN for large slaves |
| Using deprecated `leftOuter="true"` attribute | Use `joinType="leftOuter"` — the boolean attributes are deprecated |
| Modifying unmatched records on port 1 | Port 1 passes master records through unchanged — CTL cannot modify them |
| External CTL without `transformSourceCharset` | Always set charset explicitly for external files |
