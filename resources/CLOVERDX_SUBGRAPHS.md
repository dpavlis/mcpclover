# CloverDX Subgraphs — LLM Reference

> Authoritative reference for creating, using, and modifying CloverDX subgraphs.
> Token-optimized: rules first, examples second. Anything not listed here does NOT exist.

---

## 1. What is a Subgraph

A subgraph is a reusable component whose logic is implemented as a graph, not Java. It streams data just like a built-in component — executing in parallel with other components in the parent graph. It is NOT sequential (use jobflow for sequential orchestration).

- File extension: `.sgrf` — stored in `${SUBGRAPH_DIR}` (`graph/subgraph/`)
- Cannot be called recursively (no cycles allowed)
- Can nest other subgraphs
- Can contain phases, connections, lookups, metadata, parameters, dictionary — same as a regular graph
- Phases inside a subgraph execute sequentially relative to each other, but the whole subgraph runs as one unit from the parent graph's perspective

---

## 2. Four Design Patterns

| Pattern | SubgraphInput connected | SubgraphOutput connected | Use case |
|---|---|---|---|
| Reader | No | Yes | Reads a data source, emits records |
| Writer | Yes | No | Receives records, writes to target |
| Transformer | Yes | Yes | Transforms/filters/enriches records |
| Executor | No | No | Utility — controlled via phases, no data exchange |

**Rule:** The presence or absence of edges on `SubgraphInput`/`SubgraphOutput` defines the pattern. An unconnected output port on `SubgraphOutput` is valid — records sent to it are silently discarded inside the subgraph (useful for optional outputs).

---

## 3. Anatomy — Required XML Structure

Every `.sgrf` file is a `<Graph>` with `nature="subgraph"` and two special boundary components:

### `SubgraphInput` (`type="SUBGRAPH_INPUT"`)
- Exactly ONE instance per subgraph
- Each `<Port name="N"/>` child defines one input port on the resulting component
- Components feeding into `SubgraphInput` from the left = **debug inputs** (see §5)
- Port index 0-based

### `SubgraphOutput` (`type="SUBGRAPH_OUTPUT"`)
- Exactly ONE instance per subgraph
- Each `<Port name="N"/>` child defines one output port on the resulting component
- Components consuming from `SubgraphOutput` on the right = **debug outputs** (see §5)
- Port index 0-based; unconnected ports silently discard records

### `<Graph>` root attributes for subgraphs

```xml
<Graph nature="subgraph" category="readers" ...>
```

| Attribute | Notes |
|---|---|
| `nature="subgraph"` | **Required** — marks the file as a subgraph |
| `category` | Optional — sets component colour in parent graph. Values: `readers`, `writers`, `transformers`, `dataQuality`, `joiners`, `others` |

### Port declarations in `<Global>`

Ports are declared in `<Global>` as well as on the boundary components. Both must be consistent:

```xml
<Global>
  <inputPorts>
    <singlePort connected="true" name="0"/>
  </inputPorts>
  <outputPorts>
    <singlePort connected="true" name="0"/>
    <singlePort connected="false" name="1"/>   <!-- optional/unconnected output -->
  </outputPorts>
</Global>
```

`connected="true"` = parent graph must connect an edge. `connected="false"` = optional, parent graph may leave unconnected.

---

## 4. Minimal Skeleton Examples

### Reader subgraph (no input port)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph nature="subgraph" category="readers" guiVersion="7.3.0.6"
      id="..." licenseCode="..." name="MyReader">
<Global>
  <outputPorts>
    <singlePort connected="true" name="0"/>
  </outputPorts>
  <Metadata id="OutMeta">
    <Record fieldDelimiter=";" name="output" recordDelimiter="\n" type="delimited">
      <Field name="id" type="integer"/>
      <Field name="name" type="string"/>
    </Record>
  </Metadata>
  <GraphParameters>
    <GraphParameter label="Source File" name="FILE_URL" public="true" required="true"
                    value="${DATAIN_DIR}/input.csv">
      <SingleType multiple="true" name="file" selectionMode="file_or_directory"/>
    </GraphParameter>
    <GraphParameterFile fileURL="workspace.prm"/>
  </GraphParameters>
