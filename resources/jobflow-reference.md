description: Jobflow reference for CloverDX .jbf - jobs orchestration design: sequential token-driven execution model, controlled parallel branching via SIMPLE_COPY, phase behavior, EXECUTE_JOBFLOW/EXECUTE_GRAPH usage, and practical routing patterns for success/error handling.

# Jobflows Reference — LLM

## Model
Jobflow (.jbf) = token-driven orchestrator. Unlike graphs (components run in parallel), jobflow components execute **sequentially by default** — a token triggers A, A completes, token passes to B.
- Parallelism: fork token via SIMPLE_COPY → multiple components start simultaneously
- File extension `.jbf`. `nature="jobflow"` required on `<Graph>`.
- Phases work same as graphs: all phase N components finish before phase N+1.
- Any component (DB_INPUT_TABLE, REFORMAT, NORMALIZER, etc.) can be used in a jobflow, not just jobControl types.

## File Structure
```xml
<Graph name="MyJobflow" nature="jobflow">
<Global>
  <GraphParameters>
    <GraphParameterFile fileURL="workspace.prm"/>
    <GraphParameter name="INPUT_DIR" value="${DATAIN_DIR}" public="true"/>
  </GraphParameters>
  <Dictionary>
    <Entry name="recordsProcessed" type="long" input="false" output="true" dictval.value="0"/>
    <Entry name="startDate" type="date" input="true" output="false"/>
  </Dictionary>
  <ExecutionConfig>
    <Property name="max_running_concurrently" value="1"/>  <!-- optional; limits concurrent instances -->
  </ExecutionConfig>
</Global>
<Phase number="0">...</Phase>
</Graph>
```

---

## EXECUTE_GRAPH / EXECUTE_JOBFLOW
Run a .grf/.sgrf or .jbf. Identical API. Ports: input 0 (optional token), output 0 (success), output 1 (error).

**Key attributes:**
- `jobURL` — required. Path to .grf/.jbf. Can be overridden in inputMapping via `$out.0.jobURL`.
- `executionType` — `synchronous` (default, waits) | `asynchronous` (fires and returns runId immediately)
- `timeout` — max run time (0=unlimited). Supports units: `30s`, `5m`. Ignored for async.
- `stopOnFail` — default `true`. Set `false` to continue processing tokens after a failure.
- `executorsNumber` — default 1. For synchronous only: N tokens processed in parallel simultaneously.
- `propagateParameters` — `false` (default). Auto-pass matching public params to child.
- `executionGroup` — string tag for mass-kill via KILL_GRAPH.
- `daemon` — `false` (default). Set `true` so child can outlive parent jobflow.
- `redirectErrorOutput` — `false` (default). Set `true` to route failures to port 0.
- `skipCheckConfig` — required when `jobURL` is set dynamically in inputMapping (URL unknown at design time).

**inputMapping — three output records:**
| Record | Port | Key fields |
|---|---|---|
| RunConfig | `$out.0` | `jobURL`, `executionType`, `timeout`, `executionGroup`, `executionLabel`, `daemon` |
| JobParameters | `$out.1` | All public params of the child graph (auto-populated from `jobURL` template) |
| Dictionary | `$out.2` | Input dict entries of the child graph (`input="true"`) |

**outputMapping — four input records:**
| Record | Port | Key fields |
|---|---|---|
| Input token | `$in.0` | Original incoming token — use for pass-through |
| RunStatus | `$in.1` | `runId`, `status`, `startTime`, `endTime`, `duration`, `errMessage`, `errComponent`, `originalJobURL` |
| Dictionary | `$in.2` | Output dict entries of child (`output="true"`) |
| Tracking | `$in.3` | Phase/component metrics |

Empty outputMapping/errorMapping → RunStatus fields mapped by name.

**Always pass through token fields:** `$out.0.* = $in.0.*;` then overwrite specific fields. Without this, upstream fields (file paths, IDs, timestamps) are lost.

