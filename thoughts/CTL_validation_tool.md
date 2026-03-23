This is a genuinely interesting design problem. Let me reason through it properly before proposing the tool definitions.

---

## The core dependency problem

CTL validation is never truly context-free. At minimum it needs:

| Dependency | Standalone CTL | In-graph CTL |
|---|---|---|
| Input port metadata (`$in.0.field`) | Must be supplied explicitly | Available from graph edges |
| Output port metadata (`$out.0.field`) | Must be supplied explicitly | Available from graph edges |
| Propagated/calculated metadata | Cannot resolve | Fully resolved by graph instantiation |
| Lookup tables | Must reference by path | Available from graph `<Global>` |
| Sequences | Must reference by path | Available from graph `<Global>` |
| Graph parameters (`${PARAM}`) | Must supply subset | Available from workspace.prm |
| Imported CTL files (`import "..."`) | Must reference by path | Available from sandbox |

The propagated metadata point is the critical one. In many real graphs, edge metadata is not declared on the edge — it flows from a reader's auto-detected schema, or from a REFORMAT's output which is inferred. The standalone validator simply cannot handle this; the in-graph validator handles it naturally because CloverDX resolves it during graph instantiation.

---

## Two tools, not one

These are genuinely different tools with different use cases, not one tool with a mode flag:

**Standalone** — "I'm assembling a CTL snippet and want fast syntax + type checking before I even have a graph. I know my metadata, I'll supply it."

**In-graph** — "I have a working graph. I want to iterate on just the CTL of one component without running validate_graph on the whole thing every time. The graph provides all context."

---

## Tool 1: `validate_ctl` (standalone)

```python
types.Tool(
    name="validate_ctl",
    description=(
        "Validates a CTL2 code snippet in isolation — outside of any graph context. "
        "Checks syntax, type correctness, function signatures, and field access against "
        "the supplied port metadata. "
        "Use this when iterating on a CTL transform before a graph exists, or when "
        "assembling a reusable CTL snippet for a .ctl file. "
        "Limitations vs in_graph_validate_ctl: cannot resolve propagated/calculated "
        "edge metadata, cannot access lookup tables or sequences that require graph "
        "instantiation context. For full fidelity validation, use validate_graph or "
        "in_graph_validate_ctl once the graph exists."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "The CTL2 code to validate. Must start with //#CTL2. "
                    "Include all functions relevant to the component type."
                ),
            },
            "component_type": {
                "type": "string",
                "description": (
                    "The component type this CTL will run in (e.g. 'REFORMAT', "
                    "'DENORMALIZER', 'DATA_GENERATOR', 'PARTITION'). "
                    "Determines which entry point functions are valid and expected "
                    "(e.g. transform() for REFORMAT, append()/transform()/clean() "
                    "for DENORMALIZER, generate() for DATA_GENERATOR)."
                ),
            },
            "sandbox": {
                "type": "string",
                "description": (
                    "Sandbox code. Required when the CTL imports external .ctl files, "
                    "or references lookup tables or sequences by sandbox path. "
                    "Optional if the CTL has no external dependencies."
                ),
            },
            "input_ports": {
                "type": "array",
                "description": (
                    "Metadata for each input port, indexed by port number. "
                    "Supply one entry per input port the CTL accesses via $in.N. "
                    "Each entry is either a reference to an existing .fmt file in "
                    "the sandbox, or an inline field list."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "port": {
                            "type": "integer",
                            "description": "Port index (0-based).",
                        },
                        "fmt_path": {
                            "type": "string",
                            "description": (
                                "Path to an existing .fmt metadata file in the sandbox "
                                "(e.g. 'meta/dwh-loader/input/OrderFileInput.fmt'). "
                                "Use this when the metadata is already defined externally. "
                                "Mutually exclusive with 'fields'."
                            ),
                        },
                        "fields": {
                            "type": "array",
                            "description": (
                                "Inline field definitions. Use when no .fmt file exists yet. "
                                "Mutually exclusive with 'fmt_path'."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Field name.",
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "string", "integer", "long", "number",
                                            "decimal", "date", "boolean", "byte",
                                            "cbyte", "variant",
                                        ],
                                        "description": "Field data type.",
                                    },
                                },
                                "required": ["name", "type"],
                            },
                        },
                    },
                    "required": ["port"],
                },
            },
            "output_ports": {
                "type": "array",
                "description": (
                    "Metadata for each output port, indexed by port number. "
                    "Same structure as input_ports. "
                    "Supply one entry per output port the CTL writes via $out.N."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                        "fmt_path": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "string", "integer", "long", "number",
                                            "decimal", "date", "boolean", "byte",
                                            "cbyte", "variant",
                                        ],
                                    },
                                },
                                "required": ["name", "type"],
                            },
                        },
                    },
                    "required": ["port"],
                },
            },
            "lookup_tables": {
                "type": "array",
                "description": (
                    "Lookup tables referenced in the CTL via lookup(name).get(...). "
                    "Each entry is a path to a .lkp file in the sandbox. "
                    "Requires 'sandbox' to be set."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Lookup table name as referenced in CTL (e.g. 'ProductLookup').",
                        },
                        "lkp_path": {
                            "type": "string",
                            "description": "Path to the .lkp file in the sandbox.",
                        },
                    },
                    "required": ["name", "lkp_path"],
                },
            },
            "sequences": {
                "type": "array",
                "description": (
                    "Sequences referenced in the CTL via sequence(name).next(). "
                    "Each entry names a sequence defined in the sandbox. "
                    "Requires 'sandbox' to be set."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Sequence name as referenced in CTL.",
                        },
                        "seq_path": {
                            "type": "string",
                            "description": "Path to the .seq file in the sandbox.",
                        },
                    },
                    "required": ["name"],
                },
            },
            "parameters": {
                "type": "object",
                "description": (
                    "Graph parameter values referenced in the CTL via ${PARAM_NAME} "
                    "or getParamValue(). Key = parameter name, value = parameter value. "
                    "If sandbox is supplied, workspace.prm values are automatically "
                    "available and do not need to be repeated here. Only supply values "
                    "that override or extend workspace.prm."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["code", "component_type"],
        "additionalProperties": False,
    },
)
```

