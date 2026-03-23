# CloverDX AGGREGATE — LLM Reference (7.3.x)

## SKELETON

```xml
<Node aggregateKey="state" guiName="Aggregate" guiX="200" guiY="100"
      id="AGGREGATE0" mapping="$state:=$state;$total:=sum($amount);$n:=count();" type="AGGREGATE"/>
```

- Input port 0, output port 0 (`Port 0 (out)`)
- `aggregateKey` and `mapping` are **Node XML attributes** (not `<attr>` children) — canonical visual-editor form
- Child-element CDATA form also accepted; use it when mapping contains conditions (more readable, less escaping)

## NODE ATTRIBUTES

| Attr | Default | Notes |
|---|---|---|
| `aggregateKey` | — | Semicolon-separated group key fields. Empty = single group over all records. |
| `mapping` | required | Semicolon-separated mapping expressions. Trailing `;` optional. |
| `sorted` | `true` | `true` = input pre-sorted by key; `false` = internal hash table |
| `equalNULL` | `false` | `true` = NULL values treated as equal for grouping |
| `zeroCountRecord` | `false` | `true` = emit one record with count 0 when group is empty |
| `charset` | UTF-8 | Encoding of incoming records |

## MAPPING SYNTAX

Use shorthand `$fieldName` — **never** `$in.0.field` or `$out.0.field` in mapping expressions (parser rejects them).

| Form | Example |
|---|---|
| Key passthrough (required for every key field) | `$state:=$state` |
| Aggregate function | `$total:=sum($amount)` |
| Conditional aggregate | `$n:=count(,"$in.0.isActive")` |
| Constant | `$label:="USA"` |

Multiple key fields: `aggregateKey="country;state"` — each must appear as `$f:=$f` in mapping.

**CDATA form — use for mappings with conditions:**
```xml
<attr name="mapping"><![CDATA[$state:=$state;$n:=count(,"$in.0.isActive");]]></attr>
```
CDATA content must start with `$` immediately after `[[` — a leading newline causes:
`mapping does not start with proper field reference - found Token[EOL]`

## AGGREGATE FUNCTIONS

All functions accept an optional boolean condition as their last argument: `function($field,"CTL2 bool expr")`. Condition can reference **any** input field, not only the aggregated one.

| Function | Notes |
|---|---|
| `count()` | No input field. Conditional form: `count(,"condition")` |
| `countnotnull($f)` | Excludes nulls |
| `countunique($f)` | null counts as one unique value |
| `sum($f)` | Nulls ignored |
| `avg($f)` | Nulls ignored |
| `min($f)` / `max($f)` | All-null group → null |
| `first($f)` / `last($f)` | Returns null if first/last is null |
| `firstnotnull($f)` / `lastnotnull($f)` | `firstnonnull` is an undocumented alias; prefer `firstnotnull` |
| `median($f)` / `stddev($f)` / `modus($f)` | Nulls excluded |
| `crc32($f)` | Null input → null |

## CONDITIONAL AGGREGATION

Condition is a **CTL2 boolean expression passed as a string literal** (second argument).

Rules:
1. Inside the condition string use `$in.0.fieldName` — shorthand `$fieldName` does not resolve there
2. Must evaluate to boolean — comparisons, logical operators, bare boolean field ref all valid
3. Can reference any input field, not only the aggregated one

**XML-attribute encoding** (visual-editor form):

| In condition | In XML attribute |
|---|---|
| `"` (string delimiter) | `&quot;` |
| `\"` (escaped quote inside string) | `\&quot;` |
| `&&` | `&amp;&amp;` |

**CDATA form** (preferred when conditions present — no extra escaping layer):
```xml
<attr name="mapping"><![CDATA[$state:=$state;
$nCA:=count(,"$in.0.state == \"CA\" || $in.0.state == \"VA\"");
$nActiveOther:=count(,"$in.0.state != \"CA\" && $in.0.isActive");
$avgActiveSalary:=avg($salary,"$in.0.isActive");
$usdSum:=sum($amount,"$in.0.currency == \"USD\"");
$country:="USA";
$city:=firstnotnull($city);]]></attr>
```
CDATA mapping may span multiple lines — no leading newline before the first `$`.

**Attribute form** (same mapping — visual-editor output):
```xml
mapping="$state:=$state;$nCA:=count(,&quot;$in.0.state == \&quot;CA\&quot; || $in.0.state == \&quot;VA\&quot;&quot;);$nActiveOther:=count(,&quot;$in.0.state != \&quot;CA\&quot; &amp;&amp; $in.0.isActive&quot;);$avgActiveSalary:=avg($salary,&quot;$in.0.isActive&quot;);$usdSum:=sum($amount,&quot;$in.0.currency == \&quot;USD\&quot;&quot;);$country:=&quot;USA&quot;;$city:=firstnotnull($city);"
```

**ROLLUP over AGGREGATE:** When aggregation requires multi-step pre-calculations before a value can be counted, derived intermediate values, or stateful logic within a group, use **ROLLUP** — full CTL2 `initGroup` / `updateGroup` / `finishGroup` entry points, no logic limitations. More complex to configure.

## SORTED INPUT

`sorted="false"` uses an internal hash table — correct and efficient for up to low thousands of distinct groups. **Do not add FAST_SORT solely to satisfy AGGREGATE**; only pre-sort when:
- A sort already exists upstream (re-use at no cost), or
- Downstream component requires sorted data, or
- Group count is very large (tens of thousands+) where hash table memory becomes a concern

Silent bug: `sorted="true"` (default) with unsorted input produces one output row per contiguous run of each key value — wrong results, no error.

## MISTAKES

| Wrong | Correct |
|---|---|
| `$out.0.total:=sum($in.0.amount)` in mapping | `$total:=sum($amount)` — shorthand only in mapping |
| `<![CDATA[\n$field...` — leading newline | `<![CDATA[$field...` — start with `$` immediately |
| `count($field)` for conditional count | `count(,"condition")` — `count` takes no field arg |
| Condition references only the aggregated field | Condition can reference any input field |
| Condition not boolean | Must evaluate to boolean |
| `$fieldName` inside condition string | `$in.0.fieldName` inside condition string |
| `&&` unescaped in XML attribute mapping | `&amp;&amp;` |
| `"` unescaped in XML attribute mapping | `&quot;`; inner quotes: `\&quot;` |
| `aggregateKey="country,state"` comma separator | `aggregateKey="country;state"` semicolon |
| Key field not passed through in mapping | Every aggregateKey field needs `$f:=$f` in mapping |
| `aggregateKey` as `<attr>` child element | Node XML attribute — both work but attribute form avoids round-trip reformat |
| Adding FAST_SORT only to feed AGGREGATE | Use `sorted="false"` unless sort already present, needed downstream, or tens of thousands+ groups |
| `sorted` omitted (default `true`) with unsorted input | Set `sorted="false"` or pre-sort — mismatch silently produces wrong output |
| Complex stateful/pre-calc logic in condition strings | Use **ROLLUP** instead |
| `firstnonnull` (undocumented alias) | `firstnotnull` (documented name) |
| Numeric aggregate function on `string` output field | Output field must be numeric type |