**Dynamic jobURL + executionLabel pattern:**
```xml
<Node type="EXECUTE_GRAPH" skipCheckConfig="true" jobURL="${DEFAULT_WORKER}">
  <attr name="inputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.jobURL = $in.0.workerUrl;          // override URL from token
    $out.0.executionLabel = $in.0.fileName;   // visible in Server UI per iteration
    $out.1.INPUT_FILE_URL = $in.0.fileUrl;    // pass param to child
    $out.2.jobStartedAt = $in.0.startTime;    // pass dict entry to child
    return ALL;
}]]></attr>
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.* = $in.0.*;                           // pass-through token
    $out.0.jobStatus = $in.1.status;
    $out.0.jobStatistics = $in.2.__jobStatistics; // read child output dict
    return ALL;
}]]></attr>
</Node>
```

**Async + monitor pattern:**
```xml
<Node type="EXECUTE_GRAPH" executionType="asynchronous">
  <attr name="outputMapping"><![CDATA[//#CTL2
function integer transform() {
    $out.0.runId = $in.1.runId;  // capture for MONITOR_GRAPH
    return ALL;
}]]></attr>
</Node>
<!-- then: token with runId → MONITOR_GRAPH → SUCCESS -->
```

---

## EXECUTE_SCRIPT
Run shell/Python/Perl script per token. Same port pattern as EXECUTE_GRAPH (input 0, output 0, error port 1).

Key attributes: `script` (inline), `scriptURL` (file; takes precedence), `interpreter` (`/bin/bash ${}`), `timeout`, `stopOnFail`, `redirectErrorOutput`.

inputMapping RunConfig fields: `script`, `scriptURL`, `interpreter`, `workingDirectory`, `timeout`, `stdIn`, `stdOutFileURL`, `errOutFileURL`, `append`, `dataCharset`.
outputMapping RunResult fields: `stdOut`, `errOut`, `exitValue`, `startTime`, `stopTime`, `duration`, `reachedTimeout`, `errMessage`.

Dynamic script: `$out.0.script = "process.sh " + $in.0.filePath;`

---

## MONITOR_GRAPH / MONITOR_JOBFLOW
Watch async-started jobs. MonitorJobflow identical to MonitorGraph.
inputMapping outputs: `$out.0.runId`, `$out.0.timeout`, `$out.0.monitoringInterval` (periodic status while running).
outputMapping/errorMapping: same records as EXECUTE_GRAPH ($in.1=RunStatus, $in.2=Dictionary, $in.3=Tracking).
- `return STOP` in outputMapping stops monitoring early.
- Only direct child jobs can be monitored.
- No input port: monitors single static `runId` attribute.

---

## BARRIER
Wait for all parallel branches before continuing.
Ports: 1-N inputs, output 0 (success), output 1 (failure optional).

| Attribute | Values | Meaning |
|---|---|---|
| `chunkPartitioner` | `ALL` (default) / `TUPLE` | ALL=all tokens one group; TUPLE=tokens grouped by key |
| `successEvaluator` | `AND` (default) / `OR` | AND=all must succeed; OR=at least one must succeed |
| `chunkProcessor` | `SINGLE` / `ALL` | SINGLE=one output token; ALL=one per input token |

All branches MUST deliver exactly one token or BARRIER deadlocks.

---

## CONDITION
Route token by boolean expression. Identical to EXT_FILTER.
Ports: input 0, output 0 (true), output 1 (false, optional).
```xml
<Node type="CONDITION">
  <attr name="filterExpression"><![CDATA[$in.0.status == "OK" && $in.0.count > 0]]></attr>
</Node>
```

---

## TOKEN_GATHER
Fan-in from N parallel branches to one stream. Copies each token to ALL connected output ports.
Ports: 1-N inputs, 1-N outputs. Use to collect error tokens from multiple parallel branches → single FAIL.

---

## LOOP
While-loop on tokens.
- Input 0: entry (initial or next token)
- Input 1: token returning from loop body — MUST receive every token sent from output 1
- Output 0: condition false → exit loop
- Output 1: condition true → loop body

```xml
<Node type="LOOP">
  <attr name="whileCondition"><![CDATA[$in.1.iterationNumber < 5]]></attr>
</Node>
```
`$in.1.iterationNumber` = auto-incremented (0-based). `$in.0.*` = token fields.
All loop edges auto-converted to fast-propagate. Token duplication/loss = deadlock.

