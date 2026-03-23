#!/usr/bin/env python3
"""
CloverDX Graph Validator
========================
Validates a CloverDX graph stored on the server in two stages:

  Stage 1 — Local XML validation (no server round-trip after fetch):
    a) XML well-formedness
    b) Graph structure (root, Global, Phase, Node, Edge required attributes)
    c) Metadata structure and field type correctness

  Stage 2 — Server-side checkConfig (async SOAP operation):
    Deep component-level configuration check.
    Only runs if Stage 1 finds no errors.

ConfigurationProblem fields returned by checkConfig (from WSDL):
  elementID, attributeName, severity, priority, message

Usage examples
--------------
  python validate_graph.py --http --sandbox MySandbox --graph graph/MyGraph.grf
  python validate_graph.py --host myserver.com --port 35443 \\
      --user admin --password secret --sandbox MySandbox --graph graph/MyGraph.grf
  python validate_graph.py --http --sandbox MySandbox --graph graph/MyGraph.grf --debug

Dependencies
------------
  pip install zeep requests
"""

import argparse
import base64
import sys
import time
import textwrap

import urllib3
import requests
from zeep import Client
from zeep.transports import Transport
from zeep import helpers as zeep_helpers
from cloverdx_graph_validator import GraphValidator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_HOST     = "localhost"
DEFAULT_PORT     = 8083
DEFAULT_USER     = "clover"
DEFAULT_PASSWORD = "clover"

POLL_TIMEOUT_S   = 120
SERVER_WAIT_MS   = 10_000


# ── Output helpers ─────────────────────────────────────────────────────────────

def _hr(char="─", width=64):
    print(char * width)

def _section(title):
    print()
    _hr()
    print(f"  {title}")
    _hr()

def _fmt_check_config_problems(problems, indent="  "):
    if not problems:
        print(f"{indent}✓  No problems found.")
        return
    for p in problems:
        severity = getattr(p, "severity",      None) or "?"
        element  = getattr(p, "elementID",     None) or "(unknown)"
        attr     = getattr(p, "attributeName", None) or ""
        priority = getattr(p, "priority",      None) or ""
        message  = getattr(p, "message",       None) or str(p)
        attr_str     = f" [{attr}]"     if attr     else ""
        priority_str = f" ({priority})" if priority else ""
        print(f"{indent}[{severity}{priority_str}] {element}{attr_str}: {message}")


# ── Stage 1: Local graph validator ─────────────────────────────────────────────



def _print_validation_results(errors, warnings, indent="  "):
    if not errors and not warnings:
        print(f"{indent}✓  Graph structure and metadata look valid.")
        return
    for w in warnings:
        print(f"{indent}[WARNING] {w}")
    for e in errors:
        print(f"{indent}[ERROR]   {e}")


# ── Stage 2: SOAP validator ────────────────────────────────────────────────────

