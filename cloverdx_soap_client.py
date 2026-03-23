#!/usr/bin/env python3
"""SOAP/REST client for CloverDX server operations."""

import base64
from datetime import datetime
import fnmatch
import logging
import os
import struct
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from zeep import Client
from zeep.transports import Transport
from zeep import helpers as zeep_helpers

POLL_TIMEOUT_S = 120
SERVER_WAIT_MS = 10_000

logger = logging.getLogger(__name__)


class CloverDXSoapClient:
    """
    Lazy-initialised SOAP client for CloverDX Server WebServices.
    Handles login, session token reuse, and automatic re-login on expiry.
    """

    _SESSION_TIMEOUT_S: int = int(os.getenv("CLOVERDX_SESSION_TIMEOUT", "1500"))

    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = False):
        parsed = urlparse(base_url.rstrip("/"))
        scheme = parsed.scheme or "http"
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 8083)
        self._wsdl_url = f"{scheme}://{host}:{port}/clover/webservice?wsdl"
        self._rest_base = f"{scheme}://{host}:{port}/clover/api/rest/v1"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._token: Optional[str] = None
        self._last_activity: float = 0.0
        self._client = None
        self._svc = None

    def _init_client(self):
        if self._client is not None:
            return
        session = requests.Session()
        session.auth = (self._username, self._password)
        session.verify = self._verify_ssl
        self._client = Client(wsdl=self._wsdl_url, transport=Transport(session=session))
        self._svc = self._client.service

    def login(self) -> str:
        self._init_client()
        ops = sorted(op for op in dir(self._svc) if not op.startswith("_"))
        login_op = next((op for op in ops if op.lower() == "login"), None)
        if login_op is None:
            logger.info("No Login operation in WSDL — using HTTP Basic Auth only.")
            self._token = ""
            return ""
        resp = getattr(self._svc, login_op)(
            username=self._username, password=self._password, locale="en"
        )
        token = (
            getattr(resp, "sessionToken", None)
            or getattr(resp, "return_", None)
            or getattr(resp, "token", None)
            or str(resp)
        )
        self._token = token
        self._last_activity = time.time()
        logger.info("Logged in to CloverDX server.")
        return token

    def logout(self):
        if self._token and self._svc:
            try:
                ops = sorted(op for op in dir(self._svc) if not op.startswith("_"))
                logout_op = next((op for op in ops if op.lower() == "logout"), None)
                if logout_op:
                    getattr(self._svc, logout_op)(sessionToken=self._token)
                    logger.info("Logged out from CloverDX server.")
            except Exception as e:
                logger.warning(f"Logout failed (ignoring): {e}")
        self._token = None

    def _ensure_logged_in(self):
        self._init_client()
        if self._token is None:
            self.login()
        elif time.time() - self._last_activity > self._SESSION_TIMEOUT_S:
            logger.info("Session idle >%ds — proactively re-logging in.", self._SESSION_TIMEOUT_S)
            self._token = None
            self.login()

    def _call(self, op_name: str, **kwargs):
        self._ensure_logged_in()
        if self._token:
            kwargs["sessionToken"] = self._token
        try:
            result = getattr(self._svc, op_name)(**kwargs)
            self._last_activity = time.time()
            return result
        except Exception as e:
            err_str = str(e).lower()
            if any(phrase in err_str for phrase in ("invalid session", "session expired", "not authenticated", "sessiontoken")):
                logger.info("Session expired — re-logging in.")
                self._token = None
                self.login()
                if self._token:
                    kwargs["sessionToken"] = self._token
                return getattr(self._svc, op_name)(**kwargs)
            raise

    @staticmethod
    def _decode_content(raw) -> str:
        content = getattr(raw, "fileContent", raw)
        if isinstance(content, (bytes, bytearray)):
            return content.decode("utf-8")
        if isinstance(content, str):
            try:
                return base64.b64decode(content).decode("utf-8")
            except Exception:
                return content
        raise RuntimeError(f"Unexpected file content type: {type(content)}")

    def download_file(self, sandbox: str, path: str) -> str:
        resp = self._call("DownloadFileContent", sandboxCode=sandbox, filePath=path)
        return self._decode_content(resp)

    def upload_file(self, sandbox: str, dir_path: str, filename: str, content: str):
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        full_path = f"{dir_path.rstrip('/')}/{filename}"
        try:
            self._call("UploadFileContent", sandboxCode=sandbox, filePath=full_path, content=content_b64)
        except Exception as e:
            err_str = str(e).lower()
            if "not found" in err_str or "does not exist" in err_str or "no such" in err_str:
                self._call("CreateSandboxFile", sandboxCode=sandbox, filePath=full_path)
                self._call("UploadFileContent", sandboxCode=sandbox, filePath=full_path, content=content_b64)
            else:
                raise

    def copy_file(self, source_sandbox: str, source_path: str, dest_sandbox: str, dest_path: str):
        if not os.path.basename(dest_path):
            raise ValueError(f"Destination path must include a filename: '{dest_path}'")
        self._call(
            "CopySandboxFile",
            sourceSandboxCode=source_sandbox,
            sourceFilePath=source_path,
            targetSandboxCode=dest_sandbox,
            targetFilePath=dest_path,
        )

    def rename_file(self, sandbox: str, path: str, new_name: str):
        if not new_name or os.sep in new_name or "/" in new_name:
            raise ValueError(f"new_name must be a plain filename with no path separators: '{new_name}'")
        self._call("RenameSandboxFile", sandboxCode=sandbox, path=path, newName=new_name)

    @staticmethod
    def _ws_properties_to_dict(raw: Any) -> Dict[str, str]:
        serialized = zeep_helpers.serialize_object(raw, target_cls=dict)
        result: Dict[str, str] = {}

        def _collect(obj: Any):
            if isinstance(obj, dict):
                key = obj.get("key")
                if key is not None:
                    value = obj.get("value")
                    result[str(key)] = "" if value is None else str(value)
                for value in obj.values():
                    _collect(value)
            elif isinstance(obj, list):
                for item in obj:
                    _collect(item)

        _collect(serialized)
        return result

    def get_defaults(self) -> Dict[str, str]:
        resp = self._call("GetDefaults")
        return self._ws_properties_to_dict(resp)

    def get_system_properties(self) -> Dict[str, str]:
        resp = self._call("GetSystemProperties")
        return self._ws_properties_to_dict(resp)

    def list_files(self, sandbox: str, path: str, folder_only: bool = False) -> List[Dict]:
        resp = self._call("ListFiles", sandboxCode=sandbox, folderPath=path)
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)
        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            for val in raw.values():
                if isinstance(val, list):
                    items = val
                    break
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = {k: v for k, v in item.items() if v is not None}
            if folder_only and not entry.get("isFolder", False):
                continue
            result.append(entry)
        return result

    def find_files(self, sandbox: str, pattern: str, path: str = "") -> List[Dict]:
        matches: List[Dict] = []
        visited: set[str] = set()

        def _join(folder: str, name: str) -> str:
            if not folder:
                return name
            return f"{folder.rstrip('/')}/{name}".lstrip("/")

        def _walk(folder: str):
            normalized = folder.strip("/")
            if normalized in visited:
                return
            visited.add(normalized)

            for item in self.list_files(sandbox=sandbox, path=normalized, folder_only=False):
                if not isinstance(item, dict):
                    continue

                name = str(item.get("name") or item.get("fileName") or "")
                raw_path = str(item.get("path") or item.get("filePath") or "")
                is_folder = bool(item.get("isFolder") or item.get("folder"))
                relative_path = raw_path.lstrip("/") if raw_path else _join(normalized, name)

                if is_folder:
                    _walk(relative_path or _join(normalized, name))
                    continue

                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(relative_path, pattern):
                    entry = {k: v for k, v in item.items() if v is not None}
                    if "path" not in entry and relative_path:
                        entry["path"] = relative_path
                    matches.append(entry)

        _walk(path)
        return matches

    def delete_file(self, sandbox: str, path: str):
        self._call("DeleteFile", sandboxCode=sandbox, filePath=path)

    def get_sandboxes(self) -> List[Dict]:
        resp = self._call("GetSandboxes")
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)
        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            for val in raw.values():
                if isinstance(val, list):
                    items = val
                    break
                if isinstance(val, dict):
                    items = [val]
                    break
        result = []
        for item in items:
            if isinstance(item, dict):
                result.append({
                    "code": item.get("code", ""),
                    "name": item.get("name", ""),
                    "description": item.get("description", ""),
                })
        return result

    def start_check_config(self, sandbox: str, graph_path: str) -> int:
        resp = self._call("StartCheckConfigOperation", sandboxCode=sandbox, graphPath=graph_path)
        return resp if isinstance(resp, int) else int(getattr(resp, "return_", getattr(resp, "handle", resp)))

    def poll_check_config(self, handle: int, timeout_s: int = POLL_TIMEOUT_S):
        deadline = time.time() + timeout_s
        while True:
            resp = self._call("GetCheckConfigOperationResult", handle=handle, timeout=SERVER_WAIT_MS)
            if getattr(resp, "aborted", False):
                return resp
            if not getattr(resp, "timeoutExpired", True):
                return resp
            if time.time() > deadline:
                try:
                    self._call("AbortCheckConfigOperation", handle=handle)
                except Exception:
                    pass
                raise TimeoutError(f"checkConfig timed out after {timeout_s}s")

    def extract_problems(self, poll_result) -> List[Dict]:
        result_dict = zeep_helpers.serialize_object(poll_result, target_cls=dict)
        problems = []
        for item in (result_dict.get("_value_1") or []):
            p = item.get("problems") if isinstance(item, dict) else None
            if not p:
                continue
            for entry in (p if isinstance(p, list) else [p]):
                if isinstance(entry, dict) and entry:
                    problems.append({
                        "severity": entry.get("severity", ""),
                        "priority": entry.get("priority", ""),
                        "elementID": entry.get("elementID", ""),
                        "attributeName": entry.get("attributeName", ""),
                        "message": entry.get("message", ""),
                    })
        return problems

    def execute_graph(self, sandbox: str, graph_path: str,
                      params: Optional[Dict[str, str]] = None,
                      debug: bool = False) -> str:
        kwargs: Dict[str, Any] = dict(sandboxCode=sandbox, graphPath=graph_path, debugEnabled=debug)
        if params:
            kwargs["graphProperties"] = {
                "properties": [{"key": k, "value": v} for k, v in params.items()]
            }
        resp = self._call("ExecuteGraph", **kwargs)
        run_id = (
            getattr(resp, "runID", None)
            or getattr(resp, "runId", None)
            or getattr(resp, "return_", None)
            or str(resp)
        )
        return str(run_id)

    def poll_execution_status(self, run_id: str, timeout_s: int = POLL_TIMEOUT_S) -> Dict:
        start = time.time()
        resp = self._call("GetGraphExecutionStatus", runID=int(run_id), waitForStatus="FINISHED_OK", waitTimeout=timeout_s * 1000)
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)
        status = str(raw.get("status") or raw.get("runStatus") or "UNKNOWN").upper()
        return {"run_id": run_id, "status": status, "elapsed_seconds": round(time.time() - start, 1)}

    @staticmethod
    def _to_unix_seconds(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except Exception:
                return None
        return None

    def get_graph_run_status(self, run_id: str) -> Dict[str, Any]:
        try:
            resp = self._call("GetJobExecutionStatus", runID=int(run_id))
        except Exception:
            resp = self._call("GetGraphExecutionStatus", runID=int(run_id))

        raw = zeep_helpers.serialize_object(resp, target_cls=dict)
        status_obj = raw.get("out") if isinstance(raw, dict) and isinstance(raw.get("out"), dict) else raw
        if not isinstance(status_obj, dict):
            raise RuntimeError(f"Unexpected status response for run {run_id}: {status_obj!r}")

        raw_status = str(status_obj.get("status") or "UNKNOWN").upper()
        status_map = {
            "RUNNING": "RUNNING",
            "WAITING": "WAITING",
            "FINISHED_OK": "SUCCESS",
            "ERROR": "FAILED",
            "ABORTED": "ABORTED",
        }
        normalized_status = status_map.get(raw_status, raw_status)

        start_ts = self._to_unix_seconds(status_obj.get("startTime") or status_obj.get("submitTime"))
        stop_ts = self._to_unix_seconds(status_obj.get("stopTime"))
        now_ts = time.time()
        elapsed_seconds: Optional[float] = None
        if start_ts is not None:
            end_ts = stop_ts if stop_ts is not None else now_ts
            elapsed_seconds = round(max(0.0, end_ts - start_ts), 1)

        result: Dict[str, Any] = {
            "run_id": str(status_obj.get("runId") or run_id),
            "status": normalized_status,
            "raw_status": raw_status,
            "start_time": status_obj.get("startTime"),
            "stop_time": status_obj.get("stopTime"),
            "elapsed_seconds": elapsed_seconds,
            "error_message": status_obj.get("errMessage") or None,
            "error_node_id": status_obj.get("errNodeId") or None,
            "error_node_type": status_obj.get("errNodeType") or None,
            "sandbox_id": status_obj.get("sandboxId") or None,
            "graph_id": status_obj.get("graphId") or None,
        }

        if normalized_status == "RUNNING":
            try:
                tracking_resp = self._call("GetGraphTracking", runID=int(run_id))
                tracking_raw = zeep_helpers.serialize_object(tracking_resp, target_cls=dict)
                hierarchy = tracking_raw.get("out") if isinstance(tracking_raw, dict) else tracking_raw
                root = hierarchy.get("rootTracking") if isinstance(hierarchy, dict) else None
                phases = root.get("phaseTracking") if isinstance(root, dict) else None
                phase_numbers: List[int] = []
                for phase in (phases or []):
                    if not isinstance(phase, dict):
                        continue
                    number = phase.get("phaseNumber")
                    if number is None:
                        continue
                    try:
                        phase_numbers.append(int(str(number)))
                    except Exception:
                        continue
                result["current_phase_number"] = max(phase_numbers) if phase_numbers else None
            except Exception:
                result["current_phase_number"] = None

        return result

    def _rest_get(self, path: str, params: Optional[Dict] = None) -> Any:
        self._init_client()
        url = self._rest_base + path
        resp = self._client.transport.session.get(
            url,
            params=params,
            headers={"X-Requested-By": "mcp"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def list_graph_runs(
        self,
        sandbox: Optional[str] = None,
        job_file: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 25,
        start_index: int = 0,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"pageSize": limit, "startIndex": start_index}
        if sandbox:
            params["sandboxCode"] = sandbox
        if job_file:
            params["jobFile"] = job_file
        if status:
            params["status"] = status

        data = self._rest_get("/executions", params)
        total = data.get("@totalItems", 0)
        members = data.get("members") or []

        runs = []
        for item in members:
            run: Dict[str, Any] = {
                "run_id": str(item.get("runId", "")),
                "sandbox": item.get("sandboxCode", ""),
                "job_file": item.get("jobFile", ""),
                "job_type": item.get("jobType", ""),
                "status": item.get("status", ""),
                "submit_time": item.get("submitTime"),
                "start_time": item.get("startTime"),
                "stop_time": item.get("stopTime"),
                "duration_ms": item.get("duration"),
                "duration_string": item.get("durationString", ""),
                "username": item.get("username", ""),
            }
            err = item.get("jobError")
            if err:
                run["error"] = {
                    "component_id": err.get("componentId", ""),
                    "message": err.get("message", ""),
                }
            runs.append(run)

        return {"total": total, "returned": len(runs), "runs": runs}

    def get_execution_log(self, run_id: str) -> str:
        resp = self._call("GetGraphExecutionLog", runID=int(run_id), offset=0)
        raw = getattr(resp, "log", None) or getattr(resp, "return_", None) or resp
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                return base64.b64decode(raw).decode("utf-8")
            except Exception:
                return raw
        return str(raw)

    def get_graph_tracking(self, run_id: str) -> str:
        resp = self._call("GetGraphTracking", runID=int(run_id))
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)

        lines = []
        hierarchy = raw.get("out") or raw
        if isinstance(hierarchy, dict):
            root = hierarchy.get("rootTracking") or hierarchy
        else:
            root = raw

        def _ms(val):
            if val is None:
                return ""
            try:
                return f"{int(val)/1000:.1f}s"
            except Exception:
                return str(val)

        def _fmt_bytes(val):
            if not val:
                return "0 B"
            try:
                v = int(val)
                if v >= 1_048_576:
                    return f"{v/1_048_576:.1f} MB"
                if v >= 1024:
                    return f"{v/1024:.1f} KB"
                return f"{v} B"
            except Exception:
                return str(val)

        def render_tracking(t, indent=0):
            if not isinstance(t, dict):
                return
            pad = "  " * indent
            status = t.get("finalStatus", "")
            exec_ms = t.get("execTime")
            run_id_ = t.get("runId") or t.get("runID") or ""
            if run_id_:
                lines.append(f"Graph run {run_id_}  status={status}  exec={_ms(exec_ms)}")
            for phase in (t.get("phaseTracking") or []):
                if not isinstance(phase, dict):
                    continue
                pn = phase.get("phaseNumber", "?")
                pet = phase.get("execTime")
                lines.append(f"{pad}  Phase {pn}  ({_ms(pet)})")
                for node in (phase.get("nodeTracking") or []):
                    if not isinstance(node, dict):
                        continue
                    nid = node.get("nodeId", "")
                    nname = node.get("nodeName", "")
                    ntype = node.get("nodeType", "")
                    nres = node.get("result", "")
                    ncpu = node.get("totalCpuTime")
                    label = nname or nid
                    lines.append(f"{pad}    [{ntype}] {label}  cpu={_ms(ncpu)}  result={nres}")
                    for port in (node.get("portTracking") or []):
                        if not isinstance(port, dict):
                            continue
                        ptype = port.get("portType", "")
                        pidx = port.get("index", "?")
                        recs = port.get("totalRecords") or port.get("recordFlow", 0)
                        byts = port.get("totalBytes") or port.get("byteFlow", 0)
                        lines.append(f"{pad}      {ptype}[{pidx}]: {recs} records  {_fmt_bytes(byts)}")

        render_tracking(root)
        return "\n".join(lines) if lines else str(raw)

    def get_edge_debug_info(self, sandbox: str, graph_path: str,
                            run_id: str, edge_id: str,
                            retries: int = 3, retry_delay: float = 2.0) -> List[Dict]:
        for attempt in range(retries):
            resp = self._call("GetEdgeDebugInfoList", sandboxCode=sandbox, graphPath=graph_path, runId=int(run_id), edgeId=edge_id)
            raw = zeep_helpers.serialize_object(resp, target_cls=dict)
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                items = raw.get("items") or []
                if isinstance(items, dict):
                    items = [items]
            else:
                items = []
            result = [i for i in items if isinstance(i, dict)]
            if result:
                return result
            if attempt < retries - 1:
                time.sleep(retry_delay)
        return []

    def get_edge_debug_metadata(self, sandbox: str, graph_path: str, run_id: str, edge_id: str) -> str:
        info_list = self.get_edge_debug_info(sandbox, graph_path, run_id, edge_id)
        if not info_list:
            return f"No edge debug info found for edge '{edge_id}' in run {run_id}."
        resp = self._call("GetEdgeDebugMetadata", edgeDebugInfo=info_list[0])
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)
        if isinstance(raw, str):
            return raw
        return raw.get("metadata") or str(raw)

    @staticmethod
    def _clvi_record_count(data: bytes) -> Optional[int]:
        idx = data.find(b"CLVI")
        if idx < 0 or idx + 8 > len(data):
            return None
        count = struct.unpack_from(">I", data, idx + 4)[0]
        return count if count >= 0 else None

    def get_edge_debug_data(self, sandbox: str, graph_path: str,
                            run_id: str, edge_id: str,
                            start_record: int = 0,
                            record_count: int = 100,
                            filter_expression: str = "",
                            field_selection: Optional[List[str]] = None) -> str:
        expr = filter_expression.strip() if filter_expression else ""
        if not expr:
            expr = "//#CTL2\ntrue"
        elif not expr.startswith("//#CTL2"):
            expr = "//#CTL2\n" + expr
        resp = self._call(
            "GetEdgeDebugData",
            sandboxCode=sandbox,
            graphPath=graph_path,
            writerRunId=int(run_id),
            readerRunId=int(run_id),
            edgeID=edge_id,
            startRecord=start_record,
            recordCount=record_count,
            filterExpression=expr,
            fieldSelection=field_selection or [],
        )
        raw = getattr(resp, "out", None) or getattr(resp, "return_", None) or resp

        if isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
        elif isinstance(raw, str):
            try:
                data = base64.b64decode(raw)
            except Exception:
                return raw
        else:
            return str(raw)

        n_returned = self._clvi_record_count(data)
        count_info = f"{n_returned:,} record(s) returned" if n_returned is not None else "record count unavailable"
        has_more = (n_returned is not None and n_returned >= record_count)
        more_info = (
            f" (there may be more — re-call with start_record={start_record + n_returned})"
            if has_more else " (all captured records returned)"
        )

        return (
            f"Edge debug data for '{edge_id}' (run {run_id}): {count_info}{more_info}.\n"
            f"Payload is CloverDX binary (CLVI format, {len(data):,} bytes) — "
            f"not human-readable directly. Use get_edge_debug_metadata to inspect the field schema."
        )
