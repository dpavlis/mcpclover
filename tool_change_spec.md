```
SPEC: graph_edit_properties — Bulk Edit Mode
Version: 1.0
Status: Proposed
```

---

## Summary

Extend `graph_edit_properties` to accept an array of changes in a single call, while keeping the existing single-change signature fully backward-compatible.

---

## Current Signature (unchanged)

```python
graph_edit_properties(
    graph_path: str,
    sandbox: str,
    element_type: str,      # "Node" | "Metadata" | "Edge" | "GraphParameter" | ...
    element_id: str,
    attribute_name: str,    # plain attr or "attr:childName" for CDATA children
    value: str,
    dry_run: bool = False
)
```

---

## New Parameter: `changes`

Add one optional parameter:

```python
changes: list[ChangeObject] | None = None
```

Where `ChangeObject` is:

```python
{
    "element_type": str,    # required
    "element_id":   str,    # required
    "attribute_name": str,  # required
    "value":        str     # required
}
```

---

## Mode Selection Rules

| `changes` | Single params | Behaviour |
|---|---|---|
| `None` | All provided | Existing single-edit mode — no change |
| Provided | Ignored | Bulk mode |
| `None` | Missing any | Error as today |
| Both provided | — | Error: ambiguous, reject |

`graph_path`, `sandbox`, and `dry_run` always apply to the whole call in both modes.

---

## Execution Semantics

**Atomic — all-or-nothing.**  
Parse and validate all changes against the DOM before writing any of them. If any change fails (element not found, invalid attribute name, XML serialisation error), reject the entire batch and leave the file untouched.

**Order:** apply changes in array order. If two entries target the same element+attribute, the last one wins (no error).

**No partial success.** The response is either full success or full failure with the index and reason of the first failing change.

---

## Response

**Single-edit mode:** unchanged.

**Bulk mode — success:**
```json
{
  "status": "ok",
  "applied": 12,
  "dry_run": false
}
```

**Bulk mode — failure:**
```json
{
  "status": "error",
  "failed_index": 3,
  "element_type": "Node",
  "element_id": "TRANSFORM_X",
  "attribute_name": "attr:transform",
  "reason": "Element not found: id='TRANSFORM_X'"
}
```

---

## dry_run Behaviour

When `dry_run=true` in bulk mode, return a diff of all planned changes without writing:

```json
{
  "status": "ok",
  "dry_run": true,
  "planned": [
    {
      "index": 0,
      "element_type": "Node",
      "element_id": "READER",
      "attribute_name": "guiX",
      "old_value": "120",
      "new_value": "60"
    },
    ...
  ]
}
```

If any change would fail, report the failure and return no diff (same fail-fast rule).

---

## Tool Description Update

```
Set or update a property on one or more existing graph elements via XML DOM.
Single-edit: provide element_type, element_id, attribute_name, value.
Bulk edit: provide a changes[] array — all changes applied atomically; fails entirely
if any change is invalid. Use dry_run=true to preview. graph_path and sandbox apply
to all changes in both modes.
```

---

## Input Schema Delta

```json
"changes": {
  "type": "array",
  "description": "Bulk edit array. Mutually exclusive with element_type/element_id/attribute_name/value. All changes applied atomically — fails entirely if any entry is invalid.",
  "items": {
    "type": "object",
    "required": ["element_type", "element_id", "attribute_name", "value"],
    "properties": {
      "element_type":    { "type": "string" },
      "element_id":      { "type": "string" },
      "attribute_name":  { "type": "string" },
      "value":           { "type": "string" }
    },
    "additionalProperties": false
  }
}
```

Mark `element_type`, `element_id`, `attribute_name`, `value` as no longer individually required at schema level (validation moves to runtime mode-selection logic).

---

## Primary Use Cases

- **Re-layout:** 20 `guiX`/`guiY` changes in one call instead of 20 round-trips
- **Multi-attribute component overhaul:** change `enabled`, `sortKey`, and `attr:transform` on the same node together
- **Batch parameter update:** update several `GraphParameter` values in one operation

---

## Out of Scope

- Cross-file bulk edits (one call = one graph file, always)
- Structural changes (add/delete/move elements) — that remains `graph_edit_structure`
- Per-change dry_run — dry_run applies to the whole call