---

## Tool 2: `in_graph_validate_ctl`

```python
types.Tool(
    name="in_graph_validate_ctl",
    description=(
        "Validates the CTL2 code of a specific component within an existing graph — "
        "using the full graph as context. "
        "The graph is instantiated server-side so all metadata (including propagated "
        "and calculated edge metadata), lookup tables, sequences, connections, and "
        "parameters are fully resolved before the CTL is validated. "
        "This provides the same fidelity as validate_graph but scoped to a single "
        "component's CTL, making it faster to iterate on complex transforms. "
        "The graph must already exist on the server and must be structurally parseable "
        "(Stage 1 valid). If the graph itself has Stage 2 errors on OTHER components, "
        "validation of the target component's CTL may still succeed. "
        "If 'code' is omitted, validates the CTL already present in the graph for "
        "that component and attribute — useful as a targeted diagnostic."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "graph_path": {
                "type": "string",
                "description": "Path to the .grf file in the sandbox (e.g. 'graph/MyGraph.grf').",
            },
            "sandbox": {
                "type": "string",
                "description": "Sandbox code.",
            },
            "component_id": {
                "type": "string",
                "description": (
                    "The node ID of the component to validate CTL for — "
                    "matches the 'id' attribute on the <Node> element "
                    "(e.g. 'ORDER_VALIDATOR', 'ADD_REJECTION_REASON')."
                ),
            },
            "attribute_name": {
                "type": "string",
                "description": (
                    "The CTL attribute to validate. Common values: "
                    "'transform' (REFORMAT, joiners), "
                    "'denormalize' (DENORMALIZER), "
                    "'generate' (DATA_GENERATOR), "
                    "'errorMapping' (VALIDATOR), "
                    "'filterExpression' (EXT_FILTER), "
                    "'partitionSource' (PARTITION). "
                    "Defaults to 'transform' if omitted."
                ),
            },
            "code": {
                "type": "string",
                "description": (
                    "The CTL2 code to validate in place of whatever is currently "
                    "in the graph for this component and attribute. Must start with //#CTL2. "
                    "If omitted, the CTL currently present in the graph is validated as-is — "
                    "useful for targeted diagnostics without changing anything."
                ),
            },
        },
        "required": ["graph_path", "sandbox", "component_id"],
        "additionalProperties": False,
    },
)
```

---

## Summary of the design choices

**Why two separate tools rather than one with a `mode` flag:** The parameter surfaces are genuinely different. Standalone needs metadata supplied explicitly; in-graph needs a component ID and graph path. Merging them into one tool would mean most parameters are conditionally required depending on mode — that's harder for an LLM to reason about correctly.

**Why `fmt_path` OR `fields` on port metadata:** A real workflow is: existing sandbox → reference `.fmt` files by path (zero extra typing, authoritative); new graph being assembled → supply inline fields because the `.fmt` doesn't exist yet. Both are valid; forcing one form would make the other use case unnecessarily painful.

**Why `code` is optional in `in_graph_validate_ctl`:** The "validate what's already there" use case is genuinely useful. If `validate_graph` reports a CTL error on component X but everything else is fine, calling `in_graph_validate_ctl` with no `code` gives a focused diagnostic without re-running the full graph check.

**Why `attribute_name` matters:** A single component can have multiple CTL attributes — VALIDATOR has both `rules` (expressions) and `errorMapping`. Without knowing which attribute the code belongs to, the validator can't apply the right entry point constraints or port bindings.