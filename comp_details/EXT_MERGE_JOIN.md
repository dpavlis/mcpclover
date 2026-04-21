# CloverDX EXT_MERGE_JOIN — LLM Reference

## What it does
Sort-merge equality join. Both master (port 0) and all slaves (ports 1-N) must be pre-sorted on their respective join key fields. No memory constraint — processes all streams in a single streaming pass. Best when both inputs are already sorted or when the slave is too large for EXT_HASH_JOIN's hash table.

## Ports

| Port | Type | Required | Description | Metadata |
|---|---|---|---|---|
| Input 0 | master | ✓ | Drives iteration — must be sorted | Any |
| Input 1 | slave | ✓ | Must be sorted | Any |
| Input 2-N | slave | optional | Additional slaves — must be sorted | Any |
| Output 0 | joined | ✓ | Joined records | Any |
| Output 1 | unjoined | optional | Unmatched master records | Must match Input 0 |

**Metadata constraint:** Output port 1 metadata must have identical field types to input port 0 (master). Field names may differ. EXT_MERGE_JOIN propagates metadata between input port 0 and output port 1 in both directions. Unmatched master records are passed through to port 1 **unchanged** — the CTL transformation cannot modify them.

## Key Attributes

| Attribute (XML) | Req | Default | Description |
|---|---|---|---|
| `joinKey` | yes | — | Join key expression — see format below |
| `joinType` | no | `inner` | `inner` / `leftOuter` / `fullOuter` |
| `transform` [attr-cdata] | one of | — | Inline CTL2 transformation |
| `transformURL` | one of | — | External CTL file. Also set `transformSourceCharset`. |
| `slaveDuplicates` | no | `true` | When `true`: all matching slave records join (slave duplicates allowed). When `false`: only the **last** slave record per key is used. |

**Deprecated attributes** (use modern alternatives instead):
- `leftOuter` / `fullOuter` boolean → use `joinType` attribute (if both set, `joinType` wins)
- `caseSensitive` → use sort direction suffixes in `joinKey`
- `ascendingInputs` → use `(a)` / `(d)` suffixes in `joinKey`

## joinKey Format

EXT_MERGE_JOIN's `joinKey` **always starts with the master key block**, followed by one slave key block per slave port, all separated by `#`.

```
joinKey="$masterField1;$masterField2#$slave1Field1;$slave1Field2"
```

- First block = master field names (port 0)
- Second block = slave 1 field names (port 1), positionally mapped to master fields
- Third block = slave 2 field names (port 2), positionally mapped to master fields
- `#` separates blocks
- `;`, `:`, or `|` are all valid field separators within a block

**This differs from EXT_HASH_JOIN**, which has no master block and uses `$master=$slave` equality syntax. EXT_MERGE_JOIN uses positional mapping with no `=` sign.

### Sort direction annotation

Each field can carry a sort direction suffix that must match the upstream sort:

```
joinKey="$CustomerId(a)#$Id(a)"
```

- `(a)` = ascending — matches `sortKey="CustomerId(a)"`
- `(d)` = descending — matches `sortKey="CustomerId(d)"`

If omitted, ascending is assumed.

### Multi-slave join key

```
joinKey="$first_name;$last_name#$fname;$lname#$f_name;$l_name"
```

- Master key (port 0): `$first_name`, `$last_name`
- Slave 1 key (port 1): `$fname`, `$lname` — positionally mapped to master fields
- Slave 2 key (port 2): `$f_name`, `$l_name` — positionally mapped to master fields

**Constraints on multi-slave joins:**
- The **same master fields** must be used for joining with all slaves. If you need different master fields per slave, use EXT_HASH_JOIN instead.
- The **number of key fields must be equal** across master and all slaves.

## Case Sensitivity

**Default: case-insensitive** — `"Smith"` equals `"smith"` by default.

This is the **opposite default** from EXT_HASH_JOIN (which is case-sensitive by default).

To enforce case-sensitive comparison, use the deprecated `caseSensitive="true"` attribute. The modern approach is to pre-normalize case in upstream transforms.

## CTL Entry Point

`function integer transform()` — same signature as EXT_HASH_JOIN and REFORMAT.

```ctl
//#CTL2

// $in.0 = current master record
// $in.1 = matched slave record (null for all fields if no match in leftOuter)
function integer transform() {
    $out.0.transaction_id = $in.0.TransactionId;
    $out.0.customer_id    = $in.1.Id;
    $out.0.amount         = $in.0.Amount;
    $out.0.customer_name  = $in.1.LastName;
    return ALL;
}

// function integer transformOnError(string errorMessage, string stackTrace) {}
```

### Null-safe slave field access (leftOuter)
When no slave record matches, `$in.1.*` fields are all null:
```ctl
$out.0.region = $in.1.Region : "UNKNOWN";           // ternary: expression fails → fallback
$out.0.label  = nvl($in.1.label, "unmatched");       // explicit null substitute
```

## Data Merging Mechanics

The component advances both sorted streams in lockstep using key comparison:

| Comparison | Action |
|---|---|
| master key == slave key | Records joined → transformation called |
| slave key < master key | Advance slave (shift slave one step forward) |
| slave key > master key | Advance master (shift master one step forward) |

When `slaveDuplicates="true"` (default), a group of consecutive slave records with the same key value is treated as a unit and stored in memory temporarily. **If the group is very large, it spills to disk.** All slave records in the group are joined with each matching master record.

When `slaveDuplicates="false"`, only the **last** slave record in a consecutive same-key group is used — the earlier ones are discarded.