</Global>
<Phase number="0">
  <Node fileURL="${FILE_URL}" guiName="Reader" guiX="200" guiY="100"
        id="READER" type="DATA_READER"/>
  <Node debugOutput="true" guiName="DebugTrash" guiX="700" guiY="100"
        id="DEBUG_TRASH" type="TRASH"/>
  <Node guiName="SubgraphInput" guiX="50" guiY="10" id="SUBGRAPH_INPUT"
        type="SUBGRAPH_INPUT"/>
  <Node guiName="SubgraphOutput" guiX="550" guiY="10" id="SUBGRAPH_OUTPUT"
        type="SUBGRAPH_OUTPUT">
    <Port guiY="100" name="0"/>
  </Node>
  <Edge fromNode="READER:0" id="Edge0" inPort="Port 0 (in)"
        metadata="OutMeta" outPort="Port 0 (output)" toNode="SUBGRAPH_OUTPUT:0"/>
  <Edge fromNode="SUBGRAPH_OUTPUT:0" id="Edge1" inPort="Port 0 (in)"
        outPort="Port 0 (out)" toNode="DEBUG_TRASH:0"/>
</Phase>
</Graph>
```

### Transformer subgraph (input + output port)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Graph nature="subgraph" category="transformers" guiVersion="7.3.0.6"
      id="..." licenseCode="..." name="MyTransformer">
<Global>
  <inputPorts>
    <singlePort connected="true" name="0"/>
  </inputPorts>
  <outputPorts>
    <singlePort connected="true" name="0"/>
    <singlePort connected="false" name="1"/>
  </outputPorts>
  <GraphParameters>
    <GraphParameterFile fileURL="workspace.prm"/>
  </GraphParameters>
</Global>
<Phase number="0">
  <Node debugInput="true" guiName="DebugInput" guiX="40" guiY="200"
        id="DEBUG_INPUT" recordsNumber="5" type="DATA_GENERATOR">
    <attr name="generate"><![CDATA[//#CTL2
function integer generate() {
    return ALL;
}]]></attr>
  </Node>
  <Node guiName="SubgraphInput" guiX="200" guiY="10" id="SUBGRAPH_INPUT"
        type="SUBGRAPH_INPUT">
    <Port guiY="100" name="0"/>
  </Node>
  <Node guiName="Transform" guiX="450" guiY="100" id="TRANSFORM" type="REFORMAT">
    <attr name="transform"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;
    return ALL;
}]]></attr>
  </Node>
  <Node guiName="SubgraphOutput" guiX="700" guiY="10" id="SUBGRAPH_OUTPUT"
        type="SUBGRAPH_OUTPUT">
    <Port guiY="100" name="0"/>
    <Port guiY="170" name="1"/>
  </Node>
  <Node debugOutput="true" guiName="DebugTrash" guiX="900" guiY="100"
        id="DEBUG_TRASH" type="TRASH"/>
  <Edge fromNode="DEBUG_INPUT:0" id="EdgeDebug" inPort="Port 0 (in)"
        outPort="Port 0 (out)" toNode="SUBGRAPH_INPUT:0"/>
  <Edge fromNode="SUBGRAPH_INPUT:0" id="Edge0" inPort="Port 0 (in)"
        outPort="Port 0 (out)" toNode="TRANSFORM:0"/>
  <Edge fromNode="TRANSFORM:0" id="Edge1" inPort="Port 0 (in)"
        outPort="Port 0 (out)" toNode="SUBGRAPH_OUTPUT:0"/>
  <Edge fromNode="SUBGRAPH_OUTPUT:0" id="EdgeOut" inPort="Port 0 (in)"
        outPort="Port 0 (out)" toNode="DEBUG_TRASH:0"/>
</Phase>
</Graph>
```

---

## 5. Debug Input / Debug Output — CRITICAL

Components that exist only for standalone testing must be flagged so they are **automatically disabled** when the subgraph runs inside a parent graph.

| Attribute | Set on | Effect |
|---|---|---|
| `debugInput="true"` | Data source nodes (readers, generators) feeding into `SubgraphInput` | Disabled in parent graph context |
| `debugOutput="true"` | Data sink nodes (Trash, writers) consuming from `SubgraphOutput` | Disabled in parent graph context |

```xml
<!-- CORRECT — debug generator, disabled in parent -->
<Node debugInput="true" guiName="DebugInput" id="DEBUG_GEN"
      recordsNumber="5" type="DATA_GENERATOR">...</Node>

<!-- CORRECT — debug trash, disabled in parent -->
<Node debugOutput="true" guiName="DebugTrash" id="DEBUG_TRASH" type="TRASH"/>
```

**WRONG:** Wiring a test data reader as a regular component feeding through `SubgraphInput` makes it a required external input — the parent graph must then supply data on that port. Only use `SubgraphInput` for ports the parent genuinely provides.

**Rule:** If it exists solely for testing, it gets `debugInput`/`debugOutput`. If the parent needs to supply it, it goes through `SubgraphInput`.

---

## 6. Public Parameters

Public parameters expose subgraph configuration to the parent graph as component attributes.

### Declaration inside subgraph