---

## SUCCESS / FAIL
**SUCCESS:** Terminal. mapping can log a message + set output dict entries.
```ctl
function integer transform() {
    dictionary.__jobStatistics = $in.0.jobStatistics; // write output dict at end
    return ALL;
}
```

**FAIL:** Aborts parent job. No input port → fails immediately when phase starts.
mapping `$out.0.errorMessage` = abort message; can also set output dict entries simultaneously:
```ctl
function integer transform() {
    $out.0.errorMessage    = $in.0.errorText;
    $out.1.__jobStatistics = $in.0.jobStatistics;  // return partial stats to parent
    return ALL;
}
```
Priority: mapping errorMessage > `errorMessage` attribute > "user abort".

---

## KILL_GRAPH / KILL_JOBFLOW
Abort by runId or executionGroup. Attributes: `runId`, `executionGroup`, `killDaemonChildren`.
inputMapping: `$out.0.runId`.

---

## GET_JOB_INPUT / SET_JOB_OUTPUT
**GET_JOB_INPUT:** No input, output 0. Emits exactly one record. Maps input dict entries + graph params.
Use instead of DATA_GENERATOR when params/dict drive initialization:
```ctl
$out.0.fileName   = getParamValue("INPUT_FILE");
$out.0.workingDir = getParamValue("WORKING_DIR") + "/wd_${RUN_ID}";
```

**SET_JOB_OUTPUT:** Input 0, no output. Maps incoming record → output dict entries. First record sets; subsequent override.

---

## SLEEP
Delay each token. Ports: input 0, output 0-N (all copies).
Static: `delay="2s"`. Dynamic inputMapping: `$out.0.delayMillis = $in.0.waitMs;`
Unconnected SLEEP in a separate phase = phase-level pause between phases.
Set outgoing edge to "Direct fast propagate" for immediate per-record output.

---

## Dictionary — Parent/Child Exchange
```xml
<!-- In child graph <Dictionary> -->
<Entry name="inputDate" type="date" input="true" output="false"/>
<Entry name="recordsInserted" type="long" input="false" output="true" dictval.value="0"/>
```
Pass to child (inputMapping): `$out.2.inputDate = $in.0.runDate;`
Read from child (outputMapping): `dictionary.recordsInserted = $in.2.recordsInserted;`
**Parameters** = configure child (settings). **Dictionary** = pass/return data values.

---

## Error Handling Patterns
- **Try/Catch:** error port 1 → FAIL or handler (default behavior).
- **Try/Finally:** `redirectErrorOutput="true"` — both success/failure to port 0; distinguish via `$in.1.status`.
- **Ignore+continue:** `stopOnFail="false"` + `redirectErrorOutput="true"`.
- **Parallel errors:** all error ports → SIMPLE_GATHER → FAIL. First arrival aborts.

---

## Common Patterns

**Sequential:**
`GET_JOB_INPUT → EG(A) → EG(B) → SUCCESS` / `EG error → FAIL`

**Parallel + barrier:**
`GET_JOB_INPUT → SIMPLE_COPY → EG(A) ↘ BARRIER → EG(cleanup)`
`                            → EG(B) ↗`

**Parallel + error collection:**
```
SIMPLE_COPY → EJF(A) port 0 → COMBINE(incompleteTuples=true) → next
            → EJF(B) port 0 ↗
            → EJF(A) port 1 → SIMPLE_GATHER → FAIL
            → EJF(B) port 1 ↗
```
`COMBINE(incompleteTuples=true)`: if a branch fails and token exits via error port, COMBINE doesn't deadlock waiting for the missing tuple.

**Async parallel:**
`LIST_FILES → EG(async, executorsNumber=3) → MONITOR_GRAPH → SUCCESS`

**DB-driven for-loop:**
`DB_INPUT_TABLE → NORMALIZER(1→N tokens) → EG(synchronous, executorsNumber=3)`

