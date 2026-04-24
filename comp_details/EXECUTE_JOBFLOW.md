# CloverDX EXECUTE_JOBFLOW — LLM Generation Reference

> Authoritative, generation-ready reference for CloverDX EXECUTE_JOBFLOW (ExecuteJobflow).
> Incorporates confirmed working patterns from MiscExamples and BasicFeatures sandboxes.
> EXECUTE_JOBFLOW is the standard component for launching `.jbf` child jobflows
> from a parent jobflow. Its API is identical to EXECUTE_GRAPH — only the target file type
> and semantic intent differ.
> For launching `.grf`/`.sgrf` child graphs, see the EXECUTE_GRAPH reference.

---

## WHEN TO USE EXECUTE_JOBFLOW VS ALTERNATIVES

| Component | Use when |
|---|---|
| **EXECUTE_JOBFLOW** | **Default choice for running a `.jbf` child jobflow from a parent jobflow.** Same API as EXECUTE_GRAPH, but makes the orchestration intent explicit and enables drag-drop creation in Designer. |
| EXECUTE_GRAPH | Semantically identical API, target is `.grf` or `.sgrf`. **Either component accepts any target at runtime** — EXECUTE_JOBFLOW is a naming convention, not a hard constraint. |
| EXECUTE_SCRIPT | Same port and mapping model. Use when the child is a script (shell, Groovy, Python). |
| MONITOR_JOBFLOW | Not a launcher — used to wait for a previously started async EXECUTE_JOBFLOW child. Accepts `runId` token. |
| KILL_JOBFLOW | Terminates a running child jobflow by `runId` or `executionGroup`. |

**Decision rule:** Use `EXECUTE_JOBFLOW` when the target `jobURL` is a `.jbf` file. This makes the jobflow hierarchy visually clear in Designer. If `jobURL` is computed dynamically at runtime, set `skipCheckConfig="true"` or validation will fail at design time.

**Designer tip:** Dragging a `.jbf` file from the Project Explorer and dropping it into a jobflow canvas automatically creates an `EXECUTE_JOBFLOW` node.

---

## COMPONENT SKELETON

### Minimal — static jobURL, no token enrichment needed

```xml
<Node
  type="EXECUTE_JOBFLOW"
  id="RUN_WEEKLY_LOAD"
  guiName="Run weekly load"
  guiX="400" guiY="200"
  jobURL="${JOBFLOW_DIR}/WeeklyLoad.jbf"/>
```

No input/output port connections required. The component runs the child jobflow and
propagates success or aborts the parent (default `stopOnFail="true"`).

### Static jobURL with parameter injection

```xml
<Node
  type="EXECUTE_JOBFLOW"
  id="RUN_INTEGRATION"
  guiName="Run integration"
  guiX="400" guiY="200"
  jobURL="${JOBFLOW_DIR}/Integration.jbf">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.INPUT_DIR   = "${DATAIN_DIR}/batch_" + $in.0.batchId;
    $out.1.RUN_DATE    = dateFormatLocale(today(), "yyyy-MM-dd", "en");
    return ALL;
}
]]></attr>
</Node>
```

`$out.1` maps to the child jobflow's public parameters by name.

### Dynamic jobURL with per-token child selection

```xml
<Node
  type="EXECUTE_JOBFLOW"
  id="DISPATCH_WORKFLOW"
  guiName="Dispatch workflow"
  guiX="600" guiY="300"
  jobURL="${JOBFLOW_DIR}/DefaultWorkflow.jbf"
  executorsNumber="2"
  skipCheckConfig="true"
  stopOnFail="false">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.jobURL         = "${JOBFLOW_DIR}/" + $in.0.workflowName + ".jbf";
    $out.0.executionLabel = $in.0.clientId + "|" + $in.0.workflowName;
    $out.1.CLIENT_ID      = $in.0.clientId;
    $out.1.BATCH_DATE     = $in.0.batchDate;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*          = $in.0.*;
    $out.0.jobStatus  = $in.1.status;
    $out.0.duration   = $in.1.duration;
    $out.0.errorText  = $in.1.errMessage;
    return ALL;
}
]]></attr>
</Node>
```