```xml
<GraphParameter label="Mapping File Path" name="MAPPING_FILE"
                public="true" required="true"
                value="${DATAIN_DIR}/mapping.csv">
  <attr name="description"><![CDATA[Path to the CSV mapping file.]]></attr>
  <SingleType multiple="true" name="file" selectionMode="file_or_directory"/>
</GraphParameter>
```

Key attributes:
- `public="true"` — exposes as component attribute in parent graph
- `required="true"` — parent must supply a value
- `<SingleType>` — sets the editor widget in Designer (omit for plain string)

### `<SingleType>` editor types

| Content | `<SingleType>` |
|---|---|
| File/directory path | `<SingleType multiple="true" name="file" selectionMode="file_or_directory"/>` |
| Single file | `<SingleType name="file"/>` |
| Sort key | `<SingleType name="sortKey"/>` |
| Plain string | `<SingleType name="string"/>` (or omit) |
| Boolean | `<SingleType name="bool"/>` |
| Integer | `<SingleType name="int"/>` |

### Linking a public parameter to a component property

```xml
<GraphParameter name="FILE_URL" public="true" required="true">
  <ComponentReference referencedComponent="READER" referencedProperty="fileURL"/>
</GraphParameter>
```

This automatically propagates the parameter value to the component's property. The parent graph then controls the component's attribute without knowing the internal component ID.

### Setting public parameter values in parent graph — DOUBLE UNDERSCORE PREFIX

**WRONG:** `<Node id="SUBGRAPH0" MAPPING_FILE="..." type="SUBGRAPH"/>` — treated as custom attribute, not a parameter override.

**CORRECT:** Prefix with `__` (two underscores):
```xml
<Node id="SUBGRAPH0" jobURL="${SUBGRAPH_DIR}/MySubgraph.sgrf"
      __MAPPING_FILE="${DATAIN_DIR}/mapping.csv" type="SUBGRAPH"/>
```

The `__` prefix is the only way to pass a public parameter override from the parent graph XML.

---

## 7. Using a Subgraph in a Parent Graph — SUBGRAPH Component

### XML attributes on the `<Node>` element

```xml
<Node id="EXTRACT"
      jobURL="${SUBGRAPH_DIR}/dwh-loader/readers/OrderFileReader.sgrf"
      __FILE_URL="${INPUT_FILE_URL}"
      guiName="Extract" guiX="125" guiY="384"
      type="SUBGRAPH">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.jobStartedAt = dictionary.jobStartedAt;
    return ALL;
}]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function void postExecute() {
    dictionary.jobStats['recordsRead'] = $in.0.recordsRead;
    return;
}]]></attr>
</Node>
```

**Critical rules:**
- `jobURL` is a plain XML attribute on `<Node>` — NOT an `<attr>` child element
- Value: `${SUBGRAPH_DIR}/path/to/file.sgrf`
- Public parameter overrides: plain XML attributes with `__` prefix
- `inputMapping` and `outputMapping` are `<attr>` child elements (CTL2 transforms)

**WRONG:**
```xml
<!-- WRONG — graphURL does not exist -->
<Node id="SG0" type="SUBGRAPH">
  <attr name="graphURL"><![CDATA[${SUBGRAPH_DIR}/MySubgraph.sgrf]]></attr>
</Node>
```

### Edges to/from SUBGRAPH component

Port outPort/inPort strings follow the subgraph's defined port numbers:
```xml
<Edge fromNode="EXTRACT:0" outPort="Port 0 (out)" .../>
<Edge toNode="EXTRACT:0" inPort="Port 0 (in)" .../>
```

Ports are numbered as defined by `<Port name="N"/>` children of `SubgraphOutput`/`SubgraphInput` in the `.sgrf` file.

---

## 8. inputMapping and outputMapping

These CTL2 transforms on the SUBGRAPH component control how data flows into and out of the subgraph's dictionary and parameters.

### inputMapping
- Runs before the subgraph starts
- `$out.1` = subgraph's dictionary (index 1 = dictionary port)
- Use to populate subgraph dictionary entries declared with `input="true"`

```xml
<attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.jobStartedAt = dictionary.jobStartedAt;
    $out.1.jobRunId = dictionary.stats['jobRunId'];
    return ALL;
}]]></attr>
```

### outputMapping
- `postExecute()` runs after the subgraph finishes
- `$in.0` = subgraph's dictionary (output entries declared with `output="true"`)
- Use to read statistics or results back into the parent graph's dictionary

```xml
<attr name="outputMapping"><![CDATA[//#CTL2
function void postExecute() {
    dictionary.stats['recordsRead'] = $in.0.recordsRead;
    return;
}]]></attr>
```

### Dictionary entries in subgraph — input vs output

