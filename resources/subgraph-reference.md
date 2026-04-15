description: Subgraph reference for CloverDX .sgrf design and parent-graph integration: subgraph execution model, reader/writer/transformer/executor patterns, file and XML structure, exposed port contracts, parameter passing via __PARAM overrides, debugInput/debugOutput usage, and parent-node configuration rules.

# Subgraphs Reference — LLM Graph Building

## What is a Subgraph?

A reusable component whose logic is a graph (.sgrf file). Streams data in parallel with other components in the parent — NOT sequential. Stored in `${SUBGRAPH_DIR}` (= `graph/subgraph/`). Cannot recurse. Can nest other subgraphs.

## Four Patterns

| Pattern | Input connected | Output connected | Example |
|---|---|---|---|
| Reader | No | Yes | Reads file/DB, emits records |
| Writer | Yes | No | Receives records, writes to target |
| Transformer | Yes | Yes | Transforms/filters/enriches |
| Executor | No | No | Utility, no data exchange |

## File Structure

```xml
<Graph nature="subgraph" category="readers" name="MyReader" ...>
<Global>
  <inputPorts>
    <singlePort connected="true" name="0"/>    <!-- omit for Reader -->
  </inputPorts>
  <outputPorts>
    <singlePort connected="true" name="0"/>
    <singlePort connected="false" name="1"/>   <!-- optional port -->
  </outputPorts>
  <Metadata .../>
  <GraphParameters>
    <GraphParameter name="FILE_URL" public="true" required="true"
                    label="Source File" value="${DATAIN_DIR}/input.csv">
      <SingleType multiple="true" name="file" selectionMode="file_or_directory"/>
    </GraphParameter>
    <GraphParameterFile fileURL="workspace.prm"/>
  </GraphParameters>
  <Dictionary>
    <Entry input="true" output="false" name="jobStartedAt" type="date"/>
    <Entry input="false" output="true" name="recordsRead" type="long" dictval.value="0"/>
  </Dictionary>
</Global>
<Phase number="0">
  <!-- boundary components + logic + debug components -->
</Phase>
</Graph>
```

**Critical:** `nature="subgraph"` required on `<Graph>`. `category` optional: `readers|writers|transformers|dataQuality|joiners|others`.

## Boundary Components

### SUBGRAPH_INPUT — exactly one per .sgrf
```xml
<Node guiName="SubgraphInput" guiX="50" guiY="25" id="SUBGRAPH_INPUT0" type="SUBGRAPH_INPUT">
  <Port guiY="100" name="0"/>
</Node>
```
Each `<Port name="N"/>` = one input port on the resulting component. Required even if no input ports (Reader pattern) — add orphaned node with no edges.

### SUBGRAPH_OUTPUT — exactly one per .sgrf
```xml
<Node guiName="SubgraphOutput" guiX="700" guiY="25" id="SUBGRAPH_OUTPUT0" type="SUBGRAPH_OUTPUT">
  <Port guiY="100" name="0"/>
  <Port guiY="170" name="1"/>
</Node>
```
Unconnected output ports silently discard records (useful for optional error ports).

### Port consistency rule
`<inputPorts>`/`<outputPorts>` in `<Global>` MUST match `<Port>` children on boundary components. `connected="true"` = parent must connect edge. `connected="false"` = optional.

## Debug Input / Debug Output

Components for standalone testing — **disabled when run from parent graph**.

```xml
<!-- Test data source → feeds SubgraphInput for standalone testing -->
<Node debugInput="true" id="DEBUG_GEN" recordsNumber="5" type="DATA_GENERATOR">...</Node>
<Edge fromNode="DEBUG_GEN:0" metadata="TestMeta" toNode="SUBGRAPH_INPUT0:0"/>

<!-- Test sink → consumes SubgraphOutput for standalone testing -->
<Node debugOutput="true" id="DEBUG_TRASH" type="TRASH"/>
<Edge fromNode="SUBGRAPH_OUTPUT0:0" toNode="DEBUG_TRASH:0"/>
```

