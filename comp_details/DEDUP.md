# CloverDX DEDUP — LLM Reference

## What it does
Removes duplicate records, or takes the first/last N records. Two modes driven by whether `dedupKey` is set:
- **With `dedupKey`**: groups records by key value; keeps N records per group (or only unique records).
- **Without `dedupKey`**: behaves like Unix `head`/`tail` — takes `noDupRecord` records from the start or end of the entire input.

Input does NOT need to be globally sorted — groups only need to be **contiguous** (partially sorted).

## Ports
- Input 0: required
- Output 0: required — unique/kept records
- Output 1: optional — duplicate/discarded records
Metadata auto-propagated.

## Key Attributes

| Attribute (XML) | Default | Description |
|---|---|---|
| `dedupKey` | — | Field name(s) defining groups. Adjacent records with the same key value form one group. If not set, entire input is treated as one group (head/tail mode). |
| `keep` | `First` | Which records to preserve: `First` (from start of group), `Last` (from end), or `Unique` (only records with no duplicates at all). When `Unique`, `noDupRecord` is ignored. |
| `noDupRecord` | `1` | Max records to keep per group (or from total input when no `dedupKey`). Ignored when `keep="Unique"`. |
| `sorted` | `true` | `true` = streaming mode (sorted/contiguous input required). `false` = unsorted/in-memory mode (input needs no ordering). |
| `equalNULL` | `true` | Treat NULL key values as equal (same group). Set `false` to treat NULLs as distinct. |

## Sorted vs Unsorted Mode

### Sorted mode (default: `sorted="true"`)
- Input groups must be **contiguous** — records with the same key adjacent to each other. Does NOT require global sort order across groups (only within each group's run).
- Streaming — no memory constraint. Suitable for large datasets with many distinct key values.
- Sort direction on the `dedupKey` field: `Auto` (detected from first two groups), `Ascending`, `Descending`, or `Ignore` (groups contiguous but unordered).

### Unsorted mode (`sorted="false"`)
- No input ordering required at all.
- Loads records into memory — **only suitable for datasets with few distinct key values**.
- Memory cost depends on `noDupRecord` and `keep`: lower `noDupRecord` = less memory; keeping `First` records uses less memory than keeping `Last`.
- **Output order is not guaranteed** — see table below.

### Output order guarantees in unsorted mode

| `keep` value | Port 0 (kept) order | Port 1 (duplicates) order |
|---|---|---|
| `First` | Preserved | Preserved |
| `Last` | Order within group preserved | Not guaranteed |
| `Unique` | Preserved | Arbitrary |

## dedupKey Format

```
dedupKey="fieldName"              -- single field
dedupKey="field1;field2"          -- composite key (semicolon-separated)
dedupKey="ruleName(a)"            -- with ascending sort direction hint
dedupKey="recordNo(d)"            -- descending sort direction hint
```

Sort direction suffix `(a)` / `(d)` must match the upstream sort when using sorted mode.

## keep="Unique" Mode

Keeps only records that have **no duplicates** — records that appear exactly once in the input. Records with any duplicate are sent to port 1.

```xml
<Node dedupKey="email" keep="Unique" type="DEDUP"/>
```
`noDupRecord` is ignored when `keep="Unique"`.

## No-Key Mode (head / tail)

Without `dedupKey`, DEDUP behaves like Unix `head` or `tail`:
- `keep="First"` + `noDupRecord=100` → pass the first 100 records, send the rest to port 1
- `keep="Last"` + `noDupRecord=100` → pass the last 100 records, send the rest to port 1

```xml
<!-- Pass first 100 records to component B, overflow to component C -->
<Node noDupRecord="100" type="DEDUP"/>
<Edge fromNode="DEDUP:0" ... toNode="B:0"/>   <!-- first 100 -->
<Edge fromNode="DEDUP:1" ... toNode="C:0"/>   <!-- remaining -->
```

## Real Sandbox Examples

### MiscExamples — top-N by score (no-key mode after descending sort)
```xml
<!-- Upstream: AGGREGATE by customer, FAST_SORT by amount descending -->
<Node guiName="Get Top 20" id="GET_TOP_20" noDupRecord="20" type="DEDUP"/>
```
No `dedupKey` — takes first 20 records from the sorted stream (= highest 20 amounts).

### MiscExamples — deduplicate by key field (unsorted, few distinct values)
```xml
<Node dedupKey="ruleName(a)" guiName="Each Rule Name Just Once"
      id="EACH_RULE_NAME_JUST_ONCE" sorted="false" type="DEDUP"/>
```
`sorted="false"` — input not sorted by `ruleName`. Works because there are few distinct rule names.

## Common Patterns

### Sorted dedup of large dataset (streaming)
```xml
<Node id="SORT"  sortKey="email(a)"  type="FAST_SORT"/>
<Node id="DEDUP" dedupKey="email"    type="DEDUP"/>
```
Streaming, no memory limit. Requires contiguous groups (sorted input).

### Unsorted dedup of small dataset (in-memory)
```xml
<Node id="DEDUP" dedupKey="email" sorted="false" type="DEDUP"/>
```
No upstream sort needed. Only for small datasets or few distinct key values.

### Keep last 2 logins per user (unsorted)
```xml
<Node dedupKey="username" keep="Last" noDupRecord="2" sorted="false" type="DEDUP"/>
```
Input sorted by timestamp (not by username). Keeps last 2 records per username.

### Keep only unique values (no duplicates anywhere)
```xml
<Node id="SORT"  sortKey="code(a)" type="FAST_SORT"/>
<Node id="DEDUP" dedupKey="code" keep="Unique" type="DEDUP"/>
```
Records with any duplicate go to port 1; only truly-unique records reach port 0.

### Composite key dedup
```xml
<Node id="SORT"  sortKey="lastName(a);firstName(a)"  type="FAST_SORT"/>
<Node id="DEDUP" dedupKey="lastName;firstName"        type="DEDUP"/>
```

## Decision Guide

| Need | Use |
|---|---|
| Remove duplicates by key, large dataset | `dedupKey` + upstream FAST_SORT (sorted mode) |
| Remove duplicates by key, few distinct values | `dedupKey` + `sorted="false"` (unsorted mode) |
| Keep only records that appear exactly once | `dedupKey` + `keep="Unique"` |
| Keep first N records of entire stream | No `dedupKey` + `noDupRecord=N` + `keep="First"` |
| Keep last N records of entire stream | No `dedupKey` + `noDupRecord=N` + `keep="Last"` |
| Keep last N per group (unsorted) | `dedupKey` + `keep="Last"` + `noDupRecord=N` + `sorted="false"` |
| Send overflow to different component | Connect port 1 |

## Mistakes

| Wrong | Correct |
|---|---|
| `sorted="true"` (default) with non-contiguous groups | Groups must be adjacent even if not globally sorted; use `sorted="false"` for truly unsorted data |
| `sorted="false"` on large dataset with many distinct values | Memory-bound — use sorted mode for large distinct-key sets |
| `noDupRecord` used with `keep="Unique"` | `Unique` ignores `noDupRecord` — only records with zero duplicates pass |
| Expecting output order preservation in unsorted `keep="Last"` mode | Port 1 order not guaranteed; port 0 order within group preserved but not global |
| No `dedupKey` + `keep="Last"` expecting per-group behavior | No-key mode applies to entire input, not per group |
| Expecting globally sorted groups when `sorted="true"` | Groups only need to be **contiguous**, not globally ordered |
| `noDupRecord` not set when wanting to keep more than 1 per group | Default is 1; set `noDupRecord=N` explicitly for N > 1 |