### Asynchronous execution — launch and capture runId for monitoring

```xml
<Node
  type="EXECUTE_JOBFLOW"
  id="START_PARALLEL_FLOW"
  guiName="Start parallel flow"
  guiX="300" guiY="200"
  jobURL="${JOBFLOW_DIR}/ParallelProcessor.jbf"
  executionType="asynchronous">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.PARTITION_ID   = string($in.0.partitionId);
    $out.0.executionLabel = "partition_" + $in.0.partitionId;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*     = $in.0.*;
    $out.0.runId = $in.1.runId;
    return ALL;
}
]]></attr>
</Node>
```

Connect port 0 output to a `MONITOR_JOBFLOW` node to wait for completion.

---

## NODE-LEVEL ATTRIBUTES

### Target

| Attribute (XML) | Required | Description |
|---|---|---|
| `type="EXECUTE_JOBFLOW"` | yes | Component type |
| `jobURL` | yes* | Path to the target `.jbf`. Use `${JOBFLOW_DIR}/...` or `${GRAPH_DIR}/...` depending on sandbox conventions. *Can be omitted if set dynamically in `inputMapping` — but then `skipCheckConfig="true"` is mandatory. |
| `skipCheckConfig` | no | **Must be `true` whenever `jobURL` is computed in `inputMapping`.** Without it, design-time checkConfig sees an empty URL and fails. Default: `false`. |
| `propagateParameters` | no | Auto-pass matching public parameters from parent to child jobflow by name. Default: `false`. Prefer explicit `inputMapping` for clarity. |

### Execution

| Attribute (XML) | Default | Description |
|---|---|---|
| `executionType` | `synchronous` | `synchronous`: block until child finishes. `asynchronous`: return immediately with `runId`; pipe to `MONITOR_JOBFLOW` to wait. |
| `executorsNumber` | `1` | Number of parallel synchronous instances. Token stream is divided across executors — up to N child jobflows run concurrently. |
| `timeout` | `0` (unlimited) | Milliseconds before the child jobflow is killed. **Set whenever a child jobflow contains monitoring or wait logic that could block indefinitely.** |
| `daemon` | `false` | `true`: async child jobflow is allowed to outlive the parent. Required for fire-and-forget async patterns. |
| `executionGroup` | — | Tag string for mass-kill via `KILL_JOBFLOW`. All children with the same group can be terminated together. |
| `executionLabel` | — | Label displayed in Server run history per child instance. **Always set in `inputMapping` for iteration nodes.** Without it, the run history shows identical rows for every iteration. |
| `clusterNodeId` | — | Pin execution to a specific cluster node. |
| `locale` | — | Override locale for child execution. |
| `timeZone` | — | Override time zone for child execution. |

### Error handling

| Attribute (XML) | Default | Description |
|---|---|---|
| `stopOnFail` | `true` | `true`: child failure aborts the parent jobflow (error port can be unconnected). `false`: failures flow as tokens to error port (port 1) — required for retry loops, conditional recovery, and tolerated failures. |
| `redirectErrorOutput` | `false` | `true`: both success and failure tokens flow to port 0. Distinguish by `$in.1.status` in `outputMapping`. Use for try/finally patterns where cleanup must run regardless of child outcome. |

### Mappings

| Attribute (XML) | Description |
|---|---|
| `inputMapping` | CTL2/CDATA. Maps the incoming token to RunConfig (`$out.0`), JobParameters (`$out.1`), and child dictionary inputs (`$out.2`). Executed before the child jobflow starts. |
| `outputMapping` | CTL2/CDATA. Maps child RunStatus and dictionary outputs back onto the outgoing token (port 0 — success). **Must begin with `$out.0.* = $in.0.*;`.** |
| `errorMapping` | CTL2/CDATA. Same shape as `outputMapping`. Applied on error port (port 1). If absent, raw RunStatus is forwarded. |

---

## MAPPINGS — THE CORE CONCEPT

EXECUTE_JOBFLOW has three distinct mapping stages: `inputMapping` (before child starts),
`outputMapping` (after child succeeds), and `errorMapping` (after child fails, when
`stopOnFail="false"`). Each stage has a different set of available `$in` and `$out` records.

