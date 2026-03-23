Let me call it for several components to give concrete examples across different complexity levels.Good spread of examples. Here are the concrete problems, from most to least impactful:

---

### Problem 1 — `*required*` is wrong for mutually exclusive groups

The single most dangerous issue. Both REFORMAT and EXT_HASH_JOIN show:

```
transform *required*
transformURL *required*
transformClass *required*
```

These are NOT all required — exactly one of the three is required. Marking all three `*required*` tells me I must provide all three, which produces invalid XML. The correct signal is a mutual exclusivity group:

```
(one of, required):  transform | transformURL | transformClass
```

Similarly `key` and `groupSize` on DENORMALIZER are alternatives — either a key field list OR a fixed group size. The current output shows them as optional with no relationship declared, which is also misleading.

---

### Problem 2 — No XML placement guidance (Node attribute vs `<attr>` child)

The single most practically important missing piece. Every property needs one of these labels:

- **`[xml-attr]`** → goes as `<Node propertyName="value" .../>`
- **`[attr-cdata]`** → goes as `<attr name="propertyName"><![CDATA[...]]></attr>`

Currently all properties look identical. But `joinType="inner"` goes on the `<Node>` tag, while `transform` goes in a CDATA child. Getting this wrong produces XML that either silently ignores the value or fails Stage 1 validation. This caused actual errors in this session — `debugPrint` vs `debugOutput` confusion on TRASH, `graphURL` vs `jobURL` on SUBGRAPH.

Proposed format:
```
[xml-attr]   joinType
[attr-cdata] transform
```

---

### Problem 3 — Missing CTL entry point

For any component with a CTL transform, the most important thing I need is the function signature. Currently absent entirely. DENORMALIZER shows `denormalize [transformDenormalize]` but nothing tells me I need `append()` + `transform()` + `clean()`. A single line would prevent the class of bugs we hit:

```
CTL entry:   function integer append()
             function integer transform()
             function void clean()
```

---

### Problem 4 — Port numbering incomplete for variable-port components

EXT_HASH_JOIN shows:
```
[0] driver (required)
[] slave (required)
```

The `[]` for slave doesn't tell me it starts at port 1. For edge declarations this matters — `toNode="JOIN:1"` not `toNode="JOIN:0"`. Should be:

```
[0]   driver  (required)
[1+]  slave   (required, one or more)
```

---

### Problem 5 — Description is verbose and wrong priority

EXT_HASH_JOIN's description is 70 words explaining hash join theory. What I actually need from a description is **selection guidance** — when to use this vs alternatives — and **critical operational constraints**. For EXT_HASH_JOIN that would be: *"slave side loaded entirely into memory — keep slave small; input does NOT need to be sorted; for sorted inputs prefer EXT_MERGE_JOIN"*. None of that is currently present.

---

### Problem 6 — Opaque property types

`[hashJoinKey]`, `[transformDenormalize]`, `[key]`, `[sortKey]` — these type labels are internal type names that mean nothing without documentation. The one thing I actually need to know for each is the **syntax of the value**. For `joinKey` that's `$0.field=$1.field#$0.field2=$1.field2`. For `key` on DENORMALIZER it's `field1;field2`. Currently I have to infer this from memory or the reference docs.

---

### Problem 7 — Redundant/confusing properties

EXT_HASH_JOIN shows both `joinType [enum]` with values `inner|leftOuter|fullOuter` AND separate `leftOuterJoin [bool]` and `fullOuterJoin [bool]`. These are legacy aliases for the same thing. Showing both is confusing — I might set both `joinType="leftOuter"` and `leftOuterJoin="true"` unnecessarily. The legacy bool properties should be hidden or marked `[deprecated, use joinType instead]`.

---

### Proposed restructured output format

Using REFORMAT and DENORMALIZER as examples:

```
Type:     REFORMAT   (alias: MAP)
Name:     Map
Category: transformers
Summary:  Transforms records via CTL2 or Java. One input, one or more outputs.
          Return ALL to send to all ports; return port number to route selectively.

Input Ports:
  [0]  (required)

Output Ports:
  [0+] (required, one or more)

XML attributes  [xml-attr]:
  (none beyond common Node attributes)

CDATA child elements  [attr-cdata]:
  (one of, required):
    transform      CTL2 code. Entry: function integer transform()
    transformURL   path to external .ctl file
    transformClass Java class name

  charset          encoding for transformURL file (optional)
  errorActions     error handling policy (optional)
  errorLog         path to error log file (optional)

CTL entry points:
  function integer transform()   — called per record; return ALL|port|SKIP
  function boolean init()        — optional; called once before processing
  function void postExecute()    — optional; called after all records processed
  function integer transformOnError(string msg, string stack) — optional
```

```
Type:     DENORMALIZER
Category: transformers
Summary:  Groups N consecutive input records into 1 output record via CTL2.
          Input MUST be sorted on the key field(s) — add EXT_SORT or FAST_SORT upstream.
          key OR groupSize required (not both).

Input Ports:
  [0]  (required, must be sorted on key)

Output Ports:
  [0]  (required)

XML attributes  [xml-attr]:
  key            grouping key fields, semicolon-separated (e.g. "customerId;type")
  groupSize      fixed group size as alternative to key
  order          Asc|Desc|Auto(default)|Ignore — sort order of input
  equalNULL      true(default)|false — treat nulls as equal in key comparison
  incompleteGroupAllowed  false(default)|true

CDATA child elements  [attr-cdata]:
  (one of, required):
    denormalize    CTL2 code
    denormalizeURL path to external .ctl file
    denormalizeClass Java class name

CTL entry points:
  function integer append()    — called per input record in group
  function integer transform() — called once per group to produce output record
  function void clean()        — called after transform(); MUST reset state variables
```

---

### Summary — ranked by implementation priority

| # | Issue | Impact |
|---|---|---|
| 1 | `*required*` on mutually exclusive groups | Generates invalid XML |
| 2 | No `[xml-attr]` vs `[attr-cdata]` distinction | Generates structurally wrong XML |
| 3 | Missing CTL entry points | Wrong function signatures in CTL code |
| 4 | Incomplete port numbering for variable-port components | Wrong edge declarations |
| 5 | Description doesn't include selection guidance or constraints | Wrong component chosen |
| 6 | Opaque property type labels | Value syntax unknown |
| 7 | Deprecated bool aliases shown alongside enum | Redundant/confusing properties set |

Items 1–3 cause hard failures. Items 4–7 cause subtle mistakes that pass Stage 1 but fail at runtime or produce incorrect behaviour.