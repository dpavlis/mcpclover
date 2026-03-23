#!/usr/bin/env python3
"""Graph validation helpers for CloverDX graph XML."""

import xml.etree.ElementTree as ET


class GraphValidator:
    """
    Validates a .grf XML string against the CloverDX graph schema rules.
    Returns lists of errors and warnings.
    """

    VALID_FIELD_TYPES = {
        "string", "integer", "long", "number", "decimal",
        "date", "boolean", "byte", "cbyte", "variant"
    }
    VALID_RECORD_TYPES = {"delimited", "fixed", "mixed"}
    VALID_CONTAINER_TYPES = {"list", "map"}
    VALID_ENABLED_VALUES = {"enabled", "disabled", "passThrough"}

    def __init__(self, xml_text: str):
        self._xml = xml_text
        self.errors = []
        self.warnings = []

    def _err(self, msg):
        self.errors.append(msg)

    def _warn(self, msg):
        self.warnings.append(msg)

    def validate(self):
        """Run all checks. Returns (errors: list[str], warnings: list[str])."""
        try:
            root = ET.fromstring(self._xml)
        except ET.ParseError as e:
            self._err(f"XML is not well-formed: {e}")
            return self.errors, self.warnings

        self._check_graph_root(root)

        global_el = root.find("Global")
        if global_el is not None:
            self._check_graph_parameters(global_el)
            for meta in global_el.findall("Metadata"):
                self._check_metadata(meta)

        return self.errors, self.warnings

    def _check_graph_root(self, root):
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag != "Graph":
            self._err(f"Root element must be <Graph>, found <{tag}>")
            return
        for attr in ("id", "name"):
            if not root.get(attr):
                self._warn(f"<Graph> is missing recommended attribute '{attr}'")
        if root.find("Global") is None:
            self._err("<Graph> is missing required <Global> section")
        phases = root.findall("Phase")
        if not phases:
            self._warn("<Graph> has no <Phase> elements")
        prev_number = -1
        for phase in phases:
            num_str = phase.get("number")
            if num_str is None:
                self._err("<Phase> is missing required 'number' attribute")
            else:
                try:
                    n = int(num_str)
                    if n < prev_number:
                        self._err(f"<Phase number='{n}'> is out of order (previous was {prev_number})")
                    prev_number = n
                except ValueError:
                    self._err(f"<Phase> 'number' must be an integer, got '{num_str}'")
            for node in phase.findall("Node"):
                self._check_node(node)
            for edge in phase.findall("Edge"):
                self._check_edge(edge)

    def _check_node(self, node):
        nid = node.get("id", "(unknown)")
        if not node.get("id"):
            self._err("<Node> is missing required 'id' attribute")
        if not node.get("type"):
            self._err(f"<Node id='{nid}'> is missing required 'type' attribute")
        enabled = node.get("enabled")
        if enabled and enabled not in self.VALID_ENABLED_VALUES:
            self._warn(f"<Node id='{nid}'> has unknown 'enabled' value '{enabled}'")

    def _check_edge(self, edge):
        eid = edge.get("id", "(unknown)")
        if not edge.get("id"):
            self._err("<Edge> is missing required 'id' attribute")
        for attr in ("fromNode", "toNode"):
            val = edge.get(attr)
            if not val:
                self._err(f"<Edge id='{eid}'> is missing required '{attr}' attribute")
            elif ":" not in val:
                self._err(f"<Edge id='{eid}'> '{attr}' must be 'NodeID:portNumber', got '{val}'")

    def _check_graph_parameters(self, global_el):
        params_el = global_el.find("GraphParameters")
        if params_el is None:
            return
        for child in params_el:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "GraphParameter":
                if child.get("fileURL"):
                    self._err("<GraphParameter> must not have 'fileURL' — use <GraphParameterFile fileURL='...'> instead")
                if not child.get("name"):
                    self._err("<GraphParameter> is missing required 'name' attribute")
                elif child.get("name") == "":
                    self._err("<GraphParameter> has an empty 'name' attribute")

    def _check_metadata(self, meta):
        mid = meta.get("id", "(unknown)")
        if not meta.get("id"):
            self._err("<Metadata> is missing required 'id' attribute")
        if meta.get("fileURL"):
            return
        records = meta.findall("Record")
        if not records:
            self._err(f"<Metadata id='{mid}'> has no <Record> child (and no fileURL)")
            return
        if len(records) > 1:
            self._err(f"<Metadata id='{mid}'> has {len(records)} <Record> elements; expected 1")
        for record in records:
            self._check_record(mid, record)

    def _check_record(self, mid, record):
        rname = record.get("name", "(unnamed)")
        rec_type = record.get("type")
        ctx = f"<Metadata id='{mid}'> <Record name='{rname}'>"
        if not record.get("name"):
            self._err(f"{ctx} is missing required 'name' attribute")
        if not rec_type:
            self._err(f"{ctx} is missing required 'type' attribute")
        elif rec_type not in self.VALID_RECORD_TYPES:
            self._err(f"{ctx} has invalid type '{rec_type}' (must be one of: {', '.join(sorted(self.VALID_RECORD_TYPES))})")
        fields = record.findall("Field")
        if not fields:
            self._warn(f"{ctx} has no <Field> children")
        seen_names: set = set()
        for field in fields:
            self._check_field(mid, rname, rec_type or "delimited", field, seen_names)

    def _check_field(self, mid, rname, rec_type, field, seen_names):
        fname = field.get("name")
        ftype = field.get("type")
        ctx = f"<Metadata id='{mid}'> <Record name='{rname}'> <Field name='{fname or '?'}'>"
        if not fname:
            self._err(f"<Metadata id='{mid}'> <Record name='{rname}'> <Field> is missing required 'name' attribute")
            fname = "(unknown)"
        elif fname in seen_names:
            self._err(f"{ctx} duplicate field name '{fname}'")
        else:
            seen_names.add(fname)
        if not ftype:
            self._err(f"{ctx} is missing required 'type' attribute")
            return
        if ftype not in self.VALID_FIELD_TYPES:
            self._err(f"{ctx} has invalid type '{ftype}' (valid: {', '.join(sorted(self.VALID_FIELD_TYPES))})")
        container = field.get("containerType")
        if container and container not in self.VALID_CONTAINER_TYPES:
            self._err(f"{ctx} has invalid containerType '{container}' (must be 'list' or 'map')")
        if ftype == "decimal":
            for attr in ("length", "scale"):
                val = field.get(attr)
                if val is not None:
                    try:
                        int(val)
                    except ValueError:
                        self._err(f"{ctx} decimal attribute '{attr}' must be an integer, got '{val}'")
        if rec_type == "fixed" and not field.get("size"):
            self._warn(f"{ctx} in a 'fixed' record is missing 'size' attribute")
