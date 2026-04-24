# CloverDX LOOKUP_JOIN — LLM Reference

## Core semantics
- Joins input/master records from physical input port `0` with slave records fetched from a lookup table.
- Slave side is **virtual**: no input edge exists for the lookup side.
- In CTL:
 - `$in.0` = master/input record
 - `$in.1` = matched lookup/slave record
 - `$out.0` = joined output record
- A transform is required (`transform`, `transformURL`, or `transformClass`).

## Required properties
- `lookupTable` — ID of lookup table declared in `<Global>`
- `joinKey` — mapping from lookup key fields to input fields
- one transform property

## Non-obvious joinKey rule
`LOOKUP_JOIN` does **not** use generic `left=right` join syntax from other joiners.

Use:

```text
$LookupKeyField=$InputField
```

For multi-key joins:

```text
$LookupKeyField1=$InputField1;$LookupKeyField2=$InputField2
```

Meaning:
- left side = lookup/slave key field
- right side = input/master field

If names are identical, shorthand may work for single-field joins:

```text
CountryCode
```

But for LLM-generated graphs, prefer explicit mapping syntax.

## Key alignment constraints
- Number of mappings in `joinKey` must equal number of fields in lookup table `key`.
- Corresponding key field data types must match.
- Field names do **not** need to match across master and lookup metadata.

Example:
- lookup table key: `SupplierID;ProductNo`
- valid joinKey:

```text
$SupplierID=$SuppliedNumber;$ProductNo=$ProductNumber
```

## Output behavior
- Output port `0` = joined records
- Output port `1` = unmatched master records
- `leftOuterJoin=false` (default): inner-join style behavior; unmatched master records may go to output `1`
- `leftOuterJoin=true`: unmatched master records are still processed by the transform as outer-join cases

## Important runtime behavior
- One master record can produce multiple output rows if the lookup table allows duplicate keys.
- Master data is streamed; slave data is retrieved from the lookup table implementation.

## Common failure modes
### Wrong joinKey syntax
Wrong:

```text
SupplierID=SuppliedNumber;ProductNo=ProductNumber
```

Correct:

```text
$SupplierID=$SuppliedNumber;$ProductNo=$ProductNumber
```

Typical error:
- `Lookup key field 'SupplierID' is not mapped`

### Key count mismatch
Invalid if lookup key has 2 fields but `joinKey` maps only 1 or maps 3.

### Type mismatch
Lookup key field types and mapped input field types must align.

### Missing transform
`LOOKUP_JOIN` requires a transform even for simple pass-through enrichment.

### Outer join null handling
When `leftOuterJoin=true`, guard access to `$in.1.*` if unmatched lookup rows are possible.

## Minimal working pattern
### Lookup table
```xml
<LookupTable
 id="SupplierData"
 type="simpleLookup"
 fileURL="${LOOKUP_DIR}/supplier_data.csv"
 metadata="LookupMeta"
 key="SupplierID;ProductNo"/>
```

### Component
```xml
<Node
 id="LOOKUP_JOIN"
 type="LOOKUP_JOIN"
 lookupTable="SupplierData"
 joinKey="$SupplierID=$SuppliedNumber;$ProductNo=$ProductNumber"
 leftOuterJoin="false">
```

### CTL
```ctl
function integer transform() {
 $out.0.SuppliedNumber = $in.0.SuppliedNumber;
 $out.0.ProductNumber = $in.0.ProductNumber;
 $out.0.Quantity = $in.0.Quantity;
 $out.0.SupplierID = $in.1.SupplierID;
 $out.0.ProductNo = $in.1.ProductNo;
 $out.0.SupplierName = $in.1.SupplierName;
 $out.0.ProductName = $in.1.ProductName;
 return ALL;
}
```

## LLM guidance
When generating `LOOKUP_JOIN`:
1. Read lookup table `key` exactly.
2. Generate one `joinKey` mapping per lookup key field.
3. Put lookup field on left, input field on right.
4. Always generate a transform.
5. Use `$in.1` only for lookup/slave fields.
6. If field names differ, do not infer equality by name; map explicitly.
