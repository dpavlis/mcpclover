# CloverDX LOOKUP_TABLE_READER_WRITER — LLM Reference

## Core semantics
- Populates a lookup table from input records and/or emits records from a lookup table.
- No CTL/Java transform.
- Typical role: load runtime reference data into a lookup table before later lookup usage.

## Required property
- `lookupTable` = ID of `<LookupTable .../>` declared in `<Global>`

## Port semantics
- Input `0` connected -> writes incoming records into the lookup table.
- Any output connected -> reads records from the lookup table and sends them out.
- Can be used in 3 modes:
 - write-only
 - read-only
 - read+write
- At least one side must be connected.

## Non-obvious rules
- Output is **broadcast**: every connected output gets the same records.
- Metadata on outputs comes from the lookup table, not from arbitrary upstream metadata.
- Input metadata must be compatible with the lookup table metadata.
- Best used in an earlier phase than components that query the lookup table.
- Writing to **database lookup tables** is not supported.

## Real usage pattern found in existing graphs
Common pattern:
1. read reference files
2. gather/normalize them
3. write them into lookup table via `LOOKUP_TABLE_READER_WRITER`
4. later phase uses `lookup(name).get(...)` or `LOOKUP_JOIN`


## Common failure modes
- `lookupTable` references missing global lookup table
- input metadata incompatible with lookup metadata
- graph expects outputs to partition records; they do not, they broadcast
- component used to write DB lookup table
- component placed in same/later phase than consumers when lookup must be preloaded first

## `freeLookupTable`
- default `false`
- if `true`, clears caches/content after component finishes depending on lookup type
- for `simpleLookup` and `rangeLookup`, contents become empty after finish
- for other types, may clear only caches

## Minimal pattern
### Global
```xml
<LookupTable id="LookupTable0" key="customerid" metadata="Metadata0" name="customers_look" type="simpleLookup"/>
```

### Node
```xml
<Node id="LOOKUP_TABLE_READER_WRITER0" lookupTable="LookupTable0" type="LOOKUP_TABLE_READER_WRITER"/>
```

### Populate from stream
```xml
<Edge fromNode="GATHERS_INTO_1_FILE:0" toNode="LOOKUP_TABLE_READER_WRITER0:0"/>
```

### Later usage elsewhere
```ctl
matched_record = lookup(customers_look).get($in.0.OrderID);
```

## LLM guidance
- Generate this component when a lookup table must be populated during graph execution.
- Do not generate CTL for it.
- Put lookup declaration in `<Global>` first.
- Put loader phase before lookup consumer phase.
- Do not use for DB lookup table writes.