### Port numbering in mappings

**inputMapping — `$out` records written by the LLM:**

| Record | Meaning | Key fields |
|---|---|---|
| `$out.0` | RunConfig | `jobURL`, `executionType`, `executionLabel`, `timeout`, `daemon`, `executionGroup`, `skipCheckConfig` |
| `$out.1` | JobParameters | Child jobflow's public parameters by name: `$out.1.PARAM_NAME = value` |
| `$out.2` | Dictionary (child input entries) | Child jobflow's `input="true"` dictionary entries by name |

**inputMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming token record — all user-defined fields plus any injected RunConfig fields from upstream |

**outputMapping and errorMapping — `$in` records available to the LLM:**

| Record | Meaning |
|---|---|
| `$in.0` | Incoming token (same record that arrived at the input port) |
| `$in.1` | RunStatus of the completed child jobflow (see RunStatus fields below) |
| `$in.2` | Dictionary — child jobflow's `output="true"` dictionary entries by name |
| `$in.3` | Tracking — per-component record counts from the child jobflow run |

**outputMapping and errorMapping — `$out` records written by the LLM:**

| Record | Meaning |
|---|---|
| `$out.0` | Outgoing token record |

---

## INPUT MAPPING

### Setting child jobflow public parameters

```ctl
//#CTL2
function integer transform() {
    $out.1.INPUT_DIR  = "${DATAIN_DIR}/batch_" + $in.0.batchId;
    $out.1.RUN_DATE   = dateFormatLocale(today(), "yyyy-MM-dd", "en");
    $out.1.DRY_RUN    = "false";
    return ALL;
}
```

`$out.1` fields correspond to public parameter names declared in the child jobflow.
Values are always strings (parameter type is string in the graph engine).

### Setting parameters as a map (for dynamic sets)

```ctl
//#CTL2
function integer transform() {
    map[string,string] params;
    params["CLIENT_ID"]  = $in.0.clientId;
    params["BATCH_DATE"] = $in.0.batchDate;
    $out.0.jobParameters = params;
    return ALL;
}
```

Both approaches (`$out.1.PARAM` and `$out.0.jobParameters`) can be combined in the same mapping.

### Dynamic jobURL with executionLabel

```ctl
//#CTL2
function integer transform() {
    $out.0.jobURL         = "${JOBFLOW_DIR}/" + $in.0.workflowName + ".jbf";
    $out.0.executionLabel = $in.0.clientId + "|" + $in.0.workflowName;
    return ALL;
}
```

`jobURL` set via `$out.0` takes precedence over the static `jobURL` attribute.
`executionLabel` appears per-row in Server history — essential for diagnosing iteration runs.

### Writing to child jobflow dictionary inputs

```ctl
//#CTL2
function integer transform() {
    $out.0.executionLabel = $in.0.batchId;
    $out.2.jobStartedAt   = today();             // child dict input="true" entry
    $out.2.parentRunId    = $in.0.runId;         // propagate parent run context
    return ALL;
}
```

Dictionary entries on `$out.2` correspond to `input="true"` entries declared in the child jobflow's `<Dictionary>` section.

---

## OUTPUT MAPPING

### Mandatory pass-through

```ctl
//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;    // ALWAYS the first line — silently drops token fields if missing
    return ALL;
}
```

Omitting `$out.0.* = $in.0.*;` is the single most common and silent data-loss bug in jobflows.
Every upstream token field disappears without error.

### Capturing run status

```ctl
//#CTL2
function integer transform() {
    $out.0.*          = $in.0.*;
    $out.0.jobStatus  = $in.1.status;
    $out.0.runId      = $in.1.runId;
    $out.0.duration   = $in.1.duration;
    $out.0.errorText  = $in.1.errMessage;
    return ALL;
}
```

### `$in.1` RunStatus fields