## Required Upstream Sort Pattern

Both master AND slave must be pre-sorted on the exact fields specified in their key blocks, in the exact sort order annotated (`(a)` or `(d)`).

```xml
<!-- Sort master -->
<Node id="SORT_MASTER" sortKey="CustomerId(a)" type="FAST_SORT"/>
<!-- Sort slave -->
<Node id="SORT_SLAVE"  sortKey="Id(a)"         type="FAST_SORT"/>

<!-- Both feeds into join -->
<Node id="JOIN" joinKey="$CustomerId(a)#$Id(a)" joinType="leftOuter" type="EXT_MERGE_JOIN"/>

<Edge fromNode="SORT_MASTER:0" outPort="Port 0 (out)" toNode="JOIN:0" inPort="Port 0 (driver)"/>
<Edge fromNode="SORT_SLAVE:0"  outPort="Port 0 (out)" toNode="JOIN:1" inPort="Port 1 (slave)"/>
```

If input is already sorted (e.g. `DB_INPUT_TABLE` with `ORDER BY`), skip the sort component — document this assumption in `plan_graph` risks[].

## Real Sandbox Examples

### Match transactions with customers — leftOuter, sort direction annotated
```xml
<Node guiName="Match Transactions with Customer"
      id="MATCH_TRANSACTIONS_WITH_CUSTOMER"
      joinKey="$CustomerId(a)#$Id(a);"
      joinType="leftOuter"
      type="EXT_MERGE_JOIN">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    $out.0.transaction_id      = $in.0.TransactionId;
    $out.0.customer_id         = $in.1.Id;
    $out.0.amount              = $in.0.Amount;
    $out.0.currency            = $in.0.CurrencyId;
    $out.0.customer_last_name  = $in.1.LastName;
    $out.0.customer_first_name = $in.1.FirstName;
    return 0;
}
]]></attr>
</Node>
```
Note: trailing `;` after `$Id(a)` is a harmless artifact from the visual editor — the key is `$CustomerId(a)` (master) # `$Id(a)` (slave 1).

## joinType Behavior

| joinType | Matched master | Unmatched master | Unmatched slave |
|---|---|---|---|
| `inner` (default) | → port 0 | Dropped | Dropped |
| `leftOuter` | → port 0 (slave null if no match) | → port 0 (slave fields null) | Dropped |
| `fullOuter` | → port 0 | → port 0 (slave null) | → port 0 (master null) |

Port 1 (if connected) receives unmatched master records — they pass through **unchanged**, CTL cannot modify them.

## slaveDuplicates — Key Difference from EXT_HASH_JOIN

| | EXT_MERGE_JOIN | EXT_HASH_JOIN |
|---|---|---|
| Default | `true` (duplicates allowed) | `false` (duplicates not allowed) |
| When `false` | Keeps **last** slave record per key | Keeps **first** slave record per key |
| Large duplicate sets | Spills to disk automatically | Must fit in RAM (hash table) |

## EXT_MERGE_JOIN vs EXT_HASH_JOIN

| | EXT_MERGE_JOIN | EXT_HASH_JOIN |
|---|---|---|
| Input sort required | Yes — master and all slaves | No |
| Slave memory constraint | None — can spill to disk | Slave must fit in RAM |
| Case sensitivity default | **Case-insensitive** | **Case-sensitive** |
| `slaveDuplicates` default | `true` | `false` |
| Multi-slave master key | Must be **same** for all slaves | Can be **different** per slave |
| joinKey format | `master#slave1#slave2` (positional) | `$m=$s1#$m=$s2` (equality pairs) |
| Best for | Both pre-sorted, or large slave | Unsorted, or small slave in RAM |

## Edge Port Names
- Input 0: `Port 0 (driver)` *(port label uses "driver"; official docs use "master")*
- Input 1: `Port 1 (slave)`
- Output 0: `Port 0 (out)`
- Output 1: `Port 1 (unmatched driver)`

## Mistakes

| Wrong | Correct |
|---|---|
| Missing upstream sort | Both master AND slave must be sorted on their key fields |
| Sort key ≠ joinKey fields | `sortKey` field names must match the fields in the corresponding joinKey block |
| Sort direction mismatch | `(a)` in joinKey must match `(a)` in sortKey |
| `joinKey="$a=$b#$c=$d"` (equality syntax) | EXT_MERGE_JOIN uses positional blocks: `joinKey="$a#$c"` — no `=` sign |
| `joinKey="$slave1#$slave2"` (no master block) | First block is always master: `joinKey="$master#$slave1#$slave2"` |
| Assuming same `slaveDuplicates` default as EXT_HASH_JOIN | EXT_MERGE_JOIN default is `true`; EXT_HASH_JOIN default is `false` |
| Assuming `slaveDuplicates=false` keeps first record | EXT_MERGE_JOIN keeps **last** when false; EXT_HASH_JOIN keeps **first** when false |
| Assuming case-sensitive comparison | EXT_MERGE_JOIN is case-insensitive by default (unlike EXT_HASH_JOIN) |
| Different master fields per slave | EXT_MERGE_JOIN requires the same master fields for all slaves — use EXT_HASH_JOIN for per-slave master fields |
| Using deprecated `leftOuter="true"` | Use `joinType="leftOuter"` |
| Modifying unmatched records on port 1 | Port 1 passes master records through unchanged — CTL cannot modify them |
| External CTL without `transformSourceCharset` | Always set charset explicitly for external files |