```xml
<Dictionary>
  <!-- Parent writes this in before subgraph runs -->
  <Entry contentType="string" input="true"  name="jobStartedAt" output="false" type="date"/>
  <!-- Subgraph writes this; parent reads it after -->
  <Entry contentType="string" input="false" name="recordsRead"  output="true"  type="long"/>
</Dictionary>
```

---

## 9. Metadata in Subgraphs

Three approaches — pick based on how generic the subgraph needs to be:

### A. Subgraph defines explicit metadata (typed subgraph)
Define `<Metadata>` in `<Global>` and assign to edges inside the subgraph body and on `SubgraphOutput` ports. The parent graph receives this metadata via auto-propagation.
Best for: reader subgraphs that own their output schema.

### B. Subgraph requires specific input metadata (strict writer)
Assign explicit metadata to edges on `SubgraphInput` output ports. The parent graph must supply matching metadata on the connected edges.
Best for: writer subgraphs that require a known input schema.

### C. Subgraph acquires metadata from parent (generic)
Use auto-propagated metadata on all internal edges. The subgraph inherits metadata from whatever the parent connects.
Best for: generic transformer subgraphs that work with any record structure.
**Required:** Define metadata in the debug input section so the subgraph validates standalone.

---

## 10. Common Mistakes — Confirmed from Real Sessions

| Mistake | Correct form |
|---|---|
| `type="SUBGRAPH"` node uses `<attr name="graphURL">` | Use `jobURL="..."` as plain XML attribute on `<Node>` |
| Public param override without `__` prefix: `PARAM="val"` | Must be `__PARAM="val"` on the `<Node>` element |
| Test data reader wired as regular component → becomes required input port | Mark it `debugInput="true"` |
| Debug Trash without `debugOutput="true"` → runs in parent graph too | Always set `debugOutput="true"` on test sinks |
| `<SingleType>` omitted on file-path public parameter | Add `<SingleType multiple="true" name="file" selectionMode="file_or_directory"/>` |
| Metadata delimiter on individual `<Field>` elements | Set `fieldDelimiter` on `<Record>`, not `<Field>` |
| Generic subgraph with no debug metadata → fails standalone validation | Add metadata in debug input section for standalone testing |
| `connected="true"` on an optional output port | Use `connected="false"` for ports the parent may leave unconnected |
| `nature="subgraph"` missing on `<Graph>` root | Always set `nature="subgraph"` |

---

## 11. Subgraph File Location and Naming

```
graph/subgraph/               ← ${SUBGRAPH_DIR}
  readers/                    ← reader subgraphs
  writers/                    ← writer subgraphs
  transformers/                ← transformer subgraphs
  validators/                 ← validation subgraphs
  tools/                      ← utility/executor subgraphs
```

Reference from parent graph: `${SUBGRAPH_DIR}/readers/MyReader.sgrf`

---

## 12. Checklist — Before Presenting a Subgraph as Complete

- [ ] `nature="subgraph"` on `<Graph>` root
- [ ] Exactly one `SUBGRAPH_INPUT` and one `SUBGRAPH_OUTPUT` component
- [ ] Port pattern matches intent: Reader (no input), Writer (no output), Transformer (both), Executor (neither)
- [ ] `<inputPorts>`/`<outputPorts>` in `<Global>` declared consistently with `<Port>` children on boundary components
- [ ] Test data sources have `debugInput="true"`, test sinks have `debugOutput="true"`
- [ ] Public parameters have `public="true"` and appropriate `<SingleType>` editor
- [ ] File-path parameters use `<SingleType name="file" .../>` not plain string
- [ ] `ComponentReference` used to link public parameters to component properties where appropriate
- [ ] Metadata approach chosen: explicit (typed), required-input (strict), or auto-propagated (generic)
- [ ] Generic subgraphs have debug-section metadata so they validate standalone
- [ ] `validate_graph` passes on the `.sgrf` file itself

## 13. Checklist — Before Presenting SUBGRAPH Usage in Parent Graph as Complete

- [ ] `jobURL="${SUBGRAPH_DIR}/path/file.sgrf"` as plain XML attribute on `<Node>` (NOT `<attr name="graphURL">`)
- [ ] Public parameter overrides use `__PARAM_NAME="value"` prefix
- [ ] `inputMapping` and `outputMapping` are `<attr>` child elements with CTL2
- [ ] Edges use correct port numbers matching the subgraph's `<Port name="N"/>` definitions
- [ ] Dictionary entries: `input="true"` entries populated in `inputMapping.transform()`, `output="true"` entries read in `outputMapping.postExecute()`
- [ ] `validate_graph` passes on the parent `.grf` file