| Field | Type | Description |
|---|---|---|
| `runId` | long | Child jobflow run ID. Required for `MONITOR_JOBFLOW` in async patterns. |
| `originalJobURL` | string | Resolved path of the jobflow that was executed. |
| `submitTime` | date | Time the child was submitted to the server. |
| `startTime` | date | Time the child actually started executing. |
| `endTime` | date | Time the child finished. |
| `duration` | long | Wall-clock duration in milliseconds (includes all child graphs and nested jobflows). |
| `executionGroup` | string | Execution group tag. |
| `executionLabel` | string | Execution label. |
| `status` | string | `FINISHED_OK`, `ERROR`, `ABORTED`, `TIMEOUT`, … |
| `errException` | string | Exception class name on failure. |
| `errMessage` | string | Human-readable error message on failure. |
| `errComponent` | string | Component ID where the failure occurred (may be inside a nested graph). |
| `errComponentType` | string | Component type where the failure occurred. |

### Reading child jobflow dictionary output entries

```ctl
//#CTL2
function integer transform() {
    $out.0.*              = $in.0.*;
    $out.0.recordsLoaded  = $in.2.recordsLoaded;  // child dict output="true" entry
    $out.0.errorCount     = $in.2.errorCount;
    return ALL;
}
```

`$in.2` fields correspond to `output="true"` entries declared in the child jobflow's
`<Dictionary>` section. This is the standard mechanism for passing aggregated metrics
or results up to the parent jobflow.

**CLO-8807 warning:** When the child jobflow writes to a `map` dictionary entry that was populated
from its own upstream (`input="true"`), random crashes can occur. If the child jobflow reads and
then modifies a map dictionary entry, ensure it copies the value to a separate `output="true"` entry
before modifying — never write back to the same entry.

---

## ERROR MAPPING

Same `$in` / `$out` structure as `outputMapping`. Applied when the child jobflow fails and
`stopOnFail="false"`. If `errorMapping` is absent, the raw RunStatus is forwarded to port 1.

### Typical error mapping — mark token and preserve context

```ctl
//#CTL2
function integer transform() {
    $out.0.*          = $in.0.*;
    $out.0.jobStatus  = "ERROR";
    $out.0.errorText  = $in.1.errMessage;
    $out.0.errorComp  = $in.1.errComponent;
    return ALL;
}
```

### `redirectErrorOutput="true"` — single output port for both outcomes

When `redirectErrorOutput="true"`, both success and failure tokens flow to port 0.
`outputMapping` handles both — distinguish by `$in.1.status`:

```ctl
//#CTL2
function integer transform() {
    $out.0.*         = $in.0.*;
    $out.0.jobStatus = $in.1.status;
    $out.0.errorText = ($in.1.status != "FINISHED_OK") ? $in.1.errMessage : "";
    return ALL;
}
```

Use this for try/finally patterns — the downstream cleanup node always receives a token
regardless of whether the child jobflow succeeded or failed.

---

## PORTS

| Port | Direction | XML string | Description |
|---|---|---|---|
| Port 0 | in (optional) | `Port 0 (in)` | Incoming token. One child execution per token. |
| Port 0 | out (optional) | `Port 0 (out)` | Success token — one per completed child jobflow. |
| Port 1 | out (optional) | `Port 1 (error)` | Failure token — only when `stopOnFail="false"`. |

All ports are optional. Without an input port, the component executes once.
Without output ports, success/failure only affects parent jobflow continuation (`stopOnFail`).

---

## TYPICAL GRAPH PATTERNS

### Nested jobflow pipeline — sequential stages as child jobflows

Each stage of an ETL pipeline encapsulated as its own `.jbf`, orchestrated from a parent:

```xml
<Phase number="0">
  <Node type="EXECUTE_JOBFLOW" id="EXTRACT"
        jobURL="${JOBFLOW_DIR}/01_Extract.jbf"/>
</Phase>
<Phase number="1">
  <Node type="EXECUTE_JOBFLOW" id="TRANSFORM"
        jobURL="${JOBFLOW_DIR}/02_Transform.jbf"/>
</Phase>
<Phase number="2">
  <Node type="EXECUTE_JOBFLOW" id="LOAD"
        jobURL="${JOBFLOW_DIR}/03_Load.jbf"/>
</Phase>
```

Phases enforce ordering without requiring token edges between steps.

### Per-client dispatch — dynamic child jobflow selection

```
GET_JOB_INPUT → REFORMAT(build client list) → EXECUTE_JOBFLOW(dynamic, executorsNumber=3) → AGGREGATE → SUCCESS
```

