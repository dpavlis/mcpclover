#!/usr/bin/env python3
"""
CloverDX SOAP Client Test
==========================
Exercises CloverDXSoapClient and GraphValidator from cloverdx_graph_mcp_server.py
against a live CloverDX server.

Known fixtures:
  sandbox : DWHExample
  graph   : GenerateData.grf  (somewhere inside DWHExample)

Usage
-----
  cd /path/to/mcpclover
  python test_soap_client.py

Exit code 0 = all tests passed.
Exit code 1 = one or more tests failed.

Config is loaded from .env (same variables as the MCP server):
  CLOVERDX_BASE_URL, CLOVERDX_USERNAME, CLOVERDX_PASSWORD, CLOVERDX_VERIFY_SSL
"""

import asyncio
import json
import os
import sys
import xml.etree.ElementTree as ET

from dotenv import load_dotenv

# Import classes from the MCP server (same directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cloverdx_graph_mcp_server as graph_server  # noqa: E402
from cloverdx_graph_mcp_server import CloverDXSoapClient, GraphValidator, _parse_graph_params, ComponentCatalog, _scan_comp_details  # noqa: E402

# ── Config ─────────────────────────────────────────────────────────────────────

TARGET_SANDBOX = "DWHExample"
TARGET_GRAPH   = "GenerateData.grf"
TOTAL_STEPS    = 24

# ── Output helpers ─────────────────────────────────────────────────────────────

def _hr():
    print("═" * 55)

def _header():
    _hr()
    print(f"  CloverDX SOAP Client Test  —  {TARGET_SANDBOX} sandbox")
    _hr()
    print()

def _step(n, title):
    print(f"[{n}/{TOTAL_STEPS}] {title} ...")

def _pass(detail=""):
    msg = f"  \u2713  PASS"
    if detail:
        msg += f"  {detail}"
    print(msg)

def _fail(detail):
    print(f"  \u2717  FAIL  {detail}")

def _skip(reason):
    print(f"  \u25ba  SKIP  {reason}")

def _info(detail):
    print(f"       {detail}")

# ── Graph file finder ──────────────────────────────────────────────────────────


def _find_graph(client: CloverDXSoapClient, sandbox: str, graph_name: str):
    """
    Recursively search sandbox for graph_name.
    Returns (full_path_string, searched_dirs) or (None, searched_dirs).
    """
    searched = []

    def _search(folder):
        label = folder if folder else "(root)"
        if label in searched:
            return None
        searched.append(label)
        try:
            items = client.list_files(sandbox, folder)
        except Exception:
            return None

        subfolders = []
        for item in (items or []):
            fname     = item.get("name") or item.get("fileName") or ""
            fpath     = item.get("path") or item.get("filePath") or ""
            is_folder = item.get("isFolder") or item.get("folder") or False

            if is_folder and fname:
                subfolders.append(fname if not folder else f"{folder}/{fname}")
            else:
                if fname == graph_name:
                    return (f"{folder}/{graph_name}").lstrip("/")
                if fpath.endswith(graph_name):
                    return fpath.lstrip("/")

        # Recurse into subdirectories
        for sub in subfolders:
            result = _search(sub)
            if result:
                return result
        return None

    result = _search("")
    return result, searched