class CloverDXClient:
    """Handles authentication and SOAP calls to the CloverDX server."""

    def __init__(self, host, port, username, password,
                 verify_ssl=False, use_http=False, debug=False):
        scheme   = "http" if use_http else "https"
        wsdl_url = f"{scheme}://{host}:{port}/clover/webservice?wsdl"

        session = requests.Session()
        session.auth   = (username, password)
        session.verify = verify_ssl

        self._client   = Client(wsdl=wsdl_url, transport=Transport(session=session))
        self._svc      = self._client.service
        self._username = username
        self._password = password
        self._token    = None
        self._debug    = debug

    # ── Auth ───────────────────────────────────────────────────────────────

    def login(self) -> str:
        ops = sorted(op for op in dir(self._svc) if not op.startswith("_"))
        if self._debug:
            print(f"[DEBUG] Available SOAP operations: {ops}")

        login_op = next((op for op in ops if op.lower() == "login"), None)
        if login_op is None:
            print("  NOTE: No Login operation in WSDL — using HTTP Basic Auth only.")
            self._token = ""
            return ""

        resp = getattr(self._svc, login_op)(
            username=self._username, password=self._password, locale="en"
        )
        if self._debug:
            print(f"[DEBUG] Login response: {resp}")

        token = (getattr(resp, "sessionToken", None)
                 or getattr(resp, "return_",    None)
                 or getattr(resp, "token",      None)
                 or str(resp))
        self._token = token
        return token

    # ── Internal helper ────────────────────────────────────────────────────

    def _call(self, op_name: str, **kwargs):
        if self._token:
            kwargs["sessionToken"] = self._token
        return getattr(self._svc, op_name)(**kwargs)

    # ── File download ──────────────────────────────────────────────────────

    def download_graph(self, sandbox: str, graph_path: str) -> str:
        """
        Download graph file content from the server using DownloadFileContent.
        Returns the file content as a UTF-8 string.
        """
        resp = self._call(
            "DownloadFileContent",
            sandboxCode=sandbox,
            filePath=graph_path,
        )
        if self._debug:
            print(f"[DEBUG] DownloadFileContent response type: {type(resp)}")

        # Response is fileContent as base64Binary; zeep usually decodes it to bytes
        content = getattr(resp, "fileContent", resp)
        if isinstance(content, (bytes, bytearray)):
            return content.decode("utf-8")
        # Some zeep versions return already-decoded string or base64 string
        if isinstance(content, str):
            try:
                return base64.b64decode(content).decode("utf-8")
            except Exception:
                return content
        raise RuntimeError(f"Unexpected DownloadFileContent response: {type(content)}")

    # ── checkConfig ────────────────────────────────────────────────────────

    def start_check_config(self, sandbox: str, graph_path: str) -> int:
        resp = self._call(
            "StartCheckConfigOperation",
            sandboxCode=sandbox,
            graphPath=graph_path,
        )
        if self._debug:
            print(f"[DEBUG] StartCheckConfigOperation response: {resp!r}")
        return resp if isinstance(resp, int) else int(
            getattr(resp, "return_", getattr(resp, "handle", resp))
        )

    def poll_check_config(self, handle: int):
        deadline = time.time() + POLL_TIMEOUT_S
        while True:
            resp = self._call(
                "GetCheckConfigOperationResult",
                handle=handle,
                timeout=SERVER_WAIT_MS,
            )
            if self._debug:
                print(f"[DEBUG] GetCheckConfigOperationResult: {resp}")

            if getattr(resp, "aborted",        False):
                return resp
            if not getattr(resp, "timeoutExpired", True):
                return resp

            if time.time() > deadline:
                try:
                    self._call("AbortCheckConfigOperation", handle=handle)
                except Exception:
                    pass
                raise TimeoutError(
                    f"checkConfig did not finish within {POLL_TIMEOUT_S}s "
                    f"(handle={handle})"
                )
            print("    … still running, retrying …")

    def extract_problems(self, poll_result) -> list:
        result_dict = zeep_helpers.serialize_object(poll_result, target_cls=dict)
        if self._debug:
            print(f"[DEBUG] checkConfig serialised result: {result_dict}")

        problems = []
        for item in (result_dict.get("_value_1") or []):
            p = item.get("problems") if isinstance(item, dict) else None
            if not p:
                continue
            for entry in (p if isinstance(p, list) else [p]):
                if isinstance(entry, dict) and entry:
                    problems.append(type("Problem", (), entry)())
        return problems


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Validate a CloverDX graph in two stages:
              1. Local XML / structure / metadata validation
              2. Server-side checkConfig (only if stage 1 passes)
        """),
    )
    p.add_argument("--host",       default=DEFAULT_HOST,
                   help=f"Server hostname (default: {DEFAULT_HOST})")
    p.add_argument("--port",       default=DEFAULT_PORT, type=int,
                   help=f"Server port    (default: {DEFAULT_PORT})")
    p.add_argument("--user",       default=DEFAULT_USER,
                   help=f"Username       (default: {DEFAULT_USER})")
    p.add_argument("--password",   default=DEFAULT_PASSWORD,
                   help=f"Password       (default: {DEFAULT_PASSWORD})")
    p.add_argument("--sandbox",    required=True,
                   help="Sandbox code (e.g. MySandbox)")
    p.add_argument("--graph",      required=True,
                   help="Graph path within the sandbox (e.g. graph/MyGraph.grf)")
    p.add_argument("--http",       action="store_true",
                   help="Use plain HTTP instead of HTTPS")
    p.add_argument("--ssl-verify", action="store_true",
                   help="Verify the server SSL certificate (HTTPS only)")
    p.add_argument("--debug",      action="store_true",
                   help="Print raw SOAP responses for troubleshooting")
    return p


def main():
    args   = build_parser().parse_args()
    scheme = "http" if args.http else "https"

    print("CloverDX Graph Validator")
    print(f"Server  : {scheme}://{args.host}:{args.port}")
    print(f"Target  : sandbox={args.sandbox!r}  graph={args.graph!r}")

    # ── Connect & login ────────────────────────────────────────────────────
    print("\nConnecting …")
    try:
        client = CloverDXClient(
            host=args.host, port=args.port,
            username=args.user, password=args.password,
            verify_ssl=args.ssl_verify,
            use_http=args.http,
            debug=args.debug,
        )
        token = client.login()
        if token:
            short = str(token)[:12] + "…" if len(str(token)) > 12 else str(token)
            print(f"Logged in.  Session token: {short}")
        else:
            print("Logged in.  (HTTP Basic Auth)")
    except Exception as e:
        print(f"\nERROR: Could not connect or authenticate – {e}", file=sys.stderr)
        sys.exit(1)

    # ── Fetch graph ────────────────────────────────────────────────────────
    _section("Fetching graph file")
    try:
        graph_xml = client.download_graph(args.sandbox, args.graph)
        line_count = graph_xml.count("\n") + 1
        print(f"  Downloaded {len(graph_xml):,} bytes ({line_count} lines).")
    except Exception as e:
        print(f"  ERROR: Could not download graph – {e}", file=sys.stderr)
        sys.exit(1)

    # ── Stage 1: Local validation ──────────────────────────────────────────
    _section("Stage 1 / Local validation  (XML · structure · metadata)")
    validator        = GraphValidator(graph_xml)
    errors, warnings = validator.validate()
    _print_validation_results(errors, warnings)

    if errors:
        _section("Summary")
        print(f"  ✗  Stage 1 found {len(errors)} error(s) — "
              f"skipping server checkConfig until they are fixed.")
        if warnings:
            print(f"     ({len(warnings)} warning(s) also reported above)")
        print()
        sys.exit(1)

    if warnings:
        print(f"\n  ↳  {len(warnings)} warning(s) above — proceeding to server check.")

    # ── Stage 2: checkConfig ───────────────────────────────────────────────
    _section(f"Stage 2 / checkConfig  (server, timeout={POLL_TIMEOUT_S}s)")
    overall_ok = True
    try:
        handle = client.start_check_config(args.sandbox, args.graph)
        print(f"  Operation started.  Handle: {handle}")
        poll_result = client.poll_check_config(handle)
        aborted     = bool(getattr(poll_result, "aborted", False))
        print(f"  Finished: {'ABORTED' if aborted else 'FINISHED'}\n")
        problems = client.extract_problems(poll_result)
        _fmt_check_config_problems(problems)
        if problems:
            overall_ok = False
    except TimeoutError as e:
        print(f"  TIMEOUT: {e}", file=sys.stderr)
        overall_ok = False
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        overall_ok = False

    # ── Summary ────────────────────────────────────────────────────────────
    _section("Summary")
    if overall_ok:
        print("  ✓  Graph passed all checks.")
    else:
        print("  ✗  Issues found (see above).")
    print()
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