```xml
<Node
  type="EXECUTE_JOBFLOW"
  id="DISPATCH_CLIENT"
  guiName="Dispatch client"
  jobURL="${JOBFLOW_DIR}/ClientBase.jbf"
  executorsNumber="3"
  skipCheckConfig="true"
  stopOnFail="false">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.jobURL         = "${JOBFLOW_DIR}/" + $in.0.clientCode + ".jbf";
    $out.0.executionLabel = $in.0.clientCode;
    $out.1.REPORTING_DATE = $in.0.reportingDate;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*             = $in.0.*;
    $out.0.jobStatus     = $in.1.status;
    $out.0.duration      = $in.1.duration;
    $out.0.errorText     = $in.1.errMessage;
    $out.0.recordsLoaded = $in.2.recordsLoaded;
    return ALL;
}
]]></attr>
</Node>
```

### Async child jobflow fan-out + MONITOR_JOBFLOW

```
LIST_FILES → EXECUTE_JOBFLOW(asynchronous) → MONITOR_JOBFLOW → BARRIER → SUCCESS
```

```xml
<Node type="EXECUTE_JOBFLOW" id="START_FLOWS"
      jobURL="${JOBFLOW_DIR}/FileProcessor.jbf"
      executionType="asynchronous">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.1.FILE_URL        = $in.0.URL;
    $out.0.executionLabel  = $in.0.name;
    return ALL;
}
]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*     = $in.0.*;
    $out.0.runId = $in.1.runId;
    return ALL;
}
]]></attr>
</Node>
<Node type="MONITOR_JOBFLOW" id="MONITOR_FLOWS"
      jobURL="${JOBFLOW_DIR}/FileProcessor.jbf">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.runId = $in.0.runId;
    return ALL;
}
]]></attr>
</Node>
```

### Dictionary-based result aggregation

Child jobflow declares `output="true"` dictionary entries; parent reads them via `$in.2`:

```xml
<!-- In child jobflow's <Dictionary> section: -->
<Entry name="recordsLoaded" output="true" type="long" dictval.value="0"/>
<Entry name="errorCount" output="true" type="long" dictval.value="0"/>
```

```xml
<!-- In parent's EXECUTE_JOBFLOW outputMapping: -->
<attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.*               = $in.0.*;
    $out.0.recordsLoaded   = $in.2.recordsLoaded;
    $out.0.errorCount      = $in.2.errorCount;
    $out.0.jobStatus       = $in.1.status;
    return ALL;
}
]]></attr>
```

---

## EDGE DECLARATIONS

```xml
<!-- Token in -->
<Edge fromNode="UPSTREAM:0" id="Edge0" outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="RUN_CHILD:0" metadata="MetaToken"/>

<!-- Success token out -->
<Edge fromNode="RUN_CHILD:0" id="Edge1" outPort="Port 0 (out)"
      inPort="Port 0 (in)" toNode="DOWNSTREAM:0" metadata="MetaToken"/>

<!-- Error token out (requires stopOnFail="false") -->
<Edge fromNode="RUN_CHILD:1" id="Edge2" outPort="Port 1 (error)"
      inPort="Port 0 (in)" toNode="ERROR_HANDLER:0" metadata="MetaToken"/>
```

---

## TOKEN RECORD DESIGN

Token metadata is user-defined. Fields accumulate state across steps. Recommended pattern
for a jobflow that dispatches child jobflows and collects results:

```xml
<Record name="Token" type="delimited" fieldDelimiter="|" recordDelimiter="\n">
    <!-- Dispatch identity — used to select and label the child jobflow -->
    <Field name="clientCode" type="string"/>
    <Field name="workflowName" type="string"/>
    <Field name="reportingDate" type="string"/>
    <!-- Execution context — populated from RunStatus in outputMapping -->
    <Field name="runId" type="long" trim="true"/>
    <Field name="jobStatus" type="string"/>
    <Field name="duration" type="long" trim="true"/>
    <Field name="errorText" type="string"/>
    <!-- Metrics from child dictionary output entries -->
    <Field name="recordsLoaded" type="long" trim="true"/>
    <Field name="errorCount" type="long" trim="true"/>
</Record>
```