def _find_first_edge_id(xml_text: str):
    """Return the id attribute of the first <Edge> element in the graph XML, or None."""
    try:
        root = ET.fromstring(xml_text)
        for phase in root.findall("Phase"):
            for edge in phase.findall("Edge"):
                eid = edge.get("id")
                if eid:
                    return eid
    except Exception:
        pass
    return None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    load_dotenv()

    base_url   = os.getenv("CLOVERDX_BASE_URL")
    username   = os.getenv("CLOVERDX_USERNAME")
    password   = os.getenv("CLOVERDX_PASSWORD")
    verify_ssl = os.getenv("CLOVERDX_VERIFY_SSL", "false").lower() == "true"

    if not all([base_url, username, password]):
        print("ERROR: Missing env vars. Copy .env.example to .env and fill in credentials.")
        sys.exit(1)

    _header()

    passed = 0
    failed = 0
    skipped = 0
    client = CloverDXSoapClient(str(base_url), str(username), str(password), verify_ssl)

    # Dependency flags (set to False when a required prior step failed)
    have_login    = False
    have_sandbox  = False
    graph_path    = None   # set in step 3
    graph_xml     = None   # set in step 4
    exec_params   = {}     # set in step 7 (params with defaults extracted from XML)
    run_id        = None   # set in step 7
    debug_run_id  = None   # set in step 11 (debug execution)

    # ── Step 1: Login ──────────────────────────────────────────────────────
    _step(1, "Connect + Login")
    try:
        token = client.login()
        short = (str(token)[:16] + "…") if len(str(token)) > 16 else str(token)
        _pass(f"token={short!r}")
        passed += 1
        have_login = True
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Step 2: List sandboxes ─────────────────────────────────────────────
    _step(2, f"List sandboxes (check {TARGET_SANDBOX} is present)")
    if not have_login:
        _skip("depends on step 1 (login failed)")
    else:
        try:
            sandboxes = client.get_sandboxes()
            codes = [s.get("code", "") for s in sandboxes]
            if TARGET_SANDBOX in codes:
                names = ", ".join(codes[:6]) + ("…" if len(codes) > 6 else "")
                _pass(f"{len(sandboxes)} sandbox(es): {names}")
                passed += 1
                have_sandbox = True
            else:
                _fail(f"{TARGET_SANDBOX!r} not found. Available: {codes}")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 3: Find graph file ────────────────────────────────────────────
    _step(3, f"Find {TARGET_GRAPH} inside {TARGET_SANDBOX}")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        try:
            result, searched = _find_graph(client, TARGET_SANDBOX, TARGET_GRAPH)
            if result:
                graph_path = result
                _pass(f"found at {graph_path!r}")
                passed += 1
            else:
                _fail(f"{TARGET_GRAPH!r} not found in dirs: {searched}")
                _info("Hint: check the sandbox structure in CloverDX Designer")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 4: Download graph ─────────────────────────────────────────────
    _step(4, f"Download graph file ({graph_path or '?'})")
    if graph_path is None:
        _skip("depends on step 3 (graph path unknown)")
    else:
        try:
            graph_xml = client.download_file(TARGET_SANDBOX, graph_path)
            if graph_xml and "<Graph" in graph_xml:
                _pass(f"{len(graph_xml):,} bytes")
                passed += 1
            elif graph_xml:
                _fail(f"Downloaded {len(graph_xml):,} bytes but <Graph not found in content")
                _info(f"First 200 chars: {graph_xml[:200]!r}")
                failed += 1
                graph_xml = None
            else:
                _fail("Empty response")
                failed += 1
                graph_xml = None
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 5: Local XML validation ──────────────────────────────────────
    _step(5, "Stage 1 — local XML + structure validation")
    if graph_xml is None:
        _skip("depends on step 4 (graph XML not available)")
    else:
        try:
            validator = GraphValidator(graph_xml)
            errors, warnings = validator.validate()
            if errors:
                _fail(f"{len(errors)} error(s)")
                for e in errors:
                    _info(f"ERROR: {e}")
                failed += 1
            else:
                _pass(f"0 errors, {len(warnings)} warning(s)")
                if warnings:
                    for w in warnings:
                        _info(f"WARNING: {w}")
                passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 6: Server checkConfig ─────────────────────────────────────────
    _step(6, "Stage 2 — server checkConfig")
    if graph_path is None:
        _skip("depends on step 3 (graph path unknown)")
    else:
        try:
            handle = client.start_check_config(TARGET_SANDBOX, graph_path)
            _info(f"started, handle={handle}")
            poll_result = client.poll_check_config(handle)
            problems    = client.extract_problems(poll_result)
            errors_cc   = [p for p in problems if str(p.get("severity", "")).upper() == "ERROR"]
            if errors_cc:
                _fail(f"{len(errors_cc)} ERROR-severity problem(s)")
                for p in errors_cc:
                    _info(f"[{p['severity']}] {p['elementID']}: {p['message']}")
                failed += 1
            else:
                _pass(f"0 errors" + (f", {len(problems)} warning(s)" if problems else ", 0 problems"))
                if problems:
                    for p in problems:
                        _info(f"[{p['severity']}] {p['elementID']}: {p['message']}")
                passed += 1
        except TimeoutError as e:
            _fail(f"TIMEOUT: {e}")
            failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 7: Execute graph ──────────────────────────────────────────────
    _step(7, "Execute graph")
    if graph_path is None:
        _skip("depends on step 3 (graph path unknown)")
    else:
        # Extract graph parameters from downloaded XML so required ones are passed
        missing_params: list = []
        if graph_xml:
            exec_params, missing_params = _parse_graph_params(graph_xml)
        if exec_params:
            _info(f"passing {len(exec_params)} param(s) with defaults: {', '.join(exec_params)}")
        if missing_params:
            _info(f"WARNING: {len(missing_params)} required param(s) have no default value: "
                  f"{', '.join(missing_params)} — execution may fail")
        try:
            run_id = client.execute_graph(TARGET_SANDBOX, graph_path,
                                          params=exec_params if exec_params else None)
            if run_id and str(run_id).strip() not in ("None", ""):
                _pass(f"run_id={run_id}")
                passed += 1
            else:
                _fail(f"Unexpected run_id: {run_id!r}")
                failed += 1
                run_id = None
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 8: Execution status ───────────────────────────────────────────
    _step(8, "Poll execution status")
    if run_id is None:
        _skip("depends on step 7 (no run_id)")
    else:
        try:
            result = client.poll_execution_status(run_id)
            status  = result.get("status", "UNKNOWN")
            elapsed = result.get("elapsed_seconds", "?")
            terminal_statuses = {"FINISHED_OK", "FINISHED", "ERROR", "ABORTED"}
            if status in terminal_statuses:
                note = "" if status in {"FINISHED_OK", "FINISHED"} else f"  (graph ended with {status} — check log)"
                _pass(f"status={status}  ({elapsed}s){note}")
                passed += 1
            else:
                _fail(f"status={status}  ({elapsed}s) — no terminal status received")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 9: Execution log ──────────────────────────────────────────────
    _step(9, "Get execution log")
    if run_id is None:
        _skip("depends on step 7 (no run_id)")
    else:
        try:
            log = client.get_execution_log(run_id)
            if log and len(log.strip()) > 0:
                _pass(f"{len(log):,} bytes")
                # Print first 3 lines as a preview
                for line in log.splitlines()[:3]:
                    _info(line)
                passed += 1
            else:
                _fail("Empty log returned")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 10: Graph tracking ────────────────────────────────────────────
    _step(10, "Get graph tracking (record/byte counts per component port)")
    if run_id is None:
        _skip("depends on step 7 (no run_id)")
    else:
        try:
            tracking = client.get_graph_tracking(run_id)
            if tracking and len(tracking.strip()) > 0:
                lines = tracking.splitlines()
                _pass(f"{len(lines)} line(s)")
                for line in lines[:12]:        # show first ~12 lines (1 run + phases + nodes)
                    _info(line)
                passed += 1
            else:
                _fail("Empty tracking response")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 11: Execute graph with debug=True ─────────────────────────────
    _step(11, "Execute graph with debug=True (enables edge data capture)")
    if graph_path is None:
        _skip("depends on step 3 (graph path unknown)")
    else:
        if exec_params:
            _info(f"passing {len(exec_params)} param(s) with defaults")
        try:
            debug_run_id = client.execute_graph(
                TARGET_SANDBOX, graph_path,
                params=exec_params if exec_params else None,
                debug=True,
            )
            if debug_run_id and str(debug_run_id).strip() not in ("None", ""):
                _pass(f"debug run_id={debug_run_id}")
                passed += 1
            else:
                _fail(f"Unexpected run_id: {debug_run_id!r}")
                failed += 1
                debug_run_id = None
        except Exception as e:
            _fail(str(e))
            failed += 1

    # Resolve an edge_id from the graph XML for steps 12-14
    edge_id = _find_first_edge_id(graph_xml) if graph_xml else None
    edge_debug_available = False

    # ── Step 12: Edge debug info ───────────────────────────────────────────
    _step(12, f"Get edge debug info  (edge_id={edge_id!r})")
    if debug_run_id is None:
        _skip("depends on step 11 (no debug run_id)")
    elif edge_id is None:
        _skip("no edge ID found in graph XML")
    else:
        try:
            info_list = client.get_edge_debug_info(
                TARGET_SANDBOX, graph_path, debug_run_id, edge_id
            )
            if info_list:
                _pass(f"{len(info_list)} entry(ies)")
                for entry in info_list:
                    avail  = entry.get("available", "?")
                    writer = entry.get("writerNodeId", "?")
                    reader = entry.get("readerNodeId", "?")
                    _info(f"available={avail}  writerRunId={entry.get('writerRunId')}  readerRunId={entry.get('readerRunId')}")
                passed += 1
                edge_debug_available = True
            else:
                _fail(f"No edge debug info returned for edge_id={edge_id!r} run_id={debug_run_id}")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 13: Edge debug metadata ──────────────────────────────────────
    _step(13, f"Get edge debug metadata  (edge_id={edge_id!r})")
    if debug_run_id is None:
        _skip("depends on step 11 (no debug run_id)")
    elif edge_id is None:
        _skip("no edge ID found in graph XML")
    elif not edge_debug_available:
        _skip("depends on step 12 (no edge debug data available on this server)")
        skipped += 1
    else:
        try:
            meta_xml = client.get_edge_debug_metadata(
                TARGET_SANDBOX, graph_path, debug_run_id, edge_id
            )
            if meta_xml and len(meta_xml.strip()) > 0:
                _pass(f"{len(meta_xml):,} bytes")
                for line in meta_xml.splitlines()[:5]:
                    _info(line)
                passed += 1
            else:
                _fail("Empty metadata response")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 14: Edge debug data ───────────────────────────────────────────
    _step(14, f"Get edge debug data  (edge_id={edge_id!r}, first 50 records)")
    if debug_run_id is None:
        _skip("depends on step 11 (no debug run_id)")
    elif edge_id is None:
        _skip("no edge ID found in graph XML")
    elif not edge_debug_available:
        _skip("depends on step 12 (no edge debug data available on this server)")
        skipped += 1
    else:
        try:
            summary = client.get_edge_debug_data(
                sandbox=TARGET_SANDBOX,
                graph_path=graph_path,
                run_id=debug_run_id,
                edge_id=edge_id,
                start_record=0,
                record_count=50,
            )
            if summary and len(summary.strip()) > 0:
                _pass(summary.splitlines()[0])
                for line in summary.splitlines()[1:]:
                    _info(line)
                passed += 1
            else:
                _fail("Empty response")
                failed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 15: get_component_info for TRASH ──────────────────────────────────
    _step(15, "get_component_info — search for 'TRASH'")
    try:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        catalog = ComponentCatalog(os.path.join(_script_dir, "resources", "components.json"))
        catalog.load()
        results = catalog.search("TRASH")
        if results:
            comp = results[0]
            formatted = ComponentCatalog.format_component(comp)
            _pass(f"found: {comp.get('type', '')} — {comp.get('name', '')}")
            for line in formatted.splitlines():
                _info(line)
            passed += 1
        else:
            _fail("No component found matching 'TRASH'")
            failed += 1
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Step 16: get_component_info for DB_INPUT_TABLE ────────────────────────
    _step(16, "get_component_info — search for 'DB_INPUT_TABLE'")
    try:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        catalog16 = ComponentCatalog(os.path.join(_script_dir, "resources", "components.json"))
        catalog16.load()
        results16 = catalog16.search("DB_INPUT_TABLE")
        if results16:
            comp16 = results16[0]
            formatted16 = ComponentCatalog.format_component(comp16)
            _pass(f"found: {comp16.get('type', '')} — {comp16.get('name', '')}")
            for line in formatted16.splitlines():
                _info(line)
            passed += 1
        else:
            _fail("No component found matching 'DB_INPUT_TABLE'")
            failed += 1
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Step 17: get_component_details for VALIDATOR ───────────────────────────
    _step(17, "get_component_details — VALIDATOR")
    try:
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        comp_details_map = _scan_comp_details(os.path.join(_script_dir, "comp_details"))
        if not comp_details_map:
            _fail("No comp_details/ directory or no .md files found")
            failed += 1
        elif "VALIDATOR" not in comp_details_map:
            available = ", ".join(sorted(comp_details_map.keys()))
            _fail(f"VALIDATOR not in comp_details. Available: {available}")
            failed += 1
        else:
            with open(comp_details_map["VALIDATOR"], encoding="utf-8") as f:
                content = f.read()
            if content and len(content.strip()) > 0:
                _pass(f"{len(content):,} bytes from {comp_details_map['VALIDATOR']}")
                for line in content.splitlines()[:4]:
                    _info(line)
                passed += 1
            else:
                _fail("VALIDATOR.md is empty")
                failed += 1
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Step 18: patch_file dry-run + apply ───────────────────────────────────
    _step(18, "patch_file — dry-run and apply on temp sandbox file")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        temp_path = "copilot_patch_file_test.txt"
        temp_content = "alpha\ntarget=old\nomega\n"
        patch_args = {
            "sandbox": TARGET_SANDBOX,
            "path": temp_path,
            "patches": [
                {
                    "anchor": "target=old",
                    "from_offset": 0,
                    "to_offset": 0,
                    "new_content": "target=new",
                }
            ],
        }
        try:
            client.upload_file(TARGET_SANDBOX, "", temp_path, temp_content)
            graph_server.soap_client = client

            dry_run_result = asyncio.run(graph_server.tool_patch_file({**patch_args, "dry_run": True}))
            dry_run_text = dry_run_result[0].text if dry_run_result else ""
            dry_run_json = json.loads(dry_run_text)
            if dry_run_json.get("status") != "dry_run":
                raise RuntimeError(f"unexpected dry_run status: {dry_run_json}")
            if dry_run_json.get("patches_applied") != 1:
                raise RuntimeError(f"unexpected dry_run patch count: {dry_run_json}")

            apply_result = asyncio.run(graph_server.tool_patch_file(patch_args))
            apply_text = apply_result[0].text if apply_result else ""
            apply_json = json.loads(apply_text)
            if apply_json.get("status") != "ok":
                raise RuntimeError(f"unexpected apply status: {apply_json}")

            patched = client.download_file(TARGET_SANDBOX, temp_path)
            if "target=new" not in patched or "target=old" in patched:
                raise RuntimeError(f"patched content mismatch: {patched!r}")

            _pass("dry_run preview and file patch succeeded")
            _info(f"dry_run anchor_line={dry_run_json['preview'][0]['anchor_line']}  lines_after={apply_json['lines_after']}")
            passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1
        finally:
            try:
                client.delete_file(TARGET_SANDBOX, temp_path)
            except Exception:
                pass

    # ── Step 19: rename_file ───────────────────────────────────────────────
    _step(19, "rename_file — rename a temp file then clean up")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        rename_src = "copilot_rename_test_src.txt"
        rename_dst = "copilot_rename_test_dst.txt"
        try:
            client.upload_file(TARGET_SANDBOX, "", rename_src, "rename test\n")
            result = asyncio.run(graph_server.tool_rename_file({
                "sandbox": TARGET_SANDBOX,
                "path": rename_src,
                "new_name": rename_dst,
            }))
            text = result[0].text if result else ""
            if text.startswith("ERROR:"):
                raise RuntimeError(text)
            # confirm old name is gone and new name exists
            content = client.download_file(TARGET_SANDBOX, rename_dst)
            if "rename test" not in content:
                raise RuntimeError(f"renamed file content mismatch: {content!r}")
            _pass(text)
            passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1
        finally:
            for p in (rename_src, rename_dst):
                try:
                    client.delete_file(TARGET_SANDBOX, p)
                except Exception:
                    pass

    # ── Step 20: get_workflow_guide variants ──────────────────────────────
    _step(20, "get_workflow_guide — default + task variants")
    try:
        default_res = asyncio.run(graph_server.tool_get_workflow_guide({}))
        create_res = asyncio.run(graph_server.tool_get_workflow_guide({"task": "create_graph"}))
        edit_res = asyncio.run(graph_server.tool_get_workflow_guide({"task": "edit_graph"}))
        run_res = asyncio.run(graph_server.tool_get_workflow_guide({"task": "validate_and_run"}))

        default_txt = default_res[0].text if default_res else ""
        create_txt = create_res[0].text if create_res else ""
        edit_txt = edit_res[0].text if edit_res else ""
        run_txt = run_res[0].text if run_res else ""

        if not default_txt.strip() or not create_txt.strip() or not edit_txt.strip() or not run_txt.strip():
            raise RuntimeError("one or more workflow guides returned empty content")
        if default_txt != create_txt:
            raise RuntimeError("default workflow guide is not the same as task='create_graph'")

        _pass("default/create_graph/edit_graph/validate_and_run returned guide content")
        _info(f"create_graph bytes={len(create_txt):,}")
        _info(f"edit_graph bytes={len(edit_txt):,}")
        _info(f"validate_and_run bytes={len(run_txt):,}")
        passed += 1
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Step 21: list_linked_assets ───────────────────────────────────────────────
    _step(21, "list_linked_assets — all + filtered asset type")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        try:
            graph_server.soap_client = client

            all_res = asyncio.run(graph_server.tool_list_linked_assets({
                "sandbox": TARGET_SANDBOX,
                "asset_type": "all",
            }))
            all_text = all_res[0].text if all_res else ""
            all_json = json.loads(all_text)

            if all_json.get("sandbox") != TARGET_SANDBOX:
                raise RuntimeError(f"unexpected sandbox in 'all' result: {all_json.get('sandbox')!r}")
            if all_json.get("asset_type") != "all":
                raise RuntimeError(f"unexpected asset_type in 'all' result: {all_json.get('asset_type')!r}")
            assets_obj = all_json.get("assets")
            if not isinstance(assets_obj, dict):
                raise RuntimeError(f"'all' result must contain assets object by type: {all_json}")

            expected_types = {"metadata", "connection", "lookup", "ctl", "sequence", "parameters"}
            missing_types = sorted(expected_types - set(assets_obj.keys()))
            if missing_types:
                raise RuntimeError(f"missing asset categories in 'all' result: {missing_types}")

            metadata_res = asyncio.run(graph_server.tool_list_linked_assets({
                "sandbox": TARGET_SANDBOX,
                "asset_type": "metadata",
            }))
            metadata_text = metadata_res[0].text if metadata_res else ""
            metadata_json = json.loads(metadata_text)

            if metadata_json.get("asset_type") != "metadata":
                raise RuntimeError(f"unexpected asset_type in filtered result: {metadata_json.get('asset_type')!r}")
            metadata_assets = metadata_json.get("assets")
            if not isinstance(metadata_assets, list):
                raise RuntimeError(f"filtered result must contain assets list: {metadata_json}")
            if any(not str(path).lower().endswith(".fmt") for path in metadata_assets):
                raise RuntimeError("metadata filter returned non-.fmt files")

            _pass("tool returned categorized assets and respected metadata filter")
            _info(f"all count={all_json.get('count', 0)}")
            _info(f"metadata count={len(metadata_assets)}")
            passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 22: get_sandbox_parameters ───────────────────────────────────────────
    _step(22, "get_sandbox_parameters — print all resolved parameters")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        try:
            graph_server.soap_client = client
            result = asyncio.run(graph_server.tool_get_sandbox_parameters({
                "sandbox": TARGET_SANDBOX,
            }))
            text = result[0].text if result else ""
            if text.startswith("ERROR:"):
                raise RuntimeError(text)

            payload = json.loads(text)
            resolved = payload.get("resolved_parameters")
            if not isinstance(resolved, dict):
                raise RuntimeError(f"unexpected tool response shape: {payload}")

            parameter_sources = payload.get("parameter_sources")
            if parameter_sources is None:
                parameter_sources = {}
            if not isinstance(parameter_sources, dict):
                raise RuntimeError(f"unexpected parameter_sources shape: {parameter_sources!r}")

            applied_overrides = payload.get("applied_overrides")
            if applied_overrides is None:
                applied_overrides = {}
            if not isinstance(applied_overrides, dict):
                raise RuntimeError(f"unexpected applied_overrides shape: {applied_overrides!r}")

            _pass(f"resolved {len(resolved)} parameter(s)")
            _info(f"scope={payload.get('resolution_scope')}  workspace={payload.get('workspace_param_path')}")
            for key in sorted(resolved.keys()):
                source = parameter_sources.get(key, "unknown")
                _info(f"{key}={resolved[key]}  [source={source}]")

            _info(f"applied_overrides={len(applied_overrides)}")
            for key in sorted(applied_overrides.keys()):
                item = applied_overrides.get(key) or {}
                if not isinstance(item, dict):
                    _info(f"override {key}: {item}")
                    continue
                _info(
                    f"override {key}: {item.get('from')} -> {item.get('to')}  "
                    f"(source={item.get('source')})"
                )
            passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 23: list_graph_runs ───────────────────────────────────────────────
    _step(23, "list_graph_runs — list recent executions for DWHExample")
    if not have_sandbox:
        _skip("depends on step 2")
    else:
        try:
            result = client.list_graph_runs(
                sandbox=TARGET_SANDBOX,
                job_file="GenerateData.grf",
                limit=10,
            )
            runs = result.get("runs", [])
            total = result.get("total", 0)
            _pass(f"total={total}  returned={len(runs)}")
            for run in runs:
                err_info = ""
                if run.get("error"):
                    err_info = f"  error={run['error'].get('message', '')[:60]}"
                _info(
                    f"run_id={run['run_id']}  status={run['status']}"
                    f"  submit={run.get('submit_time', '')}"
                    f"  dur={run.get('duration_string', '')}"
                    + err_info
                )
            passed += 1
        except Exception as e:
            _fail(str(e))
            failed += 1

    # ── Step 24: Logout ──────────────────────────────────────────────────
    _step(24, "Logout")
    try:
        client.logout()
        _pass()
        passed += 1
    except Exception as e:
        _fail(str(e))
        failed += 1

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    _hr()
    total_run = passed + failed
    skip_note = f",  {skipped} skipped" if skipped else ""
    if failed == 0:
        print(f"  Result: {passed}/{TOTAL_STEPS} passed{skip_note}  \u2713")
    else:
        print(f"  Result: {passed}/{total_run} passed,  {failed} FAILED{skip_note}  \u2717")
    _hr()
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