**Rule:** If it exists solely for testing → `debugInput="true"` / `debugOutput="true"`. Without these flags the component runs in parent context too.

## Public Parameters

Expose subgraph config to parent graph as component attributes.

```xml
<GraphParameter name="FILE_URL" public="true" required="true" label="Source File"
                value="${DATAIN_DIR}/input.csv">
  <SingleType multiple="true" name="file" selectionMode="file_or_directory"/>
  <ComponentReference referencedComponent="READER" referencedProperty="fileURL"/>
</GraphParameter>
```

`<SingleType>` editor types: `file` (with selectionMode), `sortKey`, `string`, `bool`, `int`. `<ComponentReference>` links param directly to component property.

### Passing values from parent — DOUBLE UNDERSCORE PREFIX

```xml
<Node id="EXTRACT" jobURL="${SUBGRAPH_DIR}/readers/MyReader.sgrf"
      __FILE_URL="${INPUT_FILE}" type="SUBGRAPH"/>
```

`__` prefix is the ONLY way to override public params. Without `__` the attribute is ignored as unknown.

## Using Subgraph in Parent Graph

```xml
<Node id="EXTRACT" guiName="Extract" guiX="125" guiY="375"
      jobURL="${SUBGRAPH_DIR}/dwh-loader/readers/OrderFileReader.sgrf"
      __FILE_URL="${INPUT_FILE_URL}"
      type="SUBGRAPH">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.jobStartedAt = dictionary.jobStartedAt;
    $out.1.jobRunId = dictionary.stats['jobRunId'];
    return ALL;
}]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function void postExecute() {
    dictionary.stats['recordsRead'] = $in.0.recordsRead;
}]]></attr>
</Node>
```

**Critical rules:**
- `jobURL` = plain XML attribute on `<Node>`, NOT `<attr name="graphURL">` (common mistake)
- `type="SUBGRAPH"` always
- Public param overrides: `__PARAM="value"` as plain XML attributes
- `inputMapping` / `outputMapping` = `<attr>` child elements with CTL2
- Edges use port numbers matching subgraph's `<Port name="N"/>` definitions

### inputMapping / outputMapping

**inputMapping** runs before subgraph starts:
- `$out.1` = subgraph dictionary (port 1 = dictionary port)
- Populates entries with `input="true"`

**outputMapping** `postExecute()` runs after subgraph finishes:
- `$in.0` = subgraph dictionary (entries with `output="true"`)
- Read results back into parent dictionary

## Metadata in Subgraphs

Three approaches:
1. **Explicit** (typed): subgraph defines `<Metadata>` and assigns to edges → parent gets auto-propagated schema. Best for readers.
2. **Required input** (strict): explicit metadata on SubgraphInput edges → parent must supply matching fields. Best for writers.
3. **Auto-propagated** (generic): inherits from parent. Need debug-section metadata for standalone validation. Best for transformers.

**Every edge must have explicit metadata.** Missing metadata on SubgraphInput/Output edges causes `Metadata on port N are not defined`.

## CTL Subgraph Functions

Four CTL functions available ONLY inside .sgrf context. Fail with error if called from a regular graph.

```
integer getSubgraphInputPortsCount()
```
Returns number of input ports declared on SubgraphInput.

```
integer getSubgraphOutputPortsCount()
```
Returns number of output ports declared on SubgraphOutput.

```
boolean isSubgraphInputPortConnected(integer portNo)
```
Returns true if the parent graph connected an edge to this input port. Port numbers 0-based. Fails if portNo is out of range.

```
boolean isSubgraphOutputPortConnected(integer portNo)
```
Returns true if the parent graph connected an edge to this output port. Port numbers 0-based. Fails if portNo is out of range.

