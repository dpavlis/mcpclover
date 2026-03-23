Good question — let me look at the current output critically by calling it for a couple of different components.Good sample to analyze. Here's my honest assessment:

---

**What works well in the current format:**
- Quick to scan — type, category, ports, properties all visible at a glance
- Port required/optional is clear
- Enum values are shown inline which is useful

**What's problematic or missing:**

**1. The `*required*` marker is misleading on mutually exclusive properties.**
`EXT_HASH_JOIN` shows `transform`, `transformURL`, and `transformClass` all marked `*required*`. They're not all required — exactly one of them is required (they're alternatives). This is the most actionable error because I might generate XML with all three present or none. The correct signal would be something like `(one of: transform | transformURL | transformClass)`.

**2. Property types are opaque.**
`[hashJoinKey]`, `[transformDenormalize]`, `[transform]` tell me nothing about the expected syntax. The key question I need answered is: *does this property go as an XML attribute on `<Node>`, or as an `<attr name="...">` child element?* Currently I have to guess from convention. The distinction matters — `joinType` goes as a Node attribute, `transform` goes as a CDATA child element, and getting this wrong produces a broken graph.

**3. Missing: CTL entry point.**
For components with CTL transforms, the most important thing I need is the function signature. `DENORMALIZER` has `denormalize [transformDenormalize]` but no indication that I need `append()`, `transform()`, and `clean()`. A single line `CTL: append(), transform(), clean()` would prevent the class of errors we saw earlier in this session.

**4. Port numbering is ambiguous for multi-port components.**
`EXT_HASH_JOIN` shows `[0] driver` and `[] slave` — the `[]` doesn't tell me the slave starts at port 1. For edge declarations this matters: `fromNode="JOIN:0"` vs `fromNode="JOIN:1"`.

**5. Verbose description adds little.**
The DENORMALIZER description is 60 words explaining what denormalization is. I already know that. What I need is: *"input must be sorted on key field"* — which is buried or absent.

---

**Recommended restructure — still text, not JSON:**

JSON would actually be worse here because I'd spend tokens parsing structure rather than reading content. The current text format is the right medium, just needs different content. Suggested shape:

```
Type:        EXT_HASH_JOIN
Name:        ExtHashJoin  
Category:    joiners
Summary:     Hash-based equality join. Slave side loaded into memory — keep slave small.
             Input does NOT need to be sorted. For sorted inputs use EXT_MERGE_JOIN.

Input Ports:
  [0]  driver  (required)
  [1+] slave   (required, one per slave stream)

Output Ports:
  [0]  joined records     (required)
  [1]  unmatched master   (optional, leftOuter/fullOuter only)

Node XML attributes:
  joinType      inner | leftOuter | fullOuter   (default: inner)
  slaveDuplicates  true | false                  (default: false)
  hashTableSize    integer

<attr> child elements (CDATA):
  joinKey       *required*   Format: $0.field=$1.field#$0.field2=$1.field2
  transform     }
  transformURL  } one of these three required
  transformClass}

CTL entry point:  function integer transform()
                  $in.0 = driver record, $in.1 = slave record
                  return ALL | port number | SKIP
```

The key additions are: **summary with selection guidance** (when to use this vs alternatives), **explicit port numbers on all ports**, **Node attribute vs `<attr>` child separation**, **mutual exclusivity expressed as a group**, and **CTL entry point with port semantics**.

The last point — Node attribute vs `<attr>` child — is probably the single highest-value change. That distinction is what causes the most graph XML authoring errors and it's completely absent from the current output.