**Lock file (mutual exclusion):**
```
Phase 0: CREATE_FILES(${LOCK}, stopOnFail=false)       ← stopOnFail=false: tolerates existing lock
...work phases...
Phase N: DELETE_FILES(${LOCK}) error port → TRASH      ← TRASH: tolerates missing lock
```
Check-before-proceed: `LIST_FILES(${LOCK}, stopOnFail=false)` — port 0 (found) → FAIL, port 1 (not found) → proceed.

**Pre/post logging:**
`DATA_GENERATOR → LOG_START(logger.grf) → RUN_WORKER` / `success → LOG_FINISH → SUCCESS` / `error → LOG_ERROR → FAIL`
Pass log data via dict port: `$out.2.logData = logData;` (map[string,string]).

---

## Production Notes (DWHExample)

**Token as state carrier:** Use a jobToken record with `map[string,long] jobStatistics`. Accumulate counts across steps on the token via inputMapping/outputMapping rather than using dict — simpler for multi-level jobflow chains.

**RUN_ID:** Always available via `getParamValue('RUN_ID')`.
- Unique temp dirs: `getParamValue("WORKING_DIR") + "/wd_${RUN_ID}"`
- Stats: `$out.0.jobStatistics['jobRunId'] = str2long(getParamValue('RUN_ID'));`

**Dictionary map workaround — CLO-8807 (critical bug):** Writing to a `map` dict entry populated from upstream causes random crashes. Always copy first:
```ctl
dictionary.__jobStatistics = dictionary.jobStatistics;  // copy to local entry
// downstream: write to dictionary.__jobStatistics only
```
Declare two dict entries: `jobStatistics` (input=true) and `__jobStatistics` (output=true).

**executionLabel:** `$out.0.executionLabel = $in.0.fileName;` — shows per-iteration context in Server execution history. Set for every EXECUTE_GRAPH processing multiple files/dates.

**Multi-source file ops:** MOVE_FILES/COPY_FILES accept `;`-separated URLs:
`$out.0.sourceURL = dir + "/" + file1 + ";" + dir + "/" + file2;`
Wildcard: `$out.0.sourceURL = workingDir + "/*";`

---

## Validation Failures

| Problem | Fix |
|---|---|
| LOOP deadlock | Every path from output 1 returns to input 1; no token duplication/loss |
| BARRIER deadlock | All branches deliver exactly one token |
| COMBINE deadlock on branch failure | `incompleteTuples="true"` |
| `nature="jobflow"` missing | Add to `<Graph>` |
| Child dict entry inaccessible | Declare `<Entry input="true">` or `<Entry output="true">` in child |
| checkConfig fails on dynamic jobURL | `skipCheckConfig="true"` on Node |
| Async child killed when parent ends | `daemon="true"` on EXECUTE_GRAPH, or add MONITOR_GRAPH |
| map dict crashes randomly | CLO-8807: copy map entry to local before writing |
| Error port unconnected + stopOnFail=true | Connect to FAIL/TOKEN_GATHER or set `stopOnFail="false"` |

---

## Checklist
- `nature="jobflow"` on `<Graph>`
- Dict entries: `input`/`output` flags correct in all child graphs
- Error ports connected or `stopOnFail="false"` explicit on every EXECUTE_*
- Async: MONITOR_GRAPH tracks run IDs; `daemon="true"` if child must outlive parent
- LOOP: every token from output 1 returns to input 1; no duplication/loss
- BARRIER: all branches deliver exactly one token
- COMBINE with parallel branches: `incompleteTuples="true"`
- outputMapping: `$out.0.* = $in.0.*;` before overwriting (preserve pass-through fields)
- Dynamic jobURL: `skipCheckConfig="true"` on Node
- Lock files: CREATE_FILES `stopOnFail="false"`; DELETE_FILES error → TRASH
- map dict entries: copy before writing (CLO-8807)
- `executionLabel` set in inputMapping for per-iteration Server visibility
- `executorsNumber` set when bounded parallel execution needed
- `max_running_concurrently` in `<ExecutionConfig>` if concurrent instances must be limited
- Temp dirs: `WORKING_DIR + "/wd_${RUN_ID}"` for uniqueness across concurrent runs
- `executionType` explicit on every EXECUTE_GRAPH/EXECUTE_JOBFLOW
- `timeout` set for scripts and long-running graphs that could hang