**Use case:** Conditional logic inside a subgraph based on which optional ports the parent actually connected. Example:
```ctl
if (isSubgraphOutputPortConnected(1)) {
    // send error records to optional error port
    $out.1.errorMessage = msg;
}
```

## Common Validation Failures

### SUBGRAPH_OUTPUT → FAIL forbidden
`Invalid subgraph layout. Edge from [SubgraphOutput:X] to [Fail:Y] is not allowed.`
**Fix:** Route through SIMPLE_GATHER as splitter — port 0 to SUBGRAPH_OUTPUT, port 1 to FAIL.

### Missing SubgraphInput
`Missing SubgraphInput component.`
**Fix:** Every subgraph needs exactly one SUBGRAPH_INPUT node, even Reader pattern (add orphaned node).

### REST_CONNECTOR endpoint with ${PARAM} not found in OpenAPI
**Fix:** Use `{paramName}` template in endpoint + `requestParameters` attribute:
```xml
endpoint="/data-sets/{dataSetCode}/rows"
requestParameters="dataSetCode=${DATA_SET_CODE}&#10;"
```
CTL: `$out.2.rowId = "" + $in.0.rowId;` (NOT `(string)` cast — invalid CTL2).

### Metadata inside Phase instead of Global
`Cannot find metadata ID 'MetaXxx'.`
**Fix:** All `<Metadata>` must be in `<Global>`.

### Parameterized transform needs non-empty default
`Transformation is not defined.`
**Fix:** GraphParameter with CTL default value for validator to compile:
```xml
<GraphParameter name="INPUT_MAPPING">
  <attr name="value">//#CTL2
function integer transform() { $out.0.* = $in.0.*; return ALL; }</attr>
</GraphParameter>
```

### Incompatible input metadata
`Incompatible input metadata. Input metadata on port #0 does not match subgraph metadata.`
**Fix:** Insert REFORMAT between caller and subgraph to map fields. Keep subgraph metadata clean.

### __PARAM overrides stale after inserting REFORMAT
When inserting field-renaming REFORMAT between caller and subgraph, update all `__PARAM` overrides that reference old field names from upstream metadata.

### REST_CONNECTOR "Cannot write to output port '1'"
Usually a cascade from topology errors. Fix topology first (SIMPLE_GATHER, forbidden edges) — error disappears when port 1 gets a connected edge.

### DATA_GENERATOR import metadata from ${PARAM} with no default
**Fix:** Provide default `.fmt` path: `value="${META_DIR}/sample.fmt"`.

### requestParameters double-escaped via graph_edit_properties
**Fix:** Use literal newline in value string, not `&#13;&#10;`. One param per line.

## File Layout Convention

```
graph/subgraph/
  readers/          ← reader subgraphs
  writers/          ← writer subgraphs
  transformers/     ← transformer subgraphs
  validators/       ← validation subgraphs
  tools/            ← utility/executor subgraphs
```

## Checklist — Subgraph File (.sgrf)

- `nature="subgraph"` on `<Graph>`
- One SUBGRAPH_INPUT, one SUBGRAPH_OUTPUT
- `<inputPorts>` / `<outputPorts>` consistent with boundary `<Port>` children
- Debug sources: `debugInput="true"`, debug sinks: `debugOutput="true"`
- Public params: `public="true"`, `<SingleType>` editor, `<ComponentReference>` where appropriate
- Every edge has explicit metadata
- All `<Metadata>` in `<Global>`, not `<Phase>`

## Checklist — Parent Graph Using Subgraph

- `jobURL="..."` as plain XML attribute (NOT `<attr name="graphURL">`)
- Public param overrides use `__PARAM="value"` prefix
- `inputMapping` / `outputMapping` as `<attr>` children
- Edge port numbers match subgraph's `<Port name="N"/>` definitions
- Dictionary entries: `input="true"` populated in inputMapping.transform(), `output="true"` read in outputMapping.postExecute()
