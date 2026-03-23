#!/usr/bin/env python3
import argparse
import json
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


def _to_bool_if_bool_str(value: Optional[str]) -> Any:
    if value is None:
        return None
    low = value.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return value


def _copy_attrs(el: ET.Element, keys: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in keys:
        raw = el.get(key)
        if raw is not None:
            result[key] = _to_bool_if_bool_str(raw)
    return result


def _convert_port(port_el: ET.Element) -> Dict[str, Any]:
    port = {
        "type": port_el.tag,
    }
    port.update(_copy_attrs(port_el, ["name", "required", "label"]))

    metadata_el = port_el.find("Metadata")
    if metadata_el is not None and metadata_el.get("id"):
        port["metadata"] = {"id": metadata_el.get("id")}

    return port


def _convert_property(prop_el: ET.Element) -> Dict[str, Any]:
    prop: Dict[str, Any] = {
        "name": prop_el.get("name", ""),
        "label": prop_el.get("displayName", ""),
    }

    prop.update(
        _copy_attrs(
            prop_el,
            [
                "description",
                "modifiable",
                "nullable",
                "required",
                "primaryAttribute",
                "redundant",
                "delegate",
                "defaultHint",
                "secret",
                "category",
            ],
        )
    )

    single_type = prop_el.find("singleType")
    enum_type = prop_el.find("enumType")

    if single_type is not None:
        if single_type.get("name"):
            prop["type"] = single_type.get("name")
        for key in [
            "inputPortName",
            "outputPortName",
            "selectionMode",
            "title",
            "leftLabel",
            "rightLabel",
            "fixedKeys",
        ]:
            if single_type.get(key) is not None:
                prop[key] = _to_bool_if_bool_str(single_type.get(key))
    elif enum_type is not None:
        prop["type"] = "enum"
        values = []
        for item in enum_type.findall("item"):
            values.append(
                {
                    "value": item.get("value", ""),
                    "label": item.get("displayValue", ""),
                }
            )
        prop["values"] = values

    return {k: v for k, v in prop.items() if v is not None and v != ""}


def convert_component(plugin_xml: str, component_type: Optional[str] = None) -> Dict[str, Any]:
    root = ET.parse(plugin_xml).getroot()

    components = root.findall(".//ETLComponent")
    if not components:
        raise RuntimeError("No ETLComponent entries found in XML.")

    selected = None
    if component_type:
        wanted = component_type.strip().upper()
        for comp in components:
            if (comp.get("type") or "").upper() == wanted:
                selected = comp
                break
        if selected is None:
            available = ", ".join(sorted({(c.get("type") or "") for c in components if c.get("type")}))
            raise RuntimeError(f"Component type '{component_type}' not found. Available: {available}")
    else:
        selected = components[0]

    output: Dict[str, Any] = {
        "category": selected.get("category", ""),
        "name": selected.get("name", ""),
        "type": selected.get("type", ""),
        "shortDescription": (selected.findtext("shortDescription") or "").strip(),
        "description": (selected.findtext("description") or "").strip(),
    }

    input_ports_el = selected.find("inputPorts")
    output_ports_el = selected.find("outputPorts")
    properties_el = selected.find("properties")

    input_ports = []
    if input_ports_el is not None:
        for child in list(input_ports_el):
            input_ports.append(_convert_port(child))

    output_ports = []
    if output_ports_el is not None:
        for child in list(output_ports_el):
            output_ports.append(_convert_port(child))

    properties = []
    if properties_el is not None:
        for prop_el in properties_el.findall("property"):
            properties.append(_convert_property(prop_el))

    output["inputPorts"] = input_ports
    output["outputPorts"] = output_ports
    output["properties"] = properties

    return output


def convert_all_components(plugin_xml: str) -> List[Dict[str, Any]]:
    root = ET.parse(plugin_xml).getroot()
    components = root.findall(".//ETLComponent")
    if not components:
        return []

    result: List[Dict[str, Any]] = []
    for comp in components:
        ctype = comp.get("type")
        if not ctype:
            continue
        result.append(convert_component(plugin_xml, ctype))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert ETLComponent from plugin XML to components.json-like JSON")
    parser.add_argument("--xml", default="plugin1.xml", help="Path to plugin XML")
    parser.add_argument("--type", dest="component_type", default=None, help="Component type to export (e.g. EMAIL_FILTER)")
    parser.add_argument("--all", action="store_true", help="Export all components found in plugin XML")
    parser.add_argument("--out", default=None, help="Output JSON path")
    args = parser.parse_args()

    out_path = args.out
    if args.all:
        data_all = convert_all_components(args.xml)
        if not out_path:
            out_path = "converted_all_components.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data_all, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path} ({len(data_all)} components)")
        return

    data = convert_component(args.xml, args.component_type)
    if not out_path:
        suffix = (data.get("type") or "component").lower()
        out_path = f"converted_{suffix}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
