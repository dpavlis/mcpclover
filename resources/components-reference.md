description: Dense catalog summary for CloverDX component types bundled in components.json: non-deprecated component inventory with canonical type/name/category, port topology, configurable properties, and component-selection lookup data used to choose valid nodes and wire compatible graph structures.

# CloverDX Component Catalog Reference

Use the component tools to discover valid CloverDX node types before designing or editing a graph. The expected workflow is: browse with `list_components`, inspect one candidate with `get_component_info`, then read deeper markdown with `get_component_details` only for components that have extended docs.

## list_components

Use `list_components` when you do not yet know the exact component type and need to browse the catalog.

Purpose:
- List all non-deprecated component types from the bundled catalog.
- Narrow results by category.
- Search component type or name with literal or regex matching.

When to use:
- Early in graph design when choosing a reader, writer, transformer, joiner, or job-control component.
- When a prompt describes behavior but not a CloverDX component name.
- When you need to compare several candidate components quickly.

Inputs:
- `category` optional: one of `readers`, `writers`, `transformers`, `joiners`, `others`, `jobControl`.
- `search_string` optional: case-insensitive search text.
- `match_mode` optional: `literal` or `regex`, default `literal`.

Output shape:
- Compact table with `Type | Name | Category | Description`.
- Category-filtered output uses the full description field.

Examples:
```json
{}
```

```json
{"category": "readers"}
```

```json
{"search_string": "join", "match_mode": "literal"}
```

```json
{"category": "transformers", "search_string": "^re", "match_mode": "regex"}
```

## get_component_info

Use `get_component_info` when you have a likely component and need the exact technical contract for graph construction.

Purpose:
- Resolve a component by exact type, exact name, or partial match.
- Return ports, required/optional properties, enum values, defaults, and conditional-required groups.

When to use:
- Before wiring edges, so the correct input and output ports are known.
- Before setting node properties in XML or with graph-edit tools.
- Before deciding between similar components after a `list_components` search.

Inputs:
- `query` required: component type or display name.
- `include_deprecated` optional: include deprecated matches, default `false`.

Behavior:
- One match: returns a full formatted component definition.
- Multiple matches: returns a compact candidate list and asks for a more exact re-query.
- No match: suggests using `list_components` to browse.

Output details typically include:
- Canonical `type`, display `name`, category, and description.
- Input and output port labels with required/optional status.
- Property names, types, defaults, enum values, and conditional requirements.
- `[attr-cdata]` markers for properties that should be written as `<attr>` content rather than plain XML attributes.

Examples:
```json
{"query": "XML_EXTRACT"}
```

```json
{"query": "Map"}
```

```json
{"query": "reader", "include_deprecated": true}
```

## get_component_details

Use `get_component_details` only after the component type is already known and you need long-form component-specific guidance.

Purpose:
- Return detailed markdown documentation from the local `comp_details/` directory.
- Provide richer usage notes, examples, mapping syntax, and component-specific rules that do not fit in the compact catalog.

When to use:
- For complex components whose configuration is difficult to infer from ports and property lists alone.
- When `get_component_info` is not enough to safely configure the component.
- When you need examples or syntax guidance for advanced properties.

Inputs:
- `component_type` required: canonical type string such as `XML_EXTRACT`.

Behavior:
- If docs exist: returns the full markdown file.
- If docs do not exist: returns the list of component types that currently have extended docs.

Important limitation:
- Detailed docs are available only for components present in `comp_details/`; this is not a full-catalog feature.

Example:
```json
{"component_type": "XML_EXTRACT"}
```

## Recommended Usage Sequence

1. Use `list_components` to find candidate types by category or keyword.
2. Use `get_component_info` on the chosen candidate to obtain exact ports and property names.
3. Use `get_component_details` only if the component is complex and extended markdown is available.

## Selection Guidance

- Use `list_components` for discovery.
- Use `get_component_info` for implementation.
- Use `get_component_details` for advanced configuration and examples.