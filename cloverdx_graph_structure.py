#!/usr/bin/env python3
"""
Graph structure mutation service for CloverDX .grf files.

Handles add/delete of structural XML elements:
  Metadata, Phase, Node, Edge, Connection, GraphParameter,
  RichTextNote, LookupTable, DictionaryEntry, Sequence

Design contract
───────────────
- Add operations: caller supplies full element XML; this module parses
  it, checks ID/name uniqueness within the element's category, and
  inserts it into the correct DOM location.
- Delete operations: this module performs referential integrity checks
  (blocking or cascading) then removes the element.
- The module never constructs element XML from individual parameters.
- Returns a GraphStructureResult dataclass with: modified XML (or None
  on dry-run), list of changes, list of warnings, and list of errors.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET

try:
    from lxml import etree as _lxml  # type: ignore
    _HAVE_LXML = True
except ImportError:
    _HAVE_LXML = False


# ── Public constants ───────────────────────────────────────────────────────────

#: Element types that live directly under <Global>
GLOBAL_ELEMENT_TYPES = {
    "Metadata", "Connection", "RichTextNote", "LookupTable", "Sequence",
}

#: Element types that live inside <Phase>
PHASE_ELEMENT_TYPES = {"Node", "Edge"}

#: Identity attribute per element type  (how we look them up / deduplicate)
ID_ATTR: Dict[str, str] = {
    "Metadata":        "id",
    "Phase":           "number",
    "Node":            "id",
    "Edge":            "id",
    "Connection":      "id",
    "GraphParameter":  "name",
    "RichTextNote":    "id",
    "LookupTable":     "id",
    "DictionaryEntry": "name",    # <Entry name="..."> inside <Dictionary>
    "Sequence":        "id",
}

VALID_ELEMENT_TYPES = set(ID_ATTR.keys())

# CTL function patterns used to detect Sequence/LookupTable/Dictionary references
_SEQ_REF_RE      = re.compile(r'\bsequence\s*\(\s*"([^"]+)"')
_NEXTVAL_RE      = re.compile(r'\bnextval\s*\(\s*"([^"]+)"')
_CURRENTVAL_RE   = re.compile(r'\bcurrentval\s*\(\s*"([^"]+)"')
_RESETVAL_RE     = re.compile(r'\bresetval\s*\(\s*"([^"]+)"')
_LOOKUP_REF_RE   = re.compile(r'\blookup\s*\(\s*"([^"]+)"')
_DICT_REF_RE     = re.compile(r'\bdict\s*:\s*(\S+)')   # fileURL dict:entryName
_PARAM_REF_RE    = re.compile(r'\$\{([^}]+)\}')


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class GraphStructureResult:
    """Returned by every add/delete operation."""
    ok: bool
    xml_out: Optional[str]          # modified graph XML (None on dry-run or error)
    changes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ── Main service class ─────────────────────────────────────────────────────────

class GraphStructureService:
    """
    Stateless service for adding and deleting structural elements in a
    CloverDX graph XML string.  Instantiate once per tool call.
    """

    def __init__(self, xml_text: str):
        self._original_xml = xml_text
        self._trailing_newline = xml_text.endswith("\n")

    # ── Public entry points ────────────────────────────────────────────────

    def add_element(
        self,
        element_type: str,
        element_xml: str,
        phase_number: Optional[int] = None,
        validate: bool = True,
        dry_run: bool = False,
    ) -> GraphStructureResult:
        """
        Parse element_xml, verify uniqueness, insert into graph XML.

        Parameters
        ----------
        element_type : str
            One of VALID_ELEMENT_TYPES.
        element_xml : str
            Full XML string for the element to insert (supplied by LLM).
        phase_number : int | None
            Required for Node and Edge targets (identifies the <Phase>).
        validate : bool
            Run GraphValidator Stage 1 after insert (default True).
        dry_run : bool
            Return projected impact without modifying the graph.
        """
        if element_type not in VALID_ELEMENT_TYPES:
            return GraphStructureResult(
                ok=False, xml_out=None,
                errors=[f"Unknown element_type '{element_type}'. "
                        f"Valid types: {', '.join(sorted(VALID_ELEMENT_TYPES))}"],
            )

        # Parse the graph

        try:
            graph_root, serializer = _parse_graph(self._original_xml)
        except ET.ParseError as exc:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Graph XML is not well-formed: {exc}"])

        # Parse the element fragment
        try:
            new_elem = _parse_fragment(element_xml)
        except ValueError as exc:
            return GraphStructureResult(ok=False, xml_out=None, errors=[str(exc)])

        # Verify element tag matches declared type
        frag_tag = _local_tag(new_elem)
        expected_tag = "Entry" if element_type == "DictionaryEntry" else element_type
        if frag_tag != expected_tag:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"element_xml root tag <{frag_tag}> does not match "
                                                f"element_type '{element_type}' (expected <{expected_tag}>)"])

        # Uniqueness check
        id_attr_name = ID_ATTR[element_type]
        id_value = new_elem.get(id_attr_name)
        if id_value is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"element_xml is missing required identity attribute "
                                                f"'{id_attr_name}' for element_type '{element_type}'"])

        conflict = _find_existing(graph_root, element_type, id_attr_name, id_value)
        if conflict is not None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Element <{expected_tag} {id_attr_name}='{id_value}'> "
                                                f"already exists in this graph"])

        # Phase requirement for Node/Edge
        if element_type in PHASE_ELEMENT_TYPES:
            if phase_number is None:
                return GraphStructureResult(ok=False, xml_out=None,
                                            errors=[f"phase_number is required when adding a {element_type}"])
            phase_el = _find_phase(graph_root, phase_number)
            if phase_el is None:
                return GraphStructureResult(ok=False, xml_out=None,
                                            errors=[f"Phase number={phase_number} does not exist in graph"])

        changes: List[str] = []

        if dry_run:
            changes.append(f"Would insert <{expected_tag} {id_attr_name}='{id_value}'> "
                           + (_phase_desc(phase_number) if element_type in PHASE_ELEMENT_TYPES
                              else f"into {_target_location(element_type)}"))
            return GraphStructureResult(ok=True, xml_out=None, changes=changes)

        # Perform the insertion
        _insert_element(graph_root, element_type, new_elem, phase_number)
        changes.append(f"Inserted <{expected_tag} {id_attr_name}='{id_value}'> "
                       + (_phase_desc(phase_number) if element_type in PHASE_ELEMENT_TYPES
                          else f"into {_target_location(element_type)}"))

        result_xml = serializer(graph_root, self._original_xml, self._trailing_newline)

        warnings: List[str] = []
        if validate:
            from cloverdx_graph_validator import GraphValidator
            errs, warns = GraphValidator(result_xml).validate()
            warnings.extend(warns)
            if errs:
                return GraphStructureResult(ok=False, xml_out=None,
                                            changes=changes, warnings=warnings,
                                            errors=errs)

        return GraphStructureResult(ok=True, xml_out=result_xml,
                                    changes=changes, warnings=warnings)

    def move_element(
        self,
        element_type: str,
        element_id: str,
        target_phase_number: int,
        validate: bool = True,
        dry_run: bool = False,
    ) -> GraphStructureResult:
        """
        Move a Node or Edge to a different Phase.

        Parameters
        ----------
        element_type : str
            Must be 'Node' or 'Edge'.
        element_id : str
            Value of the element's 'id' attribute.
        target_phase_number : int
            Phase number to move the element into.
        validate : bool
            Run GraphValidator Stage 1 after move.
        dry_run : bool
            Return projected impact without modifying the graph.
        """
        if element_type not in PHASE_ELEMENT_TYPES:
            return GraphStructureResult(
                ok=False, xml_out=None,
                errors=[f"action='edit' (move) is only supported for Node and Edge, "
                        f"not '{element_type}'"],
            )

        try:
            graph_root, serializer = _parse_graph(self._original_xml)
        except ET.ParseError as exc:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Graph XML is not well-formed: {exc}"])

        # Find the element
        target = _find_existing(graph_root, element_type, "id", element_id)
        if target is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"<{element_type} id='{element_id}'> not found in graph"])

        # Find current parent phase
        source_phase = _find_parent_phase(graph_root, target)
        if source_phase is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"<{element_type} id='{element_id}'> is not inside any Phase"])

        source_num = int(source_phase.get("number", -1))

        # Find target phase
        dest_phase = _find_phase(graph_root, target_phase_number)
        if dest_phase is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Phase number={target_phase_number} does not exist in graph"])

        if source_num == target_phase_number:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"<{element_type} id='{element_id}'> is already in "
                                                f"Phase {target_phase_number}"])

        changes: List[str] = [
            f"{'Would move' if dry_run else 'Moved'} <{element_type} id='{element_id}'> "
            f"from Phase {source_num} to Phase {target_phase_number}"
        ]

        if dry_run:
            return GraphStructureResult(ok=True, xml_out=None, changes=changes)

        source_phase.remove(target)
        dest_phase.append(target)

        result_xml = serializer(graph_root, self._original_xml, self._trailing_newline)

        warnings: List[str] = []
        if validate:
            from cloverdx_graph_validator import GraphValidator
            errs, warns = GraphValidator(result_xml).validate()
            warnings.extend(warns)
            if errs:
                return GraphStructureResult(ok=False, xml_out=None,
                                            changes=changes, warnings=warnings,
                                            errors=errs)

        return GraphStructureResult(ok=True, xml_out=result_xml,
                                    changes=changes, warnings=warnings)

    def delete_element(
        self,
        element_type: str,
        element_id: str,
        cascade: bool = False,
        validate: bool = True,
        dry_run: bool = False,
    ) -> GraphStructureResult:
        """
        Remove an element from the graph XML.

        Parameters
        ----------
        element_type : str
            One of VALID_ELEMENT_TYPES.
        element_id : str
            Value of the element's identity attribute (id or name).
        cascade : bool
            When True, automatically remove dependent elements instead
            of refusing when refs are found (supported for Node, Metadata,
            Connection, Phase).
        validate : bool
            Run GraphValidator Stage 1 after delete.
        dry_run : bool
            Return projected impact without modifying the graph.
        """
        if element_type not in VALID_ELEMENT_TYPES:
            return GraphStructureResult(
                ok=False, xml_out=None,
                errors=[f"Unknown element_type '{element_type}'."])

        try:
            graph_root, serializer = _parse_graph(self._original_xml)
        except ET.ParseError as exc:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Graph XML is not well-formed: {exc}"])

        id_attr_name = ID_ATTR[element_type]
        expected_tag = "Entry" if element_type == "DictionaryEntry" else element_type
        target = _find_existing(graph_root, element_type, id_attr_name, element_id)
        if target is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Element <{expected_tag} {id_attr_name}='{element_id}'> "
                                                f"not found in graph"])

        changes: List[str] = []
        warnings: List[str] = []

        # Dispatch per type
        handler = _DELETE_HANDLERS.get(element_type)
        if handler is None:
            return GraphStructureResult(ok=False, xml_out=None,
                                        errors=[f"Delete not implemented for '{element_type}'"])

        err = handler(graph_root, target, element_id, cascade, changes, warnings, dry_run)
        if err:
            return GraphStructureResult(ok=False, xml_out=None,
                                        changes=changes, warnings=warnings,
                                        errors=[err])

        if dry_run:
            return GraphStructureResult(ok=True, xml_out=None,
                                        changes=changes, warnings=warnings)

        result_xml = serializer(graph_root, self._original_xml, self._trailing_newline)

        if validate:
            from cloverdx_graph_validator import GraphValidator
            errs, warns = GraphValidator(result_xml).validate()
            warnings.extend(warns)
            if errs:
                return GraphStructureResult(ok=False, xml_out=None,
                                            changes=changes, warnings=warnings,
                                            errors=errs)

        return GraphStructureResult(ok=True, xml_out=result_xml,
                                    changes=changes, warnings=warnings)


# ── XML parse / serialize helpers ─────────────────────────────────────────────

def _parse_graph(xml_text: str):
    """
    Parse graph XML. Returns (root_element, serializer_fn).
    Uses lxml if available (CDATA-safe), otherwise stdlib ET.
    The serializer_fn signature: (root, original_xml, trailing_newline) -> str
    """
    if _HAVE_LXML:
        parser = _lxml.XMLParser(strip_cdata=False)
        root = _lxml.fromstring(xml_text.encode("utf-8"), parser)
        return root, _serialize_lxml
    else:
        root = ET.fromstring(xml_text)
        return root, _serialize_et


def _parse_fragment(xml_text: str):
    """Parse an XML fragment string; return root element. Raises ValueError on bad XML."""
    try:
        if _HAVE_LXML:
            parser = _lxml.XMLParser(strip_cdata=False)
            return _lxml.fromstring(xml_text.encode("utf-8"), parser)
        return ET.fromstring(xml_text)
    except Exception as exc:
        raise ValueError(f"element_xml is not well-formed XML: {exc}") from exc


def _serialize_lxml(root, original_xml: str, trailing_newline: bool) -> str:
    output = _lxml.tostring(
        root,
        pretty_print=False,
        xml_declaration=True,
        encoding="UTF-8",
    ).decode("UTF-8")
    output = output.replace(
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<?xml version="1.0" encoding="UTF-8"?>',
        1,
    )
    if trailing_newline and not output.endswith("\n"):
        output += "\n"
    return output


def _serialize_et(root, original_xml: str, trailing_newline: bool) -> str:
    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, xml_declaration=True, encoding="UTF-8")
    output = buf.getvalue().decode("UTF-8")
    output = output.replace(
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<?xml version="1.0" encoding="UTF-8"?>',
        1,
    )
    if trailing_newline and not output.endswith("\n"):
        output += "\n"
    return output


def _local_tag(elem) -> str:
    tag = elem.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _get_global(graph_root) -> Any:
    """Return <Global> element, or raise if missing."""
    global_el = graph_root.find("Global")
    if global_el is None:
        raise ValueError("<Global> element not found in graph")
    return global_el


# ── Uniqueness / lookup helpers ────────────────────────────────────────────────

def _find_existing(graph_root, element_type: str, id_attr: str, id_value: str):
    """Return the element if it already exists, else None."""
    if element_type == "DictionaryEntry":
        global_el = graph_root.find("Global")
        if global_el is None:
            return None
        dict_el = global_el.find("Dictionary")
        if dict_el is None:
            return None
        for entry in dict_el.findall("Entry"):
            if entry.get("name") == id_value:
                return entry
        return None

    if element_type == "GraphParameter":
        global_el = graph_root.find("Global")
        if global_el is None:
            return None
        params_el = global_el.find("GraphParameters")
        if params_el is None:
            return None
        for param in params_el.findall("GraphParameter"):
            if param.get("name") == id_value:
                return param
        return None

    if element_type == "Phase":
        for phase in graph_root.findall("Phase"):
            if phase.get("number") == str(id_value):
                return phase
        return None

    tag = element_type
    for elem in graph_root.iter(tag):
        if elem.get(id_attr) == id_value:
            return elem
    return None


def _find_phase(graph_root, phase_number: int):
    for phase in graph_root.findall("Phase"):
        try:
            if int(phase.get("number", -1)) == phase_number:
                return phase
        except ValueError:
            pass
    return None


def _find_parent_phase(graph_root, elem):
    """Return the <Phase> element that directly contains elem, or None."""
    for phase in graph_root.findall("Phase"):
        for child in phase:
            if child is elem:
                return phase
    return None


# ── Insertion helpers ──────────────────────────────────────────────────────────

def _insert_element(graph_root, element_type: str, new_elem, phase_number: Optional[int]):
    """Insert new_elem into the correct location in the graph DOM."""

    if element_type in PHASE_ELEMENT_TYPES:
        phase_el = _find_phase(graph_root, phase_number)
        phase_el.append(new_elem)
        return

    if element_type == "Phase":
        # Insert in sorted order by number
        new_num = int(new_elem.get("number", 0))
        phases = graph_root.findall("Phase")
        insert_idx = len(list(graph_root))  # default: at end of graph root
        children = list(graph_root)
        for i, child in enumerate(children):
            if _local_tag(child) == "Phase":
                try:
                    if int(child.get("number", -1)) > new_num:
                        insert_idx = i
                        break
                except ValueError:
                    pass
        graph_root.insert(insert_idx, new_elem)
        return

    if element_type == "GraphParameter":
        global_el = _get_global(graph_root)
        params_el = global_el.find("GraphParameters")
        if params_el is None:
            params_el = _make_subelement(global_el, "GraphParameters")
        params_el.append(new_elem)
        return

    if element_type == "DictionaryEntry":
        global_el = _get_global(graph_root)
        dict_el = global_el.find("Dictionary")
        if dict_el is None:
            dict_el = _make_subelement(global_el, "Dictionary")
        dict_el.append(new_elem)
        return

    # All other Global elements: Metadata, Connection, RichTextNote, LookupTable, Sequence
    global_el = _get_global(graph_root)
    global_el.append(new_elem)


def _make_subelement(parent, tag: str):
    """Create and append a child element, using lxml or ET as appropriate."""
    if _HAVE_LXML:
        return _lxml.SubElement(parent, tag)
    return ET.SubElement(parent, tag)


def _phase_desc(phase_number: Optional[int]) -> str:
    return f"into Phase {phase_number}"


def _target_location(element_type: str) -> str:
    if element_type in ("GraphParameter",):
        return "<GraphParameters> in <Global>"
    if element_type == "DictionaryEntry":
        return "<Dictionary> in <Global>"
    return "<Global>"


# ── Referential scan helpers ───────────────────────────────────────────────────

def _all_attr_text(graph_root) -> str:
    """Concatenate all <attr> text content from all nodes (for CTL scanning)."""
    parts = []
    for elem in graph_root.iter():
        if _local_tag(elem) == "attr" and elem.text:
            parts.append(elem.text)
    return "\n".join(parts)


def _edges_referencing_node(graph_root, node_id: str) -> List[Any]:
    """Return all edges whose fromNode or toNode starts with node_id:"""
    result = []
    for edge in graph_root.iter("Edge"):
        fn = edge.get("fromNode", "")
        tn = edge.get("toNode", "")
        if fn.split(":")[0] == node_id or tn.split(":")[0] == node_id:
            result.append(edge)
    return result


def _edges_referencing_metadata(graph_root, meta_id: str) -> List[Any]:
    return [e for e in graph_root.iter("Edge") if e.get("metadata") == meta_id]


def _nodes_referencing_connection(graph_root, conn_id: str) -> List[Any]:
    return [n for n in graph_root.iter("Node") if n.get("dbConnection") == conn_id]


def _lookuptables_referencing_metadata(graph_root, meta_id: str) -> List[Any]:
    return [lt for lt in graph_root.iter("LookupTable") if lt.get("metadata") == meta_id]


def _remove_element(graph_root, elem) -> bool:
    """Remove elem from its parent anywhere in the tree. Return True if found."""
    for parent in graph_root.iter():
        children = list(parent)
        for child in children:
            if child is elem:
                parent.remove(child)
                return True
    return False


def _collect_phase_nodes(phase_el) -> List[Any]:
    return list(phase_el.findall("Node"))


# ── Delete handlers ────────────────────────────────────────────────────────────
# Each handler signature:
#   (graph_root, target_elem, element_id, cascade, changes, warnings, dry_run) -> Optional[str]
# Return None on success, or an error string to abort.

def _delete_edge(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    if dry_run:
        changes.append(f"Would remove <Edge id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Edge id='{element_id}'>")
    return None


def _delete_node(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    dep_edges = _edges_referencing_node(graph_root, element_id)
    if dep_edges:
        edge_ids = [e.get("id", "?") for e in dep_edges]
        if not cascade:
            return (f"Cannot delete Node '{element_id}': {len(dep_edges)} edge(s) reference it "
                    f"({', '.join(edge_ids)}). Use cascade=true to remove them automatically.")
        if dry_run:
            for eid in edge_ids:
                changes.append(f"Would remove <Edge id='{eid}'> (cascade from Node)")
        else:
            for edge in dep_edges:
                eid = edge.get("id", "?")
                _remove_element(graph_root, edge)
                changes.append(f"Removed <Edge id='{eid}'> (cascade from Node)")

    if dry_run:
        changes.append(f"Would remove <Node id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Node id='{element_id}'>")
    return None


def _delete_metadata(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    dep_edges = _edges_referencing_metadata(graph_root, element_id)
    dep_lts   = _lookuptables_referencing_metadata(graph_root, element_id)

    if dep_edges or dep_lts:
        if not cascade:
            refs = [f"Edge '{e.get('id','?')}'" for e in dep_edges] + \
                   [f"LookupTable '{lt.get('id','?')}'" for lt in dep_lts]
            return (f"Cannot delete Metadata '{element_id}': referenced by "
                    f"{', '.join(refs)}. Use cascade=true or remove references first.")
        if dep_lts:
            warnings.append("cascade=true: LookupTable references to this Metadata will be "
                            "left dangling — LookupTable elements are not auto-removed because "
                            "they may have other purposes. Remove them manually if needed.")
        for edge in dep_edges:
            eid = edge.get("id", "?")
            if dry_run:
                changes.append(f"Would remove <Edge id='{eid}'> (cascade from Metadata)")
            else:
                _remove_element(graph_root, edge)
                changes.append(f"Removed <Edge id='{eid}'> (cascade from Metadata)")

    if dry_run:
        changes.append(f"Would remove <Metadata id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Metadata id='{element_id}'>")
    return None


def _delete_phase(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    nodes = _collect_phase_nodes(target)
    if nodes:
        if not cascade:
            return (f"Cannot delete Phase '{element_id}': it contains {len(nodes)} node(s). "
                    "Use cascade=true to remove them (and their edges) automatically.")
        for node in nodes:
            nid = node.get("id", "?")
            dep_edges = _edges_referencing_node(graph_root, nid)
            for edge in dep_edges:
                eid = edge.get("id", "?")
                if dry_run:
                    changes.append(f"Would remove <Edge id='{eid}'> (cascade from Phase via Node)")
                else:
                    _remove_element(graph_root, edge)
                    changes.append(f"Removed <Edge id='{eid}'> (cascade from Phase via Node)")
            if dry_run:
                changes.append(f"Would remove <Node id='{nid}'> (cascade from Phase)")
            else:
                _remove_element(graph_root, node)
                changes.append(f"Removed <Node id='{nid}'> (cascade from Phase)")

    # Also remove any edges directly inside the phase (not cross-phase)
    phase_edges = list(target.findall("Edge"))
    for edge in phase_edges:
        eid = edge.get("id", "?")
        if dry_run:
            changes.append(f"Would remove <Edge id='{eid}'> (contained in Phase)")
        else:
            _remove_element(graph_root, edge)
            changes.append(f"Removed <Edge id='{eid}'> (contained in Phase)")

    if dry_run:
        changes.append(f"Would remove <Phase number='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Phase number='{element_id}'>")
    return None


def _delete_connection(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    dep_nodes = _nodes_referencing_connection(graph_root, element_id)
    if dep_nodes:
        node_ids = [n.get("id", "?") for n in dep_nodes]
        if not cascade:
            return (f"Cannot delete Connection '{element_id}': {len(dep_nodes)} node(s) reference it "
                    f"({', '.join(node_ids)}). Use cascade=true to remove the dbConnection attribute.")
        for node in dep_nodes:
            nid = node.get("id", "?")
            if dry_run:
                changes.append(f"Would remove dbConnection attribute from <Node id='{nid}'> (cascade)")
            else:
                del node.attrib["dbConnection"]
                changes.append(f"Removed dbConnection attribute from <Node id='{nid}'> (cascade)")

    if dry_run:
        changes.append(f"Would remove <Connection id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Connection id='{element_id}'>")
    return None


def _delete_graph_parameter(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    # Scan for ${name} references in all attribute values
    pattern = f"${{{element_id}}}"
    ref_locations: List[str] = []
    for elem in graph_root.iter():
        tag = _local_tag(elem)
        for attr_val in elem.attrib.values():
            if pattern in attr_val:
                ref_locations.append(f"<{tag}> attribute value")
                break
        if elem.text and pattern in elem.text:
            ref_locations.append(f"<{tag}> text content")

    if ref_locations:
        warnings.append(
            f"GraphParameter '${{{element_id}}}' is still referenced in {len(ref_locations)} "
            f"location(s): {', '.join(ref_locations[:5])}{'...' if len(ref_locations) > 5 else ''}. "
            "Parameter removed; update referencing attributes manually."
        )

    if dry_run:
        changes.append(f"Would remove <GraphParameter name='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <GraphParameter name='{element_id}'>")
    return None


def _delete_rich_text_note(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    if dry_run:
        changes.append(f"Would remove <RichTextNote id='{element_id}>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <RichTextNote id='{element_id}'>")
    return None


def _delete_lookup_table(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    # Check Node lookupTable attribute references
    node_refs = [n.get("id", "?") for n in graph_root.iter("Node")
                 if n.get("lookupTable") == element_id]
    # Check CTL attr blocks for lookup("id") patterns
    ctl_refs: List[str] = []
    for node in graph_root.iter("Node"):
        nid = node.get("id", "?")
        for attr_el in node.iter("attr"):
            text = attr_el.text or ""
            if _LOOKUP_REF_RE.search(text):
                for m in _LOOKUP_REF_RE.finditer(text):
                    if m.group(1) == element_id:
                        ctl_refs.append(nid)

    all_refs = node_refs + ctl_refs
    if all_refs:
        return (f"Cannot delete LookupTable '{element_id}': referenced by node(s) "
                f"{', '.join(sorted(set(all_refs)))}. Remove references manually before deleting "
                "(CTL lookup() references cannot be auto-patched).")

    if dry_run:
        changes.append(f"Would remove <LookupTable id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <LookupTable id='{element_id}'>")
    return None


def _delete_dictionary_entry(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    # Scan fileURL attributes for dict:name references
    pattern = f"dict:{element_id}"
    ref_locations = [
        n.get("id", "?") for n in graph_root.iter("Node")
        if pattern in n.get("fileURL", "")
    ]
    if ref_locations:
        return (f"Cannot delete DictionaryEntry '{element_id}': found 'dict:{element_id}' "
                f"in fileURL of node(s) {', '.join(ref_locations)}. Remove those references first.")

    if dry_run:
        changes.append(f"Would remove <Entry name='{element_id}'>")
        return None
    global_el = graph_root.find("Global")
    if global_el is None:
        return "No <Global> element found"
    dict_el = global_el.find("Dictionary")
    if dict_el is None:
        return f"No <Dictionary> element found"
    dict_el.remove(target)
    changes.append(f"Removed <Entry name='{element_id}'>")
    # Clean up empty Dictionary container
    if len(list(dict_el)) == 0:
        global_el.remove(dict_el)
        changes.append("Removed empty <Dictionary> container")
    return None


def _delete_sequence(graph_root, target, element_id, cascade, changes, warnings, dry_run):
    ctl_text = _all_attr_text(graph_root)
    patterns = [_SEQ_REF_RE, _NEXTVAL_RE, _CURRENTVAL_RE, _RESETVAL_RE]
    ref_nodes: List[str] = []
    for node in graph_root.iter("Node"):
        nid = node.get("id", "?")
        node_ctl = "\n".join(
            (a.text or "") for a in node.iter("attr")
        )
        for pat in patterns:
            for m in pat.finditer(node_ctl):
                if m.group(1) == element_id:
                    ref_nodes.append(nid)
                    break
    if ref_nodes:
        return (f"Cannot delete Sequence '{element_id}': CTL references found in node(s) "
                f"{', '.join(sorted(set(ref_nodes)))}. Remove CTL references manually first.")

    if dry_run:
        changes.append(f"Would remove <Sequence id='{element_id}'>")
        return None
    _remove_element(graph_root, target)
    changes.append(f"Removed <Sequence id='{element_id}'>")
    return None


# ── Delete handler dispatch table ──────────────────────────────────────────────

_DELETE_HANDLERS = {
    "Metadata":        _delete_metadata,
    "Phase":           _delete_phase,
    "Node":            _delete_node,
    "Edge":            _delete_edge,
    "Connection":      _delete_connection,
    "GraphParameter":  _delete_graph_parameter,
    "RichTextNote":    _delete_rich_text_note,
    "LookupTable":     _delete_lookup_table,
    "DictionaryEntry": _delete_dictionary_entry,
    "Sequence":        _delete_sequence,
}
