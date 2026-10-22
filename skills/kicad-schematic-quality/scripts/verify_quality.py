#!/usr/bin/env python3
# 용도: 명시 project root와 고정 registry에 결속한 XML·레이아웃·ERC·PDF·companion 증거를 검증한다.
"""이식 가능한 KiCad 회로도 deterministic 검증기.

시각적 이해 가능성, 동적 동작, PCB, 제조, 통전, 실물 안전의
합격을 판정하지 않는다. registry 자체의 사전 고정은 root 신뢰 경계다.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import package_identity
from guarded_mcp import AdapterError as GuardedPolicyError, ProjectPolicy


class VerificationError(Exception):
    pass


RESERVED_SCOPE_KEYS = {
    "deterministic_static_contract",
    "visual_review",
    "dynamic_operation",
    "glyph_completeness",
    "all_pages_manual_review",
    "electrical_performance",
    "all_erc_rules",
    "schematic_position_as_pcb_distance",
    "voltage_current_rating_and_sequencing",
    "pcb_manufacturing_energization_physical_safety",
    "port_direction_and_return_semantics",
    "project_semantic_logic",
    "port_physical_attachment",
    "port_page_annotations",
}


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"JSON duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise VerificationError(f"JSON nonfinite number: {value}")


def _reject_null_unknown(value, location="$" ):
    if value is None:
        raise VerificationError(f"JSON null/unknown 금지: {location}")
    if isinstance(value, float) and not math.isfinite(value):
        raise VerificationError(f"JSON nonfinite number: {location}")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_null_unknown(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_null_unknown(child, f"{location}[{index}]")


def load_json(path: Path):
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise VerificationError(f"JSON UTF-8 해석 실패: {path}: {exc}") from exc
    _reject_null_unknown(value)
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def validate_contract_scope_limits(value):
    require(isinstance(value, dict), "scope_limits는 JSON object여야 함")
    for key, status in value.items():
        require(isinstance(key, str) and key and isinstance(status, str) and status,
                "scope_limits key/value는 비어 있지 않은 문자열이어야 함")
        if key in RESERVED_SCOPE_KEYS:
            require(status.startswith(("not_", "partially_")),
                    f"scope_limits가 검증기 예약 scope를 확장할 수 없음: {key}={status}")
    return value


def validate_project_root(raw: Path) -> Path:
    require(raw.is_absolute(), "--project-root는 absolute path여야 함")
    require(raw.exists() and raw.is_dir() and not raw.is_symlink(),
            "--project-root는 존재하는 일반 directory여야 함")
    root = raw.resolve()
    require(root == raw, "--project-root 자체 또는 상위 경로에 symbolic link가 포함됨")
    return root


def safe_project_path(root: Path, raw: Path | str, *, label: str,
                      must_exist: bool = True, output_new: bool = False) -> Path:
    value = Path(raw)
    candidate = value if value.is_absolute() else root / value
    lexical = Path(os.path.abspath(candidate))
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"{label} 경로가 project root 밖을 가리킴: {raw}") from exc
    require(".." not in value.parts, f"{label} 경로에 lexical parent가 포함됨: {raw}")
    cursor = root
    for part in relative.parts:
        cursor /= part
        require(not cursor.is_symlink(), f"{label} 경로에 symbolic link가 포함됨: {raw}")
        if cursor.exists() and cursor != lexical:
            require(cursor.is_dir(), f"{label} 상위 경로가 directory가 아님: {cursor}")
    resolved = lexical.resolve(strict=False)
    require(resolved == root or root in resolved.parents,
            f"{label} 경로가 project root 밖으로 resolve됨: {raw}")
    if must_exist:
        require(lexical.is_file() and not lexical.is_symlink(), f"{label} 파일 누락: {raw}")
    if output_new:
        require(not lexical.exists() and not lexical.is_symlink(),
                f"{label}는 새 경로여야 함: {raw}")
    return lexical


def select_registry_path(root: Path, registry_arg: Path, expected_sha256: str) -> Path:
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") is not None,
            "registry SHA256 형식 불일치")
    return safe_project_path(root, registry_arg, label="registry")


def normalized_net(name: str) -> str:
    require(bool(name), "XML net 이름 누락")
    # 루트 local net의 선행 slash 하나만 제거하고 계층 경로는 보존한다.
    return name[1:] if name.startswith("/") and name.count("/") == 1 else name


def layout_source_files(layout):
    files = layout.get("files", layout.get("source_files"))
    require(isinstance(files, dict) and files, "layout 소스 해시 매핑 누락")
    return files


def load_sealed_contract(runtime_path: Path, registry_path: Path, project_root: Path,
                         registry_expected_sha256: str):
    runtime = load_json(runtime_path)
    required_runtime_fields = {"schema_version", "contract_kind", "sealed", "profile_id",
                               "candidate", "companion_receipts", "producer_plan_binding",
                               "producer_package_identity"}
    require(set(runtime) == required_runtime_fields,
            "runtime envelope 필드 누락/추가")
    require(type(runtime.get("schema_version")) is int
            and runtime.get("schema_version") == 2,
            "runtime schema_version은 integer 2여야 함")
    require(runtime.get("contract_kind") == "schematic-quality-runtime"
            and runtime.get("sealed") is True, "sealed runtime envelope가 아님")
    candidate = runtime.get("candidate")
    require(isinstance(candidate, dict)
            and set(candidate) == {"inputs_sha256", "source_files"},
            "runtime candidate hash 범위 누락/추가")
    require(set(candidate["inputs_sha256"]) == {"netlist", "layout", "erc", "pdf"},
            "runtime inputs_sha256는 4개 CLI 입력 전체여야 함")
    require(isinstance(candidate["source_files"], dict) and candidate["source_files"],
            "runtime source_files 누락")
    require(isinstance(runtime["companion_receipts"], dict), "companion_receipts 구조 불일치")

    require(registry_path.is_file(), "고정 registry 누락")
    registry_bytes = registry_path.read_bytes()
    registry_sha256 = hashlib.sha256(registry_bytes).hexdigest()
    if registry_expected_sha256 is not None:
        require(registry_sha256 == registry_expected_sha256,
                "registry SHA256 불일치")
    registry = json.loads(registry_bytes)
    require(type(registry.get("schema_version")) is int
            and registry.get("schema_version") == 1,
            "registry schema_version은 integer 1이어야 함")
    require(isinstance(registry.get("profiles"), dict), "registry 구조 불일치")
    profile_id = runtime["profile_id"]
    require(profile_id in registry["profiles"], f"registry에 없는 profile_id: {profile_id}")
    seal = registry["profiles"][profile_id]
    require(set(seal) == {"semantic_contract", "sha256"}, "registry profile seal 구조 불일치")
    semantic_path = safe_project_path(
        project_root, seal["semantic_contract"], label="semantic contract")
    require(semantic_path.is_file(), "sealed semantic contract 누락")
    require(digest(semantic_path) == seal["sha256"], "sealed semantic contract SHA 불일치")
    semantic = load_json(semantic_path)
    require(type(semantic.get("schema_version")) is int
            and semantic.get("schema_version") == 2
            and semantic.get("contract_kind") == "schematic-quality-semantic"
            and semantic.get("profile_id") == profile_id,
            "semantic schema_version/contract 정체성 불일치")
    required = {"semantic_sources", "components", "component_sheets", "functional_units",
                "nets", "pin_types", "pin_units",
                "net_name_policy",
                "sheet_sources", "required_source_files", "xml_component_sheet_policy",
                "layout_component_policy", "wire_coverage", "ports",
                "duplicate_pin_exceptions", "erc", "pdf", "layout", "required_companions",
                "scope_limits"}
    require(required <= set(semantic),
            f"semantic contract 필수 필드 누락: {sorted(required-set(semantic))}")
    for path_text, expected in semantic["semantic_sources"].items():
        path = safe_project_path(project_root, path_text, label="semantic source")
        require(path.is_file() and digest(path) == expected,
                f"semantic oracle/source SHA 불일치: {path_text}")
    return runtime, semantic, {
        "registry": str(registry_path.relative_to(project_root)), "registry_sha256": registry_sha256,
        "registry_expected_sha256": registry_expected_sha256,
        "semantic_contract": seal["semantic_contract"], "semantic_sha256": seal["sha256"],
        "trust_boundary": registry.get("trust_boundary", ""),
        "trust_boundary_evidence": "registry_self_declaration_only",
        "phase_root_trust_binding": "not_checked_by_common_verifier",
    }


def verify_hashes(runtime, semantic, paths, layout, seal, project_root: Path):
    actual_inputs = {name: digest(path) for name, path in paths.items() if name != "contract"}
    require(actual_inputs == runtime["candidate"]["inputs_sha256"],
            f"runtime-CLI 입력 SHA 불일치: {actual_inputs}")
    observed = layout_source_files(layout)
    require(observed == runtime["candidate"]["source_files"],
            "runtime-layout CAD 소스 범위·SHA 불일치")
    required_sources = semantic["required_source_files"]
    require(isinstance(required_sources, list) and len(required_sources) == len(set(required_sources)),
            "required_source_files 중복/구조 불일치")
    require(set(observed) == set(required_sources),
            f"필수 CAD 소스 범위 불일치: missing={sorted(set(required_sources)-set(observed))}, "
            f"extra={sorted(set(observed)-set(required_sources))}")
    sheet_sources = semantic["sheet_sources"]
    require(isinstance(sheet_sources, dict) and set(sheet_sources) == set(layout.get("sheets", {})),
            "sheet_sources-layout sheet 전수 범위 불일치")
    require(set(sheet_sources.values()) <= set(required_sources), "sheet_sources가 필수 소스 범위 밖임")
    for path_text, expected in observed.items():
        path = safe_project_path(project_root, path_text, label="CAD source")
        require(path.is_file(), f"CAD 소스 누락: {path_text}")
        require(digest(path) == expected, f"stale CAD hash: {path_text}")
    return {
        "inputs": {**actual_inputs, "runtime_envelope": digest(paths["contract"])},
        "cad_source_files": len(observed), **seal,
    }


def verify_producer_plan_binding(runtime, project_root: Path):
    binding = runtime.get("producer_plan_binding")
    if binding is None:
        return {"status": "not_provided_by_runtime"}
    required = {"schema_version", "plan_index", "mode", "project_stem",
                "require_all_plans_before_write", "allowed_files", "read_only_files",
                "plans", "common_plan"}
    require(isinstance(binding, dict) and set(binding) == required,
            "producer_plan_binding 구조 불일치")
    require(type(binding.get("schema_version")) is int
            and binding.get("schema_version") == 1,
            "producer_plan_binding schema_version은 integer 1이어야 함")
    require(binding["mode"] in {"design", "rewrite", "change", "review"}
            and isinstance(binding["project_stem"], str) and binding["project_stem"],
            "producer_plan_binding mode/project_stem 불일치")
    require(binding["require_all_plans_before_write"] is True,
            "producer_plan_binding require_all_plans_before_write가 true가 아님")
    require(isinstance(binding["allowed_files"], list)
            and isinstance(binding["read_only_files"], list),
            "producer_plan_binding file 목록 구조 불일치")

    def checked_record(record, *, label, expected_fields):
        require(isinstance(record, dict) and set(record) == expected_fields,
                f"producer_plan_binding {label} record 구조 불일치")
        require(type(record["size"]) is int and record["size"] >= 0
                and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is not None,
                f"producer_plan_binding {label} size/SHA 불일치")
        path = safe_project_path(project_root, record["path"], label=label)
        require(path.stat().st_size == record["size"] and digest(path) == record["sha256"],
                f"producer_plan_binding {label} 현재 bytes 불일치")
        return path

    index = checked_record(binding["plan_index"], label="plan-index",
                           expected_fields={"path", "sha256", "size"})
    require(index.name == "plan-index.json", "producer plan-index 파일명 불일치")
    plans = binding["plans"]
    require(isinstance(plans, list) and plans, "producer_plan_binding plans 누락")
    seen = set()
    for record in plans:
        path = checked_record(record, label="page plan",
                              expected_fields={"schematic", "path", "sha256", "size"})
        require(isinstance(record["schematic"], str)
                and record["schematic"].endswith(".kicad_sch"),
                "producer_plan_binding schematic 불일치")
        require(record["schematic"] not in seen, "producer_plan_binding schematic 중복")
        seen.add(record["schematic"])
        require(path.is_file(), "producer page plan 누락")
    common = checked_record(binding["common_plan"], label="common plan",
                            expected_fields={"path", "sha256", "size"})
    require(common.is_file(), "producer common plan 누락")
    try:
        policy = ProjectPolicy(project_root, workspace_root=project_root)
        policy._capture_all_write_plans()
        current_plans, current_common = policy._assert_write_plans_unchanged()
    except GuardedPolicyError as exc:
        raise VerificationError(f"현재 ProjectPolicy plan 검증 실패: {exc}") from exc
    require(current_common is not None, "현재 ProjectPolicy common plan 증거 누락")
    expected = {
        "schema_version": 1,
        "plan_index": {"path": "plan-index.json", "sha256": policy.index_sha256,
                       "size": len(policy.index_bytes)},
        "mode": policy.mode,
        "project_stem": policy.project_stem,
        "require_all_plans_before_write": policy.require_all_plans_before_write,
        "allowed_files": sorted(policy.allowed_files),
        "read_only_files": sorted(policy.read_only_files),
        "plans": [{"schematic": row["schematic"], "path": row["plan"],
                   "sha256": row["sha256"], "size": row["size"]}
                  for row in current_plans],
        "common_plan": {"path": current_common["plan"],
                        "sha256": current_common["sha256"],
                        "size": current_common["size"]},
    }
    require(package_identity.strict_equal(binding, expected),
            "runtime producer_plan_binding이 현재 ProjectPolicy 증거와 exact 불일치")
    return {"status": "checked_current_bytes", "plan_index_sha256": digest(index),
            "plans": len(plans), "common_plan_sha256": digest(common)}


def lib_id(component):
    source = component.find("libsource")
    require(source is not None and source.get("lib") and source.get("part"),
            f"부품 {component.get('ref')} libsource 누락")
    return f"{source.get('lib')}:{source.get('part')}"


def verify_xml(contract, path: Path, project_root: Path):
    tree = ET.parse(path)
    source_text = tree.findtext("./design/source")
    require(isinstance(source_text, str) and source_text.strip(),
            "XML design/source 누락: native owning source를 확인할 수 없음")
    source_path = safe_project_path(
        project_root, source_text.strip(), label="XML design/source")
    source_relative = str(source_path.relative_to(project_root))
    require(source_relative in set(contract["required_source_files"]),
            f"XML design/source가 required_source_files 밖임: {source_relative}")
    components = {}
    for component in tree.findall("./components/comp"):
        ref = component.get("ref")
        require(ref and ref not in components, f"부품 ref 누락/중복: {ref}")
        components[ref] = component
    expected_components = contract["components"]
    require(isinstance(expected_components, dict) and expected_components,
            "semantic components가 비어 있어 component coverage unknown")
    require(set(components) == set(expected_components),
            f"부품 집합 불일치: missing={sorted(set(expected_components)-set(components))[:20]}, "
            f"extra={sorted(set(components)-set(expected_components))[:20]}")
    for ref, expected in expected_components.items():
        actual = components[ref]
        fields = {"value": actual.findtext("value") or "",
                  "footprint": actual.findtext("footprint") or "", "lib_id": lib_id(actual)}
        require(fields == expected, f"부품 속성 불일치 {ref}: expected={expected}, actual={fields}")

    component_sheets = contract["component_sheets"]
    require(set(component_sheets) == set(components),
            "component_sheets는 부품 전수를 명시해야 함")
    sheet_policy = contract["xml_component_sheet_policy"]
    require(set(sheet_policy) == set(contract["sheet_sources"]),
            "xml_component_sheet_policy-sheet_sources 범위 불일치")
    for sheet_id, policy in sheet_policy.items():
        require(set(policy) == {"sheetfile", "sheetpath_names"},
                f"XML sheet policy 구조 불일치: {sheet_id}")
        require(Path(contract["sheet_sources"][sheet_id]).name == policy["sheetfile"],
                f"sheet_sources basename-policy 불일치: {sheet_id}")
    for ref, component in components.items():
        sheet_id = component_sheets[ref]
        require(sheet_id in sheet_policy, f"부품의 미등록 semantic sheet: {ref}:{sheet_id}")
        properties = component.findall("property[@name='Sheetfile']")
        require(len(properties) == 1 and properties[0].get("value"),
                f"XML Sheetfile property 누락/중복: {ref}")
        require(properties[0].get("value") == sheet_policy[sheet_id]["sheetfile"],
                f"XML Sheetfile-semantic sheet 불일치: {ref}:"
                f"{properties[0].get('value')}!={sheet_policy[sheet_id]['sheetfile']}")
        sheetpaths = component.findall("sheetpath")
        require(len(sheetpaths) == 1 and sheetpaths[0].get("names"),
                f"XML sheetpath 누락/중복: {ref}")
        require(sheetpaths[0].get("names") == sheet_policy[sheet_id]["sheetpath_names"],
                f"XML sheetpath-semantic sheet 불일치: {ref}:"
                f"{sheetpaths[0].get('names')}!={sheet_policy[sheet_id]['sheetpath_names']}")

    nets, owners, pin_to_net = {}, {}, {}
    for net in tree.findall("./nets/net"):
        raw_name = net.get("name")
        name = normalized_net(raw_name)
        require(name not in nets, f"정규화 후 net 이름 중복: {raw_name} -> {name}")
        members = []
        for node in net.findall("node"):
            ref, pin = node.get("ref"), node.get("pin")
            key = f"{ref}.{pin}"
            require(ref in components and pin, f"미등록 부품 또는 pin: {key}")
            require(key not in owners, f"물리 pin 중복: {key}")
            require(node.get("pintype"), f"pin type 누락: {key}")
            owners[key] = node
            pin_to_net[key] = name
            members.append(key)
        require(members, f"빈 net: {name}")
        nets[name] = sorted(members)
    expected_nets = {name: sorted(members) for name, members in contract["nets"].items()}
    name_policy = contract["net_name_policy"]
    if name_policy.get("mode") == "exact_after_root_local_slash":
        require(nets == expected_nets, "net-pin 전수 계약 불일치")
    elif name_policy.get("mode") == "partition_bijection":
        expected_by_partition = {tuple(members): name for name, members in expected_nets.items()}
        require(len(expected_by_partition) == len(expected_nets), "semantic net pin partition 중복")
        require(set(map(tuple, nets.values())) == set(expected_by_partition),
                "net pin partition 전단사 불일치")
        if name_policy.get("cross_sheet_names_exact"):
            for actual_name, members in nets.items():
                canonical_name = expected_by_partition[tuple(members)]
                owner_sheets = {contract["component_sheets"][pin.rsplit('.',1)[0]] for pin in members}
                if len(owner_sheets) > 1:
                    require(actual_name == canonical_name,
                            f"시트 간 net 이름 불일치: {actual_name}!={canonical_name}")
        pin_to_net = {pin: expected_by_partition[tuple(members)]
                      for members in nets.values() for pin in members}
    else:
        raise VerificationError(f"알 수 없는 net_name_policy: {name_policy}")
    expected_types = contract["pin_types"]
    require(isinstance(expected_types, dict) and expected_types,
            "semantic pin_types가 비어 있어 pin coverage unknown")
    require(all(isinstance(value, str) and value.strip() for value in expected_types.values()),
            "semantic pin_types에 nil/빈 값이 있어 pin coverage unknown")
    pin_owner_refs = {key.rsplit(".", 1)[0] for key in expected_types}
    require(pin_owner_refs == set(expected_components),
            "semantic component별 pin coverage 누락/추가")
    require(set(expected_types) == set(owners),
            f"pin_types 전수 범위 불일치: missing={sorted(set(owners)-set(expected_types))[:20]}, "
            f"extra={sorted(set(expected_types)-set(owners))[:20]}")
    require({key: node.get("pintype") for key, node in owners.items()} == expected_types,
            "pin type 계약 불일치")
    expected_units = contract["pin_units"]
    require(isinstance(expected_units, dict) and set(expected_units) == set(owners)
            and all(type(unit) is int and unit >= 1 for unit in expected_units.values()),
            "semantic pin_units 전수 범위/구조 불일치")
    functions = contract.get("pin_functions")
    if functions is not None:
        require(set(functions) == set(owners), "pin_functions 전수 범위 불일치")
        require({key: node.get("pinfunction") for key, node in owners.items()} == functions,
                "pin function 계약 불일치")
    return {"tree": tree, "components": len(components), "pins": len(owners), "nets": len(nets),
            "source": source_relative, "pin_keys": set(owners), "pin_to_net": pin_to_net}


def point(x, y):
    return round(float(x), 5), round(float(y), 5)


def on_segment(target, wire):
    left, right = wire
    cross = ((right[0]-left[0])*(target[1]-left[1])
             - (right[1]-left[1])*(target[0]-left[0]))
    return (abs(cross) < 1e-5
            and min(left[0], right[0])-1e-5 <= target[0] <= max(left[0], right[0])+1e-5
            and min(left[1], right[1])-1e-5 <= target[1] <= max(left[1], right[1])+1e-5)


def expected_duplicate_map(contract, sheet_id):
    result = {}
    for row in contract["duplicate_pin_exceptions"]:
        if row["sheet"] != sheet_id:
            continue
        key = row["ref"], str(row["pin"])
        require(key not in result, f"duplicate pin 예외 중복: {sheet_id}:{key}")
        result[key] = row
    return result


PIN_RECORD_FIELDS = {"number", "x", "y", "unit", "length_mm", "orientation_degrees", "name"}


def validate_pin_record(record, context):
    require(isinstance(record, dict) and set(record) == PIN_RECORD_FIELDS,
            f"pin record schema 불일치: {context}")
    require(isinstance(record["number"], str) and record["number"],
            f"pin number 누락/타입 불일치: {context}")
    require(isinstance(record["name"], str), f"pin name 타입 불일치: {context}")
    require(type(record["unit"]) is int and record["unit"] >= 1,
            f"pin unit 누락/타입 불일치: {context}")
    for field in ["x", "y", "length_mm", "orientation_degrees"]:
        require(type(record[field]) in {int, float} and math.isfinite(float(record[field])),
                f"pin {field} 누락/비유한/타입 불일치: {context}")
    require(float(record["length_mm"]) >= 0, f"pin length_mm 음수: {context}")


def verify_layout_component_inventory(contract, sheet_id, sheet):
    require(isinstance(sheet, dict), f"layout sheet 구조 불일치: {sheet_id}")
    for key in ["layout", "pins", "junctions", "orphans", "shorts"]:
        require(key in sheet, f"layout sheet 필수 필드 누락: {sheet_id}:{key}")
    layout = sheet["layout"]
    for key in ["component_count", "components", "bounds_resolved", "bounds_unresolved",
                "wire_count", "wires", "label_count", "labels"]:
        require(key in layout, f"layout 관측 필드 누락: {sheet_id}:{key}")
    require(isinstance(layout["components"], list)
            and isinstance(layout["bounds_unresolved"], list)
            and isinstance(layout["wires"], list) and isinstance(layout["labels"], list),
            f"layout 관측 list 구조 불일치: {sheet_id}")
    for key in ["component_count", "bounds_resolved", "wire_count", "label_count"]:
        require(type(layout[key]) is int and layout[key] >= 0,
                f"layout 관측 count 타입/범위 불일치: {sheet_id}:{key}")
    require(layout["component_count"] == len(layout["components"]),
            f"layout component_count-목록 불일치: {sheet_id}")
    require(layout["bounds_resolved"] + len(layout["bounds_unresolved"])
            == layout["component_count"],
            f"layout bounds 해석 개수-부품 개수 불일치: {sheet_id}")
    require(layout["wire_count"] == len(layout["wires"]),
            f"layout wire_count-목록 불일치: {sheet_id}")
    require(layout["label_count"] == len(layout["labels"]),
            f"layout label_count-목록 불일치: {sheet_id}")
    require(isinstance(sheet["junctions"], list), f"layout junctions 구조 불일치: {sheet_id}")
    for container, count_key, list_key in [(sheet["orphans"], "orphan_count", "orphans"),
                                           (sheet["shorts"], "short_count", "shorts")]:
        require(isinstance(container, dict) and count_key in container and list_key in container
                and isinstance(container[list_key], list),
                f"layout {count_key} 원 구조 누락: {sheet_id}")
        require(type(container[count_key]) is int and container[count_key] >= 0,
                f"layout {count_key} 타입/범위 불일치: {sheet_id}")
        require(container[count_key] == len(container[list_key]),
                f"layout {count_key}-목록 불일치: {sheet_id}")

    policy = contract["layout_component_policy"]
    require(policy.get("functional_inventory") == "exact_by_component_sheets"
            and isinstance(policy.get("auxiliary_rules"), list),
            "layout_component_policy 구조 불일치")
    expected_refs = {ref for ref, owner in contract["component_sheets"].items() if owner == sheet_id}
    semantic_units = contract["functional_units"]
    semantic_pin_units = contract["pin_units"]
    require(set(semantic_units) == set(contract["components"]),
            "semantic functional_units는 부품 전수를 명시해야 함")
    for ref, units in semantic_units.items():
        require(isinstance(units, list) and units and len(units) == len(set(units))
                and all(type(unit) is int and unit >= 1 for unit in units),
                f"semantic functional_units 구조 불일치: {ref}")
    functional_units = defaultdict(set)
    auxiliary_count = 0
    for row in layout["components"]:
        require(isinstance(row, dict) and all(key in row for key in ["reference", "unit", "lib_id"]),
                f"layout component 필수 필드 누락: {sheet_id}")
        require(type(row["unit"]) is int and row["unit"] >= 1,
                f"layout component unit 타입/범위 불일치: {sheet_id}:{row['reference']}")
        ref, unit, library = row["reference"], row["unit"], row["lib_id"]
        if ref in expected_refs:
            require(library == contract["components"][ref]["lib_id"],
                    f"layout component lib_id-semantic 불일치: {sheet_id}:{ref}")
            require(unit not in functional_units[ref], f"실제 동일 ref/unit 중복 배치: {(ref,unit)}")
            require(unit in set(semantic_units[ref]),
                    f"layout functional unit-semantic 불일치: {sheet_id}:{ref}:{unit}")
            functional_units[ref].add(unit)
            continue
        matches = [rule for rule in policy["auxiliary_rules"]
                   if re.fullmatch(rule["reference_regex"], ref)]
        require(len(matches) == 1, f"미등록 layout component: {sheet_id}:{ref}")
        rule = matches[0]
        require(library in rule["lib_ids"] and unit in {int(value) for value in rule["units"]},
                f"layout auxiliary 종류/unit 범위 불일치: {sheet_id}:{ref}:{library}:{unit}")
        auxiliary_count += 1
    require(set(functional_units) == expected_refs,
            f"functional layout component ref inventory 불일치: {sheet_id}:"
            f"missing={sorted(expected_refs-set(functional_units))}, "
            f"extra={sorted(set(functional_units)-expected_refs)}")

    require(isinstance(sheet["pins"], dict) and isinstance(sheet["pins"].get("components"), list),
            f"pins evidence components 누락/구조 불일치: {sheet_id}")
    pin_components = {}
    for component in sheet["pins"]["components"]:
        require(isinstance(component, dict)
                and all(key in component for key in ["reference", "unit_count", "units", "pins"])
                and isinstance(component["units"], list) and isinstance(component["pins"], list),
                f"pins evidence component 필수 필드 누락: {sheet_id}")
        ref = component["reference"]
        require(ref not in pin_components, f"pins evidence ref 중복: {sheet_id}:{ref}")
        units = []
        nested_records = []
        for unit_row in component["units"]:
            require(isinstance(unit_row, dict) and "unit" in unit_row and "pins" in unit_row
                    and isinstance(unit_row["pins"], list),
                    f"nested unit/pins 원 구조 누락: {sheet_id}:{ref}")
            unit_number = unit_row["unit"]
            require(type(unit_number) is int and unit_number >= 1,
                    f"nested unit 누락/타입 불일치: {sheet_id}:{ref}")
            units.append(unit_number)
            for index, pin in enumerate(unit_row["pins"]):
                validate_pin_record(pin, f"{sheet_id}:{ref}:nested:{unit_number}:{index}")
                require(pin["unit"] == unit_number,
                        f"nested pin unit-소유 unit 불일치: {sheet_id}:{ref}:{pin['number']}")
                pin_key = f"{ref}.{pin['number']}"
                require(pin_key in semantic_pin_units and pin["unit"] == semantic_pin_units[pin_key],
                        f"nested pin-semantic unit 소유 불일치: {sheet_id}:{pin_key}:"
                        f"{pin['unit']}!={semantic_pin_units.get(pin_key)}")
                nested_records.append(pin)
        top_records = component["pins"]
        require(top_records, f"pins evidence가 성공했지만 pin 0개: {sheet_id}:{ref}")
        for index, pin in enumerate(top_records):
            validate_pin_record(pin, f"{sheet_id}:{ref}:top:{index}")
            pin_key = f"{ref}.{pin['number']}"
            require(pin_key in semantic_pin_units and pin["unit"] == semantic_pin_units[pin_key],
                    f"top pin-semantic unit 소유 불일치: {sheet_id}:{pin_key}:"
                    f"{pin['unit']}!={semantic_pin_units.get(pin_key)}")
        require(type(component["unit_count"]) is int and component["unit_count"] >= 1,
                f"pins evidence unit_count 타입/범위 불일치: {sheet_id}:{ref}")
        require(len(units) == len(set(units)) == component["unit_count"],
                f"pins evidence unit_count/unit 집합 불일치: {sheet_id}:{ref}")
        require(Counter(canonical(pin) for pin in top_records)
                == Counter(canonical(pin) for pin in nested_records),
                f"top pin-nested unit pins multiset 불일치: {sheet_id}:{ref}")
        pin_components[ref] = set(units)
    require(set(pin_components) == expected_refs,
            f"pins evidence functional ref inventory 불일치: {sheet_id}")
    for ref in expected_refs:
        expected_units = set(semantic_units[ref])
        require(functional_units[ref] == expected_units,
                f"layout unit-semantic 집합 불일치: {sheet_id}:{ref}:"
                f"layout={sorted(functional_units[ref])},semantic={sorted(expected_units)}")
        require(pin_components[ref] == expected_units,
                f"pins evidence unit-semantic 집합 불일치: {sheet_id}:{ref}:"
                f"pins={sorted(pin_components[ref])},semantic={sorted(expected_units)}")
    return {"functional_refs": len(expected_refs), "functional_units": sum(map(len,functional_units.values())),
            "auxiliary_components": auxiliary_count}


def wire_graph(contract, sheet_id, sheet):
    layout = sheet["layout"]
    wires = [(point(row["x1"], row["y1"]), point(row["x2"], row["y2"]))
             for row in layout["wires"]]
    placements = [(row["reference"], row["unit"]) for row in layout["components"]]
    require(len(placements) == len(set(placements)), "실제 동일 ref/unit 중복 배치")
    records = defaultdict(list)
    for component in sheet["pins"]["components"]:
        for pin in component["pins"]:
            records[(component["reference"], str(pin["number"]))].append(pin)
    expected_duplicates = expected_duplicate_map(contract, sheet_id)
    actual_duplicates = set()
    pins = {}
    for key, rows in records.items():
        pins[key] = point(rows[0]["x"], rows[0]["y"])
        if len(rows) == 1:
            continue
        actual_duplicates.add(key)
        require(key in expected_duplicates, f"미등록 MCP pin 중복: {sheet_id}:{key}")
        expected = expected_duplicates[key]
        require(len(rows) == len(expected["lengths_mm"]), f"pin 중복 record 수 불일치: {key}")
        require(all(int(row.get("unit")) == int(expected["unit"]) for row in rows),
                f"pin 중복 unit 불일치: {key}")
        ignored = set(expected.get("same_fields_except", []))
        first = {name: value for name, value in rows[0].items() if name not in ignored}
        require(all({name: value for name, value in row.items() if name not in ignored} == first
                    for row in rows[1:]), f"다른 좌표/필드의 pin 중복: {key}")
        lengths = sorted(round(float(row["length_mm"]), 6) for row in rows)
        require(lengths == sorted(round(float(value), 6) for value in expected["lengths_mm"]),
                f"pin 중복 길이 쌍 불일치: {key}")
    require(actual_duplicates == set(expected_duplicates),
            f"duplicate pin baseline 범위 불일치: sheet={sheet_id}, "
            f"missing={sorted(set(expected_duplicates)-actual_duplicates)}, "
            f"extra={sorted(actual_duplicates-set(expected_duplicates))}")

    vertices = set(pins.values()) | {point(*xy) for xy in sheet["junctions"]}
    vertices |= {xy for wire in wires for xy in wire}
    parent = {xy: xy for xy in vertices}

    def find(xy):
        while parent[xy] != xy:
            parent[xy] = parent[parent[xy]]
            xy = parent[xy]
        return xy

    for wire in wires:
        require(wire[0][0] == wire[1][0] or wire[0][1] == wire[1][1], f"사선 배선: {wire}")
        # mid-mid 교차는 junction/endpoint vertex가 없으면 합치지 않는다.
        members = [xy for xy in vertices if on_segment(xy, wire)]
        require(members, f"배선 vertex 누락: {wire}")
        root = find(members[0])
        for member in members[1:]:
            parent[find(member)] = root

    def roots_at(xy):
        xy = point(*xy)
        roots = set()
        if xy in parent:
            roots.add(find(xy))
        for wire in wires:
            if on_segment(xy, wire):
                roots.add(find(wire[0]))
        return roots

    roots = {key: find(xy) for key, xy in pins.items()}
    return {"pins": pins, "roots": roots, "roots_at": roots_at,
            "duplicate_records": sum(len(rows)-1 for rows in records.values())}


def validate_wire_coverage(contract, all_pins):
    coverage = contract["wire_coverage"]
    require(isinstance(coverage, dict) and set(coverage) == {"groups", "exceptions"},
            "wire_coverage 구조 불일치")
    component_sheets = contract["component_sheets"]
    pin_to_net = {pin: net for net, members in contract["nets"].items() for pin in members}
    classified = {}
    for category in ["groups", "exceptions"]:
        for row in coverage[category]:
            require(row.get("pins") and row.get("sheet") and row.get("net"),
                    f"wire coverage {category} 필드 누락")
            if category == "exceptions":
                require(isinstance(row.get("reason"), str) and row["reason"].strip()
                        and isinstance(row.get("checks"), list) and row["checks"],
                        "wire exception은 구체 reason/checks가 필수")
            for pin in row["pins"]:
                require(pin in all_pins, f"wire coverage의 미등록 pin: {pin}")
                require(pin not in classified, f"wire coverage pin 중복 분류: {pin}")
                ref = pin.rsplit(".", 1)[0]
                require(component_sheets[ref] == row["sheet"], f"wire coverage sheet 불일치: {pin}")
                require(pin_to_net[pin] == row["net"], f"wire coverage net 불일치: {pin}")
                classified[pin] = category
    require(set(classified) == set(all_pins),
            f"wire coverage 전수 분류 불일치: missing={sorted(set(all_pins)-set(classified))[:30]}, "
            f"extra={sorted(set(classified)-set(all_pins))[:30]}")
    return coverage


def page_tags(sheet, label):
    tags = []
    for text in sheet.get("texts", []):
        x, y = text["at"][:2]
        if abs(float(x)-float(label["x"])) < .01 and abs(float(y)-float(label["y"])-3.175) < .01:
            tags.append(text["text"])
    return tags


def verify_ports(contract, layout, graphs, root_pins):
    ports = contract["ports"]
    require(isinstance(ports, dict) and ports.get("status") == "checked"
            and isinstance(ports.get("items"), list), "ports 명시 계약 누락/미완료")
    expected = {}
    for item in ports["items"]:
        key = item["sheet"], item["net"]
        require(key not in expected and int(item["expected_label_count"]) > 0,
                f"port 계약 중복/개수 오류: {key}")
        require(item["local_pins"], f"port local_pins 누락: {key}")
        for pin in item["local_pins"]:
            require(pin in contract["nets"][item["net"]], f"port local pin-net 불일치: {key}:{pin}")
            require(contract["component_sheets"][pin.rsplit('.',1)[0]] == item["sheet"],
                    f"port local pin-sheet 불일치: {key}:{pin}")
        expected[key] = item
    actual = defaultdict(list)
    for sheet_id, sheet in layout["sheets"].items():
        for label in sheet["layout"]["labels"]:
            if label.get("type") == "GlobalLabel":
                actual[sheet_id, label["net"]].append(label)
    require(set(actual) == set(expected),
            f"global port inventory 불일치: missing={sorted(set(expected)-set(actual))[:20]}, "
            f"extra={sorted(set(actual)-set(expected))[:20]}")
    checked_tags, missing_tags, attached = 0, 0, 0
    for key, item in expected.items():
        labels = actual[key]
        require(len(labels) == int(item["expected_label_count"]),
                f"global port label 개수 불일치: {key}:{len(labels)}")
        declared = {tuple(pin.rsplit(".", 1)) for pin in item["local_pins"]}
        attached_declared = set()
        for label in labels:
            roots = graphs[key[0]]["roots_at"]((label["x"], label["y"]))
            require(len(roots) == 1,
                    f"global port label 실선 root 접속 실패/모호: {key}@({label['x']},{label['y']})")
            pins = root_pins[key[0]].get(next(iter(roots)), set())
            local = pins & declared
            require(local, f"global port label이 명시 local_pins root에 접속되지 않음: {key}")
            attached_declared |= local
            attached += 1
            tags = page_tags(layout["sheets"][key[0]], label)
            require(len(tags) <= 1, f"port 상대 page 주석 중복: {key}")
            if tags:
                require(re.fullmatch(r"S[0-9/]+", tags[0]), f"port page 주석 형식 오류: {key}:{tags[0]}")
                stated = set(tags[0][1:].split("/"))
                require(stated and stated <= set(item["peer_sheets"]),
                        f"port page 주석-peer sheet 불일치: {key}:{tags[0]}")
                checked_tags += 1
            else:
                missing_tags += 1
        require(attached_declared == declared,
                f"port local_pins 중 label root에 대응하지 않는 pin: {key}:"
                f"{sorted(declared-attached_declared)}")
    return {"status": "checked", "labels": attached,
            "physical_attachment": "checked",
            "page_annotations": {"checked": checked_tags, "not_checked_missing": missing_tags}}


def verify_layout(contract, layout, xml_result):
    schema = layout.get("schema_version", layout.get("schema"))
    require(type(schema) is int and schema == 1,
            f"layout schema_version은 integer 1이어야 함: {schema}")
    expected_sheets = set(contract["sheet_sources"])
    require(set(layout.get("sheets", {})) == expected_sheets, "layout sheet 전수 범위 불일치")
    coverage = validate_wire_coverage(contract, xml_result["pin_keys"])
    expected_by_sheet = defaultdict(set)
    for key in contract["pin_types"]:
        expected_by_sheet[contract["component_sheets"][key.rsplit('.',1)[0]]].add(tuple(key.rsplit('.',1)))

    graphs, root_pins = {}, {}
    total_pins = duplicate_records = 0
    functional_refs = functional_units = auxiliary_components = 0
    policy = contract["layout"]
    for sheet_id, sheet in layout["sheets"].items():
        inventory = verify_layout_component_inventory(contract, sheet_id, sheet)
        functional_refs += inventory["functional_refs"]
        functional_units += inventory["functional_units"]
        auxiliary_components += inventory["auxiliary_components"]
        unresolved = sheet["layout"]["bounds_unresolved"]
        unresolved_count = len(unresolved)
        require(unresolved_count == int(policy["bounds_unresolved"]),
                f"layout bounds_unresolved 불일치: {sheet_id}")
        require(int(sheet["orphans"]["orphan_count"]) == int(policy["orphan_count"]),
                f"layout orphan 불일치: {sheet_id}")
        require(int(sheet["shorts"]["short_count"]) == int(policy["short_count"]),
                f"layout short 보고 불일치: {sheet_id}")
        graph = wire_graph(contract, sheet_id, sheet)
        require(set(graph["pins"]) == expected_by_sheet[sheet_id],
                f"layout pin 전수 범위 불일치: {sheet_id}")
        graphs[sheet_id] = graph
        by_root = defaultdict(set)
        for pin, root in graph["roots"].items():
            by_root[root].add(pin)
        root_pins[sheet_id] = by_root
        # 보고된 short_count가 아니라 실제 wire root의 XML net 혼합을 직접 거부한다.
        for root, pins in by_root.items():
            nets = {xml_result["pin_to_net"][f"{ref}.{pin}"] for ref, pin in pins}
            require(len(nets) == 1,
                    f"실제 wire root에 서로 다른 XML net pin 유입: {sheet_id}:"
                    f"nets={sorted(nets)}, pins={sorted(f'{r}.{p}' for r,p in pins)}")
        total_pins += len(graph["pins"])
        duplicate_records += graph["duplicate_records"]
    require(total_pins == len(xml_result["pin_keys"]), "XML-layout pin 전수 범위 불일치")

    for group in coverage["groups"]:
        roots = {graphs[group["sheet"]]["roots"][tuple(pin.rsplit('.',1))] for pin in group["pins"]}
        require(len(roots) == 1, f"실선 그룹 분리: {group['sheet']}:{group['net']}:{group['pins']}")
    ports = verify_ports(contract, layout, graphs, root_pins)
    return {"sheets": len(expected_sheets), "pins": total_pins,
            "functional_refs": functional_refs, "functional_units": functional_units,
            "auxiliary_components": auxiliary_components,
            "wire_groups": len(coverage["groups"]),
            "wire_exceptions": len(coverage["exceptions"]),
            "wire_coverage": "complete_exact_once",
            "cross_net_wire_roots": 0,
            "duplicate_pin_records_allowed_by_exact_baseline": duplicate_records,
            "ports": ports}


def violation_identity(sheet, violation):
    require(violation.get("severity") in {"error", "warning", "exclusion"},
            f"ERC severity 구조 불일치: {violation}")
    require(isinstance(violation.get("type"), str) and violation["type"], "ERC type 누락")
    require(isinstance(violation.get("description"), str) and violation["description"],
            "ERC description 누락")
    require("items" in violation and isinstance(violation["items"], list),
            "ERC items 원 구조 누락/불일치")
    descriptions = []
    for item in violation["items"]:
        require(isinstance(item, dict) and isinstance(item.get("description"), str),
                "ERC item description 누락")
        descriptions.append(item["description"])
    return {"sheet": sheet, "severity": violation["severity"], "type": violation["type"],
            "description": violation["description"], "items": sorted(descriptions)}


def verify_erc(contract, erc, layout):
    policy = contract["erc"]
    require(isinstance(policy.get("policy"), dict), "ERC policy 사전 계약 누락")
    require(isinstance(erc.get("sheets"), list), "ERC sheets 구조 불일치")
    expected_paths = policy.get("sheet_paths")
    require(isinstance(expected_paths, list) and expected_paths
            and len(expected_paths) == len(set(expected_paths)),
            "ERC semantic sheet_paths 누락/중복")
    actual_paths = []
    identities = []
    for sheet in erc["sheets"]:
        require(isinstance(sheet, dict) and isinstance(sheet.get("path"), str) and sheet["path"],
                "ERC sheet path 누락")
        require("violations" in sheet and isinstance(sheet["violations"], list),
                f"ERC violations 원 구조 누락: {sheet['path']}")
        actual_paths.append(sheet["path"])
        identities.extend(violation_identity(sheet["path"], row) for row in sheet["violations"])
    require(len(actual_paths) == len(set(actual_paths)), "ERC sheet path 중복")
    require(actual_paths == expected_paths,
            f"ERC sheet path 전수/순서 불일치: missing={sorted(set(expected_paths)-set(actual_paths))}, "
            f"extra={sorted(set(actual_paths)-set(expected_paths))}")
    counts = Counter(item["severity"] for item in identities)
    actual = {"errors": counts["error"], "warnings": counts["warning"],
              "exclusions": counts["exclusion"]}
    require(actual == {key: int(policy[key]) for key in actual},
            f"ERC error/warning/exclusion 개수 불일치: {actual}")
    warnings = [item for item in identities if item["severity"] == "warning"]
    exclusions = [item for item in identities if item["severity"] == "exclusion"]
    require(sorted(map(canonical, warnings)) == sorted(map(canonical, policy["warning_allowlist"])),
            "ERC warning type/항목 identity 불일치")
    require(sorted(map(canonical, exclusions)) == sorted(map(canonical, policy["exclusion_allowlist"])),
            "ERC exclusion identity 불일치")
    source = erc if "ignored_checks" in erc and "included_severities" in erc else layout.get("erc_policy")
    require(isinstance(source, dict), "ERC disabled/exclusion policy 증거 미수신")
    require("included_severities" in source and isinstance(source["included_severities"], list)
            and "ignored_checks" in source and isinstance(source["ignored_checks"], list),
            "ERC policy 원 필드 누락")
    observed_policy = {"included_severities": sorted(source["included_severities"]),
                       "ignored_checks": sorted(source["ignored_checks"], key=lambda row: row["key"])}
    expected_policy = {"included_severities": sorted(policy["policy"]["included_severities"]),
                       "ignored_checks": sorted(policy["policy"]["ignored_checks"], key=lambda row: row["key"])}
    require(observed_policy == expected_policy, "ERC 비활성/포함 severity policy 불일치")
    return {
        **actual,
        "warning_identities": len(warnings),
        "policy": "checked_exact_included_severities_ignored_checks_and_identities",
        "source_class": "sha_bound_erc_json; native producer provenance not independently checked",
        "all_erc_checks_claimed": False,
        "coverage_limit": (
            "입력 JSON의 included_severities·ignored_checks·violation identity만 검사; "
            "모든 전기 규칙·도구 지원 범위·PCB 거리·전류 정격을 검사하지 않음"
        ),
    }


def resolve_pdf_tool(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        require(candidate.is_absolute(), "PDF text tool의 path 표기는 absolute여야 함")
        path = candidate
    else:
        found = shutil.which(raw)
        require(found is not None, f"PDF text tool을 PATH에서 찾지 못함: {raw}")
        path = Path(found)
    require(path.is_file() and os.access(path, os.X_OK),
            f"PDF text tool 실행 파일 누락/비실행: {path}")
    return path.resolve()


def probe_pdf_tool(tool: Path):
    # Poppler pdftotext의 정식 version 옵션은 ``-v``다.
    argv = [str(tool), "-v"]
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"PDF text tool version 확인 실패: {exc}") from exc
    require(completed.returncode == 0,
            f"PDF text tool version 확인 rc 실패: {completed.returncode}")
    return {
        "version_argv": argv,
        "version_rc": completed.returncode,
        "version_output": (completed.stdout + completed.stderr).strip()[-2000:],
    }


def _element_text(element):
    return "".join(element.itertext()).strip()


def verify_pdf(contract, path: Path, tool: Path):
    policy = contract["pdf"]
    argv = [str(tool), "-bbox-layout", "-enc", "UTF-8", str(path), "-"]
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"PDF text 검사가 unknown 상태로 실패: {exc}") from exc
    require(completed.returncode == 0,
            f"PDF text 검사가 unknown 상태로 실패: rc={completed.returncode}, "
            f"stderr={completed.stderr[-1000:]}")
    try:
        document = ET.fromstring(completed.stdout)
    except ET.ParseError as exc:
        raise VerificationError(f"PDF bbox XML 해석 실패로 검사 unknown: {exc}") from exc
    page_nodes = document.findall(".//{*}page")
    require(len(page_nodes) == int(policy["page_count"]),
            f"PDF page count 불일치: {len(page_nodes)}")
    required_text = policy["required_text"]
    require(isinstance(required_text, dict)
            and set(required_text) == {str(index) for index in range(1, len(page_nodes)+1)},
            "PDF required_text는 모든 page를 명시해야 함")
    expected_width, expected_height = map(float, policy["page_size_mm"])
    tolerance = float(policy.get("page_size_tolerance_mm", .2))
    frame = policy.get("text_bounds_mm")
    ignore = re.compile(policy.get("bounds_ignore_regex", r"$^"))
    missing_markers = policy.get("missing_glyph_markers", ["�"])
    pages, mm = [], 25.4/72
    for index, page in enumerate(page_nodes, 1):
        try:
            width, height = float(page.attrib["width"])*mm, float(page.attrib["height"])*mm
        except (KeyError, ValueError) as exc:
            raise VerificationError(f"PDF page bbox 크기 누락/타입 불일치: {index}") from exc
        require(math.isfinite(width) and math.isfinite(height),
                f"PDF page bbox 크기 비유한: {index}")
        require(abs(width-expected_width) <= tolerance and abs(height-expected_height) <= tolerance,
                f"PDF page size 불일치: {index}:{width:.3f}x{height:.3f}mm")
        word_nodes = page.findall(".//{*}word")
        line_nodes = page.findall(".//{*}line")
        words = [_element_text(word) for word in word_nodes if _element_text(word)]
        lines = []
        for line in line_nodes:
            members = [_element_text(word) for word in line.findall(".//{*}word")]
            normalized = " ".join(member for member in members if member)
            if normalized:
                lines.append(normalized)
        exact_text = set(words) | set(lines)
        require(isinstance(required_text[str(index)], list)
                and all(isinstance(item, str) and item for item in required_text[str(index)]),
                f"PDF required_text page 항목 구조 불일치: {index}")
        for expected in required_text[str(index)]:
            require(expected in exact_text,
                    f"PDF 필수 문자 누락(word/line exact): page={index}, text={expected}")
        joined = "\n".join(lines)
        candidates = [marker for marker in missing_markers
                      if isinstance(marker, str) and marker and marker in joined]
        require(not candidates, f"PDF 누락 문자 후보: page={index}, markers={candidates}")
        out = []
        if frame is not None:
            require(isinstance(frame, list) and len(frame) == 4,
                    "PDF text_bounds_mm 구조 불일치")
            left, top, right, bottom = map(float, frame)
            for word in word_nodes:
                label = _element_text(word)
                if not label or ignore.fullmatch(label):
                    continue
                try:
                    box = [float(word.attrib[key])*mm
                           for key in ["xMin", "yMin", "xMax", "yMax"]]
                except (KeyError, ValueError) as exc:
                    raise VerificationError(
                        f"PDF word bbox 누락/타입 불일치: page={index}, text={label}") from exc
                require(all(math.isfinite(value) for value in box),
                        f"PDF word bbox 비유한: page={index}, text={label}")
                if box[0] < left or box[1] < top or box[2] > right or box[3] > bottom:
                    out.append({"text": label, "bbox_mm": box})
        require(not out, f"PDF 문자 유효영역 이탈: page={index}, count={len(out)}")
        pages.append({"page": index, "width_mm": width, "height_mm": height,
                      "word_count": len(words), "line_count": len(lines),
                      "required_text": len(required_text[str(index)]),
                      "missing_glyph_candidates": [], "out_of_bounds": []})
    return {
        "pages": pages,
        "text_matching": "exact_normalized_word_or_line",
        "scope": "Poppler text layer의 page 크기·필수 word/line·word 경계·누락 문자 후보만 검사",
        "argv": argv,
        "rc": completed.returncode,
        "stderr": completed.stderr[-2000:],
    }


def verify_companions(contract, runtime, source_files, project_root: Path):
    required = contract["required_companions"]
    require(isinstance(required, dict), "required_companions는 빈 경우도 dict로 명시해야 함")
    received = runtime["companion_receipts"]
    require(set(received) == set(required),
            f"필수 companion receipt 범위 불일치: missing={sorted(set(required)-set(received))}, "
            f"extra={sorted(set(received)-set(required))}")
    if not required:
        return {"status": "not_applicable_explicit_empty", "checked": []}
    checked = []
    for name, spec in required.items():
        ref = received[name]
        require(set(ref) == {"path", "sha256"}, f"companion receipt ref 구조 불일치: {name}")
        path = safe_project_path(project_root, ref["path"], label=f"companion receipt {name}")
        require(path.is_file() and digest(path) == ref["sha256"], f"companion receipt SHA 불일치: {name}")
        receipt = load_json(path)
        require(type(receipt.get("schema_version")) is int
                and receipt.get("schema_version") == 1,
                f"companion receipt schema_version은 integer 1이어야 함: {name}")
        require(receipt.get("name") == name, f"companion receipt 정체성 불일치: {name}")
        require(type(receipt.get("rc")) is int and receipt.get("rc") == 0,
                f"companion 원 rc 타입/실패: {name}:{receipt.get('rc')}")
        require(receipt.get("argv") == spec["argv"], f"companion argv 불일치: {name}")
        require(receipt.get("verifier") == spec["verifier"], f"companion verifier receipt 불일치: {name}")
        verifier_path = safe_project_path(
            project_root, spec["verifier"]["path"], label=f"companion verifier {name}")
        require(verifier_path.is_file() and digest(verifier_path) == spec["verifier"]["sha256"],
                f"companion verifier SHA 불일치: {name}")
        expected_inputs = {
            item: digest(safe_project_path(project_root, item, label=f"companion input {name}"))
            for item in spec["input_paths"]
        }
        require(receipt.get("inputs") == expected_inputs, f"companion input SHA 불일치: {name}")
        require(receipt.get("current_cad_source_files") == source_files,
                f"companion current CAD SHA 불일치: {name}")
        for field in ["log", "report"]:
            record = receipt.get(field)
            expected_path = spec[f"{field}_path"]
            require(isinstance(record, dict) and record.get("path") == expected_path,
                    f"companion {field} path 불일치: {name}")
            target = safe_project_path(
                project_root, expected_path, label=f"companion {field} {name}")
            require(target.is_file() and digest(target) == record.get("sha256"),
                    f"companion {field} SHA 불일치: {name}")
            require(target.stat().st_size > 0, f"companion {field} 빈 증거: {name}")
        checked.append(name)
    return {"status": "checked", "checked": checked}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--erc", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pdf-text-tool", default="pdftotext")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    try:
        project_root = validate_project_root(args.project_root)
    except VerificationError as exc:
        print("[FAIL]", str(exc))
        return 2
    try:
        report_path = safe_project_path(
            project_root, args.report, label="report", must_exist=False, output_new=True)
    except VerificationError as exc:
        print("[FAIL]", str(exc))
        return 2
    package_start = {}
    package_capture_error = ""
    try:
        package_start = package_identity.capture()
    except (OSError, ValueError) as exc:
        package_capture_error = f"package identity 시작 캡처 실패: {exc}"
    report = {
        "schema_version": 2, "status": "FAIL", "at": datetime.now().astimezone().isoformat(),
        "argv": [sys.executable, str(Path(__file__).resolve()), *raw_argv],
        "verifier_sha256": digest(Path(__file__)),
        "project_root": str(project_root),
        "runtime": {"python": platform.python_version(), "pdf_text_backend": "Poppler pdftotext"},
        "registry_selection": {
            "mode": "explicit_pair_unverified",
            "requested_path": str(args.registry),
            "selected_path": None, "actual_sha256": None,
            "expected_sha256": args.registry_sha256,
            "phase_root_trust_binding": "not_checked_by_common_verifier",
        },
        "pdf_tool": {
            "requested": args.pdf_text_tool,
            "status": "unknown_until_checked",
            "argv": [],
        },
        "package_identity": {"status": "start_failed" if package_capture_error else "started",
                             **({"start": package_start} if package_start else {})},
        "scope": {"deterministic_static_contract": "checked_on_success",
                  "visual_review": "not_checked", "dynamic_operation": "not_checked",
                  "glyph_completeness": "not_checked",
                  "all_pages_manual_review": "not_checked",
                  "electrical_performance": "not_checked",
                  "all_erc_rules": "not_claimed",
                  "schematic_position_as_pcb_distance": "not_checked_not_equivalent",
                  "voltage_current_rating_and_sequencing": "not_checked",
                  "pcb_manufacturing_energization_physical_safety": "not_checked",
                  "port_direction_and_return_semantics": "not_checked",
                  "project_semantic_logic": "checked_only_by_bound_companion_receipts"},
        "errors": [],
    }
    try:
        require(not package_capture_error, package_capture_error)
        paths = {
            name: safe_project_path(project_root, getattr(args, name), label=name)
            for name in ["contract", "netlist", "layout", "erc", "pdf"]
        }
        registry_path = select_registry_path(
            project_root, args.registry, args.registry_sha256)
        report["registry_selection"]["selected_path"] = str(registry_path.relative_to(project_root))
        report["registry_selection"]["actual_sha256"] = digest(registry_path)
        runtime, contract, seal = load_sealed_contract(
            paths["contract"], registry_path, project_root, args.registry_sha256)
        producer_package = runtime["producer_package_identity"]
        report["package_identity"]["producer"] = producer_package
        require(package_identity.strict_equal(producer_package, package_start),
                "runtime producer package identity가 현재 검증기 패키지와 불일치")
        report["plan_binding"] = verify_producer_plan_binding(runtime, project_root)
        report["contract_scope_limits"] = contract["scope_limits"]
        validate_contract_scope_limits(contract["scope_limits"])
        report["registry_selection"]["actual_sha256"] = seal["registry_sha256"]
        report["registry_selection"]["mode"] = "explicit_sha256_pinned"
        layout, erc = load_json(paths["layout"]), load_json(paths["erc"])
        report["profile_id"] = contract["profile_id"]
        report["hashes"] = verify_hashes(
            runtime, contract, paths, layout, seal, project_root)
        xml_result = verify_xml(contract, paths["netlist"], project_root)
        report["xml"] = {
            key: xml_result[key] for key in ["components", "pins", "nets", "source"]
        }
        report["layout"] = verify_layout(contract, layout, xml_result)
        report["scope"]["port_physical_attachment"] = "checked"
        missing_page_tags = report["layout"]["ports"]["page_annotations"]["not_checked_missing"]
        report["scope"]["port_page_annotations"] = (
            "checked" if missing_page_tags == 0 else f"partially_checked_missing_{missing_page_tags}")
        report["erc"] = verify_erc(contract, erc, layout)
        pdf_tool = resolve_pdf_tool(args.pdf_text_tool)
        report["pdf_tool"].update(probe_pdf_tool(pdf_tool))
        report["pdf_tool"].update({"status": "available", "resolved": str(pdf_tool)})
        report["pdf"] = verify_pdf(contract, paths["pdf"], pdf_tool)
        report["pdf_tool"]["argv"] = report["pdf"]["argv"]
        report["pdf_tool"]["rc"] = report["pdf"]["rc"]
        report["companions"] = verify_companions(
            contract, runtime, layout_source_files(layout), project_root)
        if report["companions"]["status"] == "checked":
            report["scope"]["project_semantic_logic"] = "checked_by_bound_companion_receipts"
        else:
            report["scope"]["project_semantic_logic"] = "not_applicable_explicit_empty"
        report["status"] = "PASS"
        report["scope"]["deterministic_static_contract"] = "checked"
    except (VerificationError, OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        report["errors"].append(str(exc))
        report["status"] = "FAIL"
    if package_start:
        try:
            package_end = package_identity.assert_unchanged(package_start)
            report["package_identity"].update(
                {"status": "unchanged", "end": package_end, "unchanged": True})
        except (OSError, ValueError) as exc:
            report["status"] = "FAIL"
            report["package_identity"].update({"status": "changed", "unchanged": False})
            report["errors"].append(f"package identity 종료 대조 실패: {exc}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if report["status"] == "PASS":
        print("[PASS] sealed semantic XML·실선·port·ERC·PDF·companion 계약 통과")
        print("범위: deterministic 정적 계약. 시각·동적·PCB·제조·통전·실물 안전 합격이 아님.")
        return 0
    print("[FAIL]", report["errors"][0] if report["errors"] else "알 수 없는 오류")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
