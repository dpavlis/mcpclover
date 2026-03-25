#!/usr/bin/env python3
"""SOAP/REST client for CloverDX server operations."""

import base64
from datetime import datetime
import fnmatch
import json
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
        self._debug_read_url = f"{scheme}://{host}:{port}/clover/data-service/debugRead"
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

    def get_graph_tracking(self, run_id: str, detailed: bool = True) -> Dict[str, Any]:
        resp = self._call("GetGraphTracking", runID=int(run_id))
        raw = zeep_helpers.serialize_object(resp, target_cls=dict)

        hierarchy = raw.get("out") or raw
        if isinstance(hierarchy, dict):
            root = hierarchy.get("rootTracking") or hierarchy.get("graphTracking") or hierarchy
        else:
            root = raw

        def _as_list(value):
            """Normalize SOAP payloads where collections may appear as object or list."""
            if value is None:
                return []
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                # Common wrappers from zeep/object serialization.
                for key in (
                    "phaseTracking", "nodeTracking", "portTracking",
                    "phases", "nodes", "ports",
                    "item", "items", "_value_1", "out",
                ):
                    if key in value and value[key] is not value:
                        nested = _as_list(value.get(key))
                        if nested:
                            return nested
                return [value]
            return []

        def _seconds(val):
            if val is None:
                return None
            try:
                return round(int(val) / 1000.0, 3)
            except Exception:
                try:
                    return round(float(val) / 1000.0, 3)
                except Exception:
                    return None

        def _to_int(val, default: int = 0) -> int:
            if val is None:
                return default
            try:
                return int(val)
            except Exception:
                return default

        def _unwrap_container(value: Any, key: str) -> Any:
            """Unwrap dict containers like {'phaseTracking': {...}}."""
            if isinstance(value, dict) and isinstance(value.get(key), dict):
                return value.get(key)
            return value

        def build_tracking(t):
            if not isinstance(t, dict):
                return None

            status = t.get("finalStatus", "")
            run_id_ = str(t.get("runId") or t.get("runID") or run_id)

            result: Dict[str, Any] = {
                "run_id": run_id_,
                "status": status,
                "exec_seconds": _seconds(t.get("execTime")),
                "phases": [],
                "summary": {
                    "phase_count": 0,
                    "node_count": 0,
                    "port_count": 0,
                    "total_records": 0,
                    "total_bytes": 0,
                },
            }

            phases = _as_list(t.get("phaseTracking") or t.get("phases") or t.get("_value_1"))
            for phase_raw in phases:
                phase = _unwrap_container(phase_raw, "phaseTracking")
                if not isinstance(phase, dict):
                    continue
                phase_entry: Dict[str, Any] = {
                    "phase_number": phase.get("phaseNumber"),
                    "exec_seconds": _seconds(phase.get("execTime")),
                    "nodes": [],
                }

                nodes = _as_list(phase.get("nodeTracking") or phase.get("nodes") or phase.get("_value_1"))
                for node_raw in nodes:
                    node = _unwrap_container(node_raw, "nodeTracking")
                    if not isinstance(node, dict):
                        continue
                    node_entry: Dict[str, Any] = {
                        "node_id": node.get("nodeId"),
                        "node_name": node.get("nodeName") or node.get("nodeId"),
                        "node_type": node.get("nodeType"),
                        "result": node.get("result"),
                        "cpu_seconds": _seconds(node.get("totalCpuTime")),
                        "ports": [],
                    }

                    ports = _as_list(node.get("portTracking") or node.get("ports") or node.get("_value_1"))
                    for port_raw in ports:
                        port = _unwrap_container(port_raw, "portTracking")
                        if not isinstance(port, dict):
                            continue
                        records = port.get("totalRecords")
                        if records is None:
                            records = port.get("recordFlow", 0)
                        bytes_value = port.get("totalBytes")
                        if bytes_value is None:
                            bytes_value = port.get("byteFlow", 0)
                        node_entry["ports"].append(
                            {
                                "port_type": port.get("portType"),
                                "index": port.get("index"),
                                "records": _to_int(records, 0),
                                "bytes": _to_int(bytes_value, 0),
                            }
                        )

                        result["summary"]["port_count"] += 1
                        result["summary"]["total_records"] += _to_int(records, 0)
                        result["summary"]["total_bytes"] += _to_int(bytes_value, 0)

                    phase_entry["nodes"].append(node_entry)
                    result["summary"]["node_count"] += 1

                result["phases"].append(phase_entry)
                result["summary"]["phase_count"] += 1

            return result

        parsed = build_tracking(root)
        if parsed is not None:
            if not detailed:
                return {
                    "run_id": parsed.get("run_id"),
                    "status": parsed.get("status"),
                    "exec_seconds": parsed.get("exec_seconds"),
                    "summary": parsed.get("summary", {}),
                }
            return parsed

        fallback = {
            "run_id": str(run_id),
            "status": "UNKNOWN",
            "exec_seconds": None,
            "phases": [],
            "summary": {
                "phase_count": 0,
                "node_count": 0,
                "port_count": 0,
                "total_records": 0,
                "total_bytes": 0,
            },
            "warning": "No phase/node metrics found in a recognized tracking payload shape.",
            "raw_top_level_keys": sorted(raw.keys()) if isinstance(raw, dict) else [type(raw).__name__],
        }
        if not detailed:
            return {
                "run_id": fallback["run_id"],
                "status": fallback["status"],
                "exec_seconds": fallback["exec_seconds"],
                "summary": fallback["summary"],
                "warning": fallback["warning"],
                "raw_top_level_keys": fallback["raw_top_level_keys"],
            }
        return fallback

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

    def _rest_debug_read(self, run_id: str, edge_id: str, num_rec: int) -> Any:
        self._init_client()
        resp = self._client.transport.session.get(
            self._debug_read_url,
            params={"runID": str(run_id), "edgeID": str(edge_id), "numRec": int(num_rec)},
            headers={
                "X-Requested-By": "mcp",
                "Accept": "application/json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "json" in content_type:
            return resp.json()
        text = resp.text
        try:
            return json.loads(text)
        except Exception:
            return text

    @staticmethod
    def _clvi_record_count(data: bytes) -> Optional[int]:
        idx = data.find(b"CLVI")
        if idx < 0 or idx + 8 > len(data):
            return None
        count = struct.unpack_from(">I", data, idx + 4)[0]
        return count if count >= 0 else None

    def get_edge_debug_data(self,
                            run_id: str, edge_id: str,
                            record_count: int = 100) -> str:
        effective_record_count = max(1, int(record_count))
        parsed = self._rest_debug_read(run_id=run_id, edge_id=edge_id, num_rec=effective_record_count)
        if isinstance(parsed, str):
            return parsed

        response: Dict[str, Any]
        if isinstance(parsed, dict):
            response = dict(parsed)
        else:
            response = {"records": parsed}

        return json.dumps(response, indent=2, default=str)