---

## GENERATION RULES FOR LLM

Always include:
- `type="EXECUTE_JOBFLOW"`
- `jobURL` (static) OR dynamic `jobURL` in `inputMapping` — never both
- `skipCheckConfig="true"` whenever `jobURL` is computed in `inputMapping`
- `$out.0.* = $in.0.*;` as the first line of every `outputMapping`
- `executionLabel` set in `inputMapping` for any node that iterates over multiple tokens

Parent–child dictionary contracts:
- Child jobflow must declare `input="true"` entries for values the parent writes to `$out.2`
- Child jobflow must declare `output="true"` entries for values the parent reads from `$in.2`
- Never write back to the same `map`-typed dictionary entry that was received as input — CLO-8807 crash risk

When using parallel synchronous execution (`executorsNumber > 1`):
- The token stream is split across executors — each token runs one child jobflow instance
- Output token order is non-deterministic

When using async execution:
- Set `daemon="true"` if the child jobflow must outlive the parent
- Always pipe port 0 to `MONITOR_JOBFLOW` to wait for completion
- Only direct children are monitorable — a `runId` from a grandchild cannot be monitored

Error handling — decide for each node:
- `stopOnFail="true"` (default): child failure aborts parent; error port can be unconnected
- `stopOnFail="false"`: connect error port 1 to handle failures as tokens
- `redirectErrorOutput="true"`: both outcomes to port 0; `outputMapping` distinguishes by `$in.1.status`

Parameter passing — two mechanisms:
- `$out.1.PARAM_NAME = value` for known parameter names
- `$out.0.jobParameters = myMap` for dynamic or computed parameter sets
- Both can coexist in the same `inputMapping`

Do NOT:
- Set `jobURL` statically AND override it in `inputMapping` — mapping wins but creates confusion
- Forget `skipCheckConfig="true"` for dynamic `jobURL` — validation fails at design time
- Omit `$out.0.* = $in.0.*;` in `outputMapping` — all upstream token fields silently disappear
- Leave error port unconnected when `stopOnFail="false"` — the error token is lost
- Use `EXECUTE_JOBFLOW` for `.grf` targets — use `EXECUTE_GRAPH` for those
- Set `executionLabel` as a static attribute for iteration nodes — it will be the same for every token; always set it in `inputMapping`
- Attempt to monitor a grandchild's `runId` with `MONITOR_JOBFLOW` — only direct children work

---

## COMMON MISTAKES

| Mistake | Correct approach |
|---|---|
| Dynamic `jobURL` without `skipCheckConfig="true"` | Add `skipCheckConfig="true"` whenever `jobURL` is set in `inputMapping` |
| Missing `$out.0.* = $in.0.*;` in `outputMapping` | Always make it the first line — silently drops all upstream token fields if omitted |
| Static `executionLabel` on iteration node | Set `$out.0.executionLabel` in `inputMapping` — must be per-token to be useful |
| Error port unconnected with `stopOnFail="false"` | Connect to error handler, `TRASH`, or accumulator — unconnected loses the token |
| Using `$in.1.*` instead of `$in.0.*` for pass-through | `$in.0` is the incoming token; `$in.1` is RunStatus — mixing them loses token fields |
| Reading child dictionary without `output="true"` declaration | Child must declare the entry with `output="true"` — otherwise `$in.2.fieldName` is empty |
| Writing child dictionary without `input="true"` declaration | Child must declare the entry with `input="true"` — otherwise `$out.2.fieldName` is silently ignored |
| CLO-8807: modifying a received `map` dict entry in-place | Copy it to a separate `output="true"` entry first; never write back to the same `input="true"` map entry |
| Forgetting `daemon="true"` for async fire-and-forget | Without it, async children are killed when the parent jobflow ends |
| Monitoring a grandchild's runId | Only direct children are monitorable — pass the `runId` from the child, not from nested layers |
| Using EXECUTE_JOBFLOW for `.grf`/`.sgrf` targets | Use EXECUTE_GRAPH for `.grf`/`.sgrf` — EXECUTE_JOBFLOW is for `.jbf` targets |
