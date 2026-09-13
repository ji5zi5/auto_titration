import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/hik_whole_apk/g002_method_a.py"
SPEC = importlib.util.spec_from_file_location("g002_method_a_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
METHOD_A = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = METHOD_A
SPEC.loader.exec_module(METHOD_A)


class G002MethodARegressionTests(unittest.TestCase):
    def test_candidate_output_is_complete_public_v10_root(self) -> None:
        self.assertEqual(
            METHOD_A.DEFAULT_OUTPUT,
            Path(
                ".omx/research/hikmicro-viewer-2.6.0/static/"
                "g002-method-a-v10"
            ),
        )
        self.assertEqual(
            METHOD_A.CANDIDATE_DOCUMENT_PATHS,
            (
                "bundle.json",
                "inventory.json",
                "source-index.json",
                "run.json",
                "command.json",
                "review.json",
                "raw/xapk.json",
                "raw/apk-entries.json",
                "raw/manifests.json",
                "raw/resources.json",
                "raw/signing.json",
                "raw/dex.json",
                "raw/elf.json",
                "raw/jni.json",
            ),
        )

    def test_candidate_schema_constants_are_public_shapes(self) -> None:
        self.assertEqual(METHOD_A.CANDIDATE_BUNDLE_SCHEMA, "g002-candidate-bundle/v2")
        self.assertEqual(METHOD_A.INVENTORY_SCHEMA, "g002-normalized-inventory/v2")
        self.assertEqual(METHOD_A.RAW_ATTACHMENT_SCHEMA, "g002-raw-attachment/v1")
        self.assertEqual(METHOD_A.SOURCE_INDEX_SCHEMA, "g002-source-index/v2")
        self.assertEqual(METHOD_A.CANDIDATE_SCOPE, "whole_inventory")
        self.assertNotIn("raw/coverage.json", METHOD_A.CANDIDATE_DOCUMENT_PATHS)

    def test_parser_exposes_contract_and_candidate_root(self) -> None:
        args = METHOD_A._parser().parse_args(
            [
                "--contract",
                "contract.json",
                "--candidate-root",
                "candidate",
            ]
        )
        self.assertEqual(args.contract, "contract.json")
        self.assertEqual(args.candidate_root, "candidate")

    def test_dynsym_parser_keeps_unnamed_nonzero_entry_and_hex_size(self) -> None:
        sample = """
Symbol table '.dynsym' contains 3 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND
     1: 0000000000000010 0x186a0 FUNC    GLOBAL DEFAULT   12 exported
     2: 0000000000000020     0 SECTION LOCAL  DEFAULT   13
"""
        declared, included, excluded = METHOD_A._parse_readelf_symbols(sample)
        self.assertEqual(declared, 3)
        self.assertEqual([row["dynsym_index"] for row in included], [1, 2])
        self.assertEqual(included[0]["size_bytes"], 100000)
        self.assertIsNone(included[1]["name"])
        self.assertEqual([row["reason"] for row in excluded], ["reserved-index-zero"])

    def test_manifest_payload_carries_immediate_parent_record_id(self) -> None:
        collector = METHOD_A.RecordCollector()
        collector.add(
            "frozen_artifact",
            "apk:test",
            dataset="xapk",
            artifact_id="apk:test",
            source_artifact_id="apk:test",
            sha256="0" * 64,
            size_bytes=1,
            official_source={"type": "file", "path": "test.apk"},
        )
        collector.add(
            "configuration",
            {
                "configuration_kind": "apk_archive_entry",
                "container_artifact_id": "apk:test",
                "central_directory_ordinal": 0,
                "path": "AndroidManifest.xml",
                "compression_method": 0,
                "crc32": 0,
                "compressed_size_bytes": 1,
                "uncompressed_size_bytes": 1,
                "sha256": "1" * 64,
            },
            dataset="apk_entries",
            artifact_id=None,
            source_artifact_id="apk:test",
            sha256="1" * 64,
            size_bytes=1,
            official_source=None,
            parent_record_ids=[METHOD_A._record_id("frozen_artifact", "apk:test")],
        )
        METHOD_A._add_manifest_records(
            collector,
            axml={
                "nodes": [
                    {
                        "event_ordinal": 0,
                        "name": "manifest",
                        "qname": "Q{}manifest",
                        "path": "axmlpath:/Q{}manifest[1]",
                        "attributes": [],
                    },
                    {
                        "event_ordinal": 1,
                        "name": "application",
                        "qname": "Q{}application",
                        "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]",
                        "attributes": [],
                    },
                ],
                "features": [],
                "components": [],
            },
            apk_artifact_id="apk:test",
        )
        nodes = [
            record
            for record in collector.records
            if record["record_type"] == "manifest_node"
        ]
        self.assertEqual(len(nodes), 2)
        payloads = [json.loads(record["scope_key"]) for record in nodes]
        root_index = next(
            index
            for index, payload in enumerate(payloads)
            if payload["xpath"] == "axmlpath:/Q{}manifest[1]"
        )
        child_index = 1 - root_index
        self.assertIsNone(payloads[root_index]["parent_manifest_node_record_id"])
        self.assertEqual(
            payloads[child_index]["parent_manifest_node_record_id"],
            nodes[root_index]["record_id"],
        )

    def test_raw_facts_and_source_rows_are_reordered_in_place_by_fact_id(self) -> None:
        first = "FCT-" + "1" * 64
        second = "FCT-" + "2" * 64
        document = {
            "facts": [
                {"fact_id": second, "source_row_index": 0},
                {"fact_id": first, "source_row_index": 1},
            ],
            "source_rows": [
                {"source_locator": "raw/test.json#/facts/1"},
                {"source_locator": "raw/test.json#/facts/0"},
            ],
        }
        facts_object = document["facts"]
        rows_object = document["source_rows"]
        METHOD_A._order_normalized_facts_in_place(document)
        self.assertIs(document["facts"], facts_object)
        self.assertIs(document["source_rows"], rows_object)
        self.assertEqual([row["fact_id"] for row in document["facts"]], [first, second])
        self.assertEqual(
            [row["source_row_index"] for row in document["facts"]],
            [0, 1],
        )
        self.assertEqual(
            [row["source_locator"] for row in document["source_rows"]],
            ["raw/test.json#/facts/0", "raw/test.json#/facts/1"],
        )

    def test_raw_provenance_uses_source_rows_and_source_index_rows(self) -> None:
        payload = "official-xapk"
        record = {
            "record_id": METHOD_A._record_id("frozen_artifact", payload),
            "record_type": "frozen_artifact",
            "scope_key": METHOD_A._canonical_text(payload),
            "payload": payload,
            "artifact_id": payload,
            "source_artifact_id": payload,
            "sha256": "0" * 64,
            "size_bytes": 1,
            "official_source": {"type": "file", "path": "x.xapk"},
            "dossier_id": None,
            "classification_status": "classified",
            "parent_record_ids": [],
        }
        source_index, raw_documents = METHOD_A._build_raw_provenance(
            [record],
            {},
            artifact_set_id="artifact-set:test",
            artifacts_by_id={
                payload: {
                    "artifact_id": payload,
                    "sha256": "0" * 64,
                    "size_bytes": 1,
                    "source": {"type": "file", "path": "x.xapk"},
                }
            },
            include_official_obligations=False,
        )
        self.assertEqual(source_index["schema_version"], "g002-source-index/v2")
        self.assertIn("rows", source_index)
        self.assertNotIn("records", source_index)
        xapk = raw_documents["raw/xapk.json"]
        self.assertEqual(xapk["schema_version"], "g002-raw-attachment/v1")
        self.assertIn("facts", xapk)
        self.assertIn("source_rows", xapk)
        self.assertNotIn("records", xapk)
        self.assertEqual(xapk["facts"][0]["source_row_index"], 0)
        self.assertEqual(
            xapk["source_rows"][0]["source_locator"],
            "raw/xapk.json#/source_rows/0",
        )

    def test_public_v10_official_obligation_rows_are_support_facts_without_source_rows(self) -> None:
        artifact_id = "official-xapk"
        artifact = {
            "artifact_id": artifact_id,
            "sha256": "0" * 64,
            "size_bytes": 1,
            "source": {"type": "file", "path": "x.xapk"},
        }
        byte_range = {
            "artifact_id": artifact_id,
            "offset_bytes": 0,
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
        }
        root_primitive = {
            "primitive_kind": "artifact.bytes",
            "origin": "artifact",
            "input_artifact_ids": [artifact_id],
            "physical_key": [artifact_id],
            "byte_ranges": [byte_range],
            "dependency_primitive_ids": [],
        }
        root_id = METHOD_A._primitive_id("xapk", root_primitive)
        path = "raw/xapk.json"
        digest = "1" * 64
        primitive_kind = (
            METHOD_A.RAW_NORMALIZED_PRIMITIVE_KIND[path].rsplit(".", 1)[0]
            + ".official_obligation"
        )
        expected_primitive = {
            "primitive_kind": primitive_kind,
            "origin": "derived",
            "input_artifact_ids": [artifact_id],
            "physical_key": [path, digest],
            "byte_ranges": [],
            "dependency_primitive_ids": [root_id],
        }
        expected_primitive_id = METHOD_A._primitive_id("xapk", expected_primitive)
        expected_fact_id = "FCT-" + METHOD_A._sha256_bytes(
            METHOD_A._canonical_bytes(["g002-obligation-fact/v1", path, digest])
        ).upper()
        documents = {
            attachment_path: {
                "schema_version": METHOD_A.RAW_ATTACHMENT_SCHEMA,
                "attachment_kind": kind,
                "artifact_set_id": "artifact-set:test",
                "input_artifact_ids": [artifact_id] if attachment_path == path else [],
                "primitives": [],
                "decisions": [],
                "facts": [],
                "source_rows": [],
                "scope_summaries": [],
            }
            for attachment_path, kind in METHOD_A.EXPECTED_ATTACHMENT_KINDS.items()
        }
        old_digests = METHOD_A.OFFICIAL_OBLIGATION_DIGESTS
        old_ids = METHOD_A.OFFICIAL_OBLIGATION_IDS
        try:
            METHOD_A.OFFICIAL_OBLIGATION_DIGESTS = {path: digest}
            METHOD_A.OFFICIAL_OBLIGATION_IDS = {
                path: (expected_primitive_id, expected_fact_id)
            }
            METHOD_A._append_official_obligation_rows(
                {path: documents[path]},
                {artifact_id: root_id},
            )
        finally:
            METHOD_A.OFFICIAL_OBLIGATION_DIGESTS = old_digests
            METHOD_A.OFFICIAL_OBLIGATION_IDS = old_ids

        self.assertEqual(len(documents[path]["source_rows"]), 0)
        self.assertEqual(documents[path]["primitives"][0]["primitive_id"], expected_primitive_id)
        self.assertEqual(
            documents[path]["decisions"][0],
            {
                "primitive_id": expected_primitive_id,
                "disposition": "support",
                "fact_ids": [expected_fact_id],
                "reason_code": None,
            },
        )
        self.assertEqual(
            documents[path]["facts"][0],
            {
                "fact_id": expected_fact_id,
                "fact_kind": "validation",
                "record_id": None,
                "record_type": None,
                "scope_key": None,
                "validation_code": f"official_obligation:{digest}",
                "dependency_primitive_ids": [expected_primitive_id],
                "source_row_index": None,
            },
        )

    def test_orphan_java_export_has_source_library_and_selected_native_export_parents(self) -> None:
        library_artifact_id = "extracted-native:lib/arm64-v8a/libsample.so"
        library_parent = METHOD_A._record_id("frozen_artifact", library_artifact_id)
        collector = METHOD_A.RecordCollector()
        collector.add(
            "frozen_artifact",
            library_artifact_id,
            dataset="elf",
            artifact_id=library_artifact_id,
            source_artifact_id=library_artifact_id,
            sha256="2" * 64,
            size_bytes=7,
            official_source={"type": "file", "path": "libsample.so"},
        )
        symbol_payload = {
            "library_artifact_id": library_artifact_id,
            "dynamic_symbol_index": 3,
            "name": "Java_com_example_Unmatched_nativeCall",
            "version": None,
            "type": "STT_FUNC",
            "binding": "STB_GLOBAL",
            "visibility": "STV_DEFAULT",
            "section_index": 1,
            "value": 4096,
            "size_bytes": 24,
        }
        symbol_record_id = collector.add(
            "native_symbol",
            symbol_payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent],
        )
        native_export_payload = {
            "native_symbol_record_id": symbol_record_id,
            "library_artifact_id": library_artifact_id,
            "dynamic_symbol_index": 3,
            "name": "Java_com_example_Unmatched_nativeCall",
            "version": None,
            "binding": "STB_GLOBAL",
        }
        native_export_record_id = collector.add(
            "native_export",
            native_export_payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent, symbol_record_id],
        )
        inputs = METHOD_A.Inputs(
            repo_root=Path("."),
            xapk=Path("fixture.xapk"),
            official_manifest_path=Path("official-artifacts.json"),
            official_manifest={},
            artifacts=(),
            artifacts_by_id={
                library_artifact_id: {
                    "artifact_id": library_artifact_id,
                    "kind": "native_library",
                    "sha256": "2" * 64,
                    "size_bytes": 7,
                    "source": {"type": "file", "path": "libsample.so"},
                },
            },
            artifact_set_id="artifact-set:test",
            base_member="base.apk",
            apk_member_artifact_by_path={},
            xapk_member_artifact_by_path={},
            base_entry_artifact_by_path={},
        )
        METHOD_A._add_jni_edges(
            collector,
            inputs=inputs,
            native_methods=(),
            native_exports=[
                {
                    "library_artifact_id": library_artifact_id,
                    "dynamic_symbol_index": 3,
                    "name": "Java_com_example_Unmatched_nativeCall",
                    "version": None,
                    "native_symbol_record_id": symbol_record_id,
                    "native_export_record_id": native_export_record_id,
                    "virtual_address": 4096,
                }
            ],
        )

        records, _ = collector.finalize()
        orphan_edges = [
            record
            for record in records
            if record["record_type"] == "jni_edge"
            and record["payload"]["binding_form"] == "orphan_java_export"
        ]
        self.assertEqual(len(orphan_edges), 1)
        self.assertEqual(
            orphan_edges[0]["parent_record_ids"],
            sorted([library_parent, native_export_record_id]),
        )
        self.assertEqual(len(set(orphan_edges[0]["parent_record_ids"])), 2)

    def test_canonical_writer_emits_compact_json_with_one_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "value.json"
            METHOD_A._write_json(path, {"b": 1, "a": "é"}, pretty=False)
            self.assertEqual(path.read_bytes(), b'{"a":"\xc3\xa9","b":1}\n')

    def test_producer_does_not_reference_public_validator_module(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("g002_neutral_validator", source)
        self.assertNotIn("validate_official_anchors", source)


class _FakeInstruction:
    def __init__(self, name, operands):
        self._name = name
        self._operands = operands

    def get_name(self):
        return self._name

    def get_operands(self):
        return [(None, None, value) for value in self._operands]


class _FakeMethod:
    def __init__(self, name, descriptor, access_flags=0, instructions=()):
        self._name = name
        self._descriptor = descriptor
        self._access_flags = access_flags
        self._instructions = tuple(instructions)

    def get_name(self):
        return self._name

    def get_descriptor(self):
        return self._descriptor

    def get_access_flags(self):
        return self._access_flags

    def get_code(self):
        return object() if self._instructions else None

    def get_instructions_idx(self):
        return iter(self._instructions)


class _FakeClass:
    def __init__(self, methods):
        self._methods = tuple(methods)

    def get_name(self):
        return "Lcom/example/Caller;"

    def get_access_flags(self):
        return 1

    def get_superclassname(self):
        return "Ljava/lang/Object;"

    def get_interfaces(self):
        return ()

    def get_methods(self):
        return self._methods


def _dex_class_with_methods(methods):
    class FakeDex:
        def __init__(self, _data):
            pass

        def get_classes(self):
            return [_FakeClass(methods)]

    return FakeDex


def _collector_with_frozen_artifact(artifact_id, *, dataset="dex", kind="dex"):
    collector = METHOD_A.RecordCollector()
    collector.add(
        "frozen_artifact",
        artifact_id,
        dataset=dataset,
        artifact_id=artifact_id,
        source_artifact_id=artifact_id,
        sha256="a" * 64,
        size_bytes=1,
        official_source={"type": "file", "path": artifact_id},
    )
    artifact = {
        "artifact_id": artifact_id,
        "kind": kind,
        "sha256": "a" * 64,
        "size_bytes": 1,
        "source": {"type": "file", "path": artifact_id},
    }
    return collector, artifact


def _utf8_string_pool(strings):
    encoded = []
    offsets = []
    position = 0
    for value in strings:
        raw = value.encode("utf-8")
        utf16_length = len(value.encode("utf-16-le")) // 2
        if utf16_length >= 0x80 or len(raw) >= 0x80:
            raise AssertionError("fixture string is too long for one-byte lengths")
        item = bytes([utf16_length, len(raw)]) + raw + b"\0"
        offsets.append(position)
        encoded.append(item)
        position += len(item)
    string_data = b"".join(encoded)
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    chunk_size = strings_start + len(string_data)
    padding = (-chunk_size) % 4
    chunk_size += padding
    return b"".join(
        [
            struct.pack("<HHI", 1, header_size, chunk_size),
            struct.pack("<IIIII", len(strings), 0, 0x100, strings_start, 0),
            b"".join(struct.pack("<I", offset) for offset in offsets),
            string_data,
            b"\0" * padding,
        ]
    )


def _minimal_arsc_fixture():
    global_pool = _utf8_string_pool(["Hello"])
    type_pool = _utf8_string_pool(["string"])
    key_pool = _utf8_string_pool(["title"])
    type_spec = b"".join(
        [
            struct.pack("<HHI", 0x0202, 16, 20),
            struct.pack("<BBHI", 1, 0, 1, 1),
            struct.pack("<I", 0),
        ]
    )
    config_bytes = struct.pack("<I", 8) + b"\x01\x02\x03\x04"
    type_header_size = 20 + len(config_bytes)
    entries_start = type_header_size + 4
    entry = struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 3, 0)
    type_chunk_size = entries_start + len(entry)
    type_chunk = b"".join(
        [
            struct.pack("<HHI", 0x0201, type_header_size, type_chunk_size),
            struct.pack("<BBHII", 1, 0, 0, 1, entries_start),
            config_bytes,
            struct.pack("<I", 0),
            entry,
        ]
    )
    package_header_size = 288
    package_name = "com.example".encode("utf-16-le")
    package_name_field = package_name + b"\0" * (256 - len(package_name))
    type_strings_offset = package_header_size
    key_strings_offset = type_strings_offset + len(type_pool)
    package_children = type_pool + key_pool + type_spec + type_chunk
    package_size = package_header_size + len(package_children)
    package_header = b"".join(
        [
            struct.pack("<HHI", 0x0200, package_header_size, package_size),
            struct.pack("<I", 0x7F),
            package_name_field,
            struct.pack("<IIIII", type_strings_offset, 0, key_strings_offset, 0, 0),
        ]
    )
    package = package_header + package_children
    root_size = 12 + len(global_pool) + len(package)
    return struct.pack("<HHII", 2, 12, root_size, 1) + global_pool + package


class G002MethodAV10RegressionTests(unittest.TestCase):
    def test_v10_defaults_use_v10_root_schema_and_contract_gate(self) -> None:
        self.assertEqual(
            METHOD_A.DEFAULT_OUTPUT,
            Path(
                ".omx/research/hikmicro-viewer-2.6.0/static/"
                "g002-method-a-v10"
            ),
        )
        self.assertEqual(METHOD_A.INVENTORY_SCHEMA, "g002-normalized-inventory/v2")
        self.assertEqual(METHOD_A.DEFAULT_CONTRACT.name, "g002-neutral-normalization-contract.json")
        self.assertEqual(
            METHOD_A.ACCEPTED_CONTRACT_SHA256,
            "c378fe00e906fbf492d970d3cdc02df30601b416e61449de271ac4433087da29",
        )
        self.assertEqual(
            METHOD_A.ACCEPTED_CONTRACT_SCHEMA,
            "g002-neutral-normalization-contract/v10",
        )



    def test_deferred_component_emission_adds_split_application_declaration_parents(self) -> None:
        collector = METHOD_A.RecordCollector()
        base_parent = collector.add(
            "frozen_artifact",
            "xapk-apk:base.apk",
            dataset="xapk",
            artifact_id="xapk-apk:base.apk",
            source_artifact_id="xapk-apk:base.apk",
            sha256="a" * 64,
            size_bytes=1,
            official_source={"type": "zip_member", "member_path": "base.apk"},
        )
        def add_manifest_node(apk_id: str, ordinal: int, xpath_suffix: str) -> str:
            payload = {
                "apk_artifact_id": apk_id,
                "event_ordinal": ordinal,
                "qname": "Q{}application",
                "xpath": f"axmlpath:/Q{{}}manifest[1]/Q{{}}application[{xpath_suffix}]",
                "attributes": [],
                "parent_manifest_node_record_id": "INV-" + str(ordinal) * 64,
            }
            return collector.add(
                "manifest_node",
                payload,
                dataset="manifests",
                artifact_id=None,
                source_artifact_id=apk_id,
                sha256=None,
                size_bytes=None,
                official_source=None,
                parent_record_ids=[base_parent],
            )
        base_decl = add_manifest_node("xapk-apk:base.apk", 1, "1")
        split_decl = add_manifest_node("xapk-apk:split.apk", 2, "2")
        manifest_items = [
            {
                "apk_artifact_id": "xapk-apk:base.apk",
                "node_record_ids_by_path": {"base-app": base_decl},
                "axml": {"package": "com.example", "components": [("application", None, "base-app")], "nodes": [{"event_ordinal": 1, "name": "application", "path": "base-app", "attrs": {}}]},
            },
            {
                "apk_artifact_id": "xapk-apk:split.apk",
                "node_record_ids_by_path": {"split-app": split_decl},
                "axml": {"package": "com.example", "components": [("application", None, "split-app")], "nodes": [{"event_ordinal": 2, "name": "application", "path": "split-app", "attrs": {}}]},
            },
        ]
        METHOD_A._add_android_component_records(
            collector,
            manifest_items=manifest_items,
            canonical_base_apk_artifact_id="xapk-apk:base.apk",
            effective_target_sdk=35,
        )
        component = next(record for record in collector.records if record["record_type"] == "android_component")
        self.assertEqual(component["parent_record_ids"], sorted([base_parent, base_decl, split_decl]))

    def test_nonalias_component_parents_include_all_declaration_nodes_for_merge_key(self) -> None:
        collector = METHOD_A.RecordCollector()
        base_parent = collector.add(
            "frozen_artifact",
            "xapk-apk:base.apk",
            dataset="xapk",
            artifact_id="xapk-apk:base.apk",
            source_artifact_id="xapk-apk:base.apk",
            sha256="a" * 64,
            size_bytes=1,
            official_source={"type": "zip_member", "member_path": "base.apk"},
        )
        collector.add(
            "configuration",
            {
                "configuration_kind": "apk_archive_entry",
                "container_artifact_id": "xapk-apk:base.apk",
                "central_directory_ordinal": 0,
                "path": "AndroidManifest.xml",
                "compression_method": 0,
                "crc32": 0,
                "compressed_size_bytes": 1,
                "uncompressed_size_bytes": 1,
                "sha256": "b" * 64,
            },
            dataset="apk_entries",
            artifact_id=None,
            source_artifact_id="xapk-apk:base.apk",
            sha256="b" * 64,
            size_bytes=1,
            official_source=None,
            parent_record_ids=[base_parent],
        )
        name_attr = {"typed": ".SyncService", "raw": None, "type": 3, "data": 0}
        axml = {
            "package": "com.example",
            "target_sdk": 28,
            "min_sdk": 21,
            "features": [],
            "components": [
                ("service", ".SyncService", "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}service[1]"),
                ("service", ".SyncService", "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}service[2]"),
            ],
            "nodes": [
                {"event_ordinal": 0, "name": "manifest", "qname": "Q{}manifest", "path": "axmlpath:/Q{}manifest[1]", "attributes": [], "attrs": {("", "package"): {"typed": "com.example", "raw": None}}},
                {"event_ordinal": 1, "name": "application", "qname": "Q{}application", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]", "attributes": [], "attrs": {}},
                {"event_ordinal": 2, "name": "service", "qname": "Q{}service", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}service[1]", "attributes": [], "attrs": {(METHOD_A.ANDROID_NS, "name"): name_attr}},
                {"event_ordinal": 3, "name": "service", "qname": "Q{}service", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}service[2]", "attributes": [], "attrs": {(METHOD_A.ANDROID_NS, "name"): name_attr}},
            ],
        }
        result = METHOD_A._add_manifest_records(
            collector,
            axml=axml,
            apk_artifact_id="xapk-apk:base.apk",
            include_installed_declarations=True,
        )
        component = next(record for record in collector.records if record["record_type"] == "android_component")
        declaration_ids = [result["node_record_ids_by_path"][path] for _kind, _name, path in axml["components"]]
        self.assertEqual(component["parent_record_ids"], sorted([base_parent, *declaration_ids]))

    def test_alias_component_parents_include_alias_declarations_and_target_component(self) -> None:
        collector = METHOD_A.RecordCollector()
        base_parent = collector.add(
            "frozen_artifact",
            "xapk-apk:base.apk",
            dataset="xapk",
            artifact_id="xapk-apk:base.apk",
            source_artifact_id="xapk-apk:base.apk",
            sha256="a" * 64,
            size_bytes=1,
            official_source={"type": "zip_member", "member_path": "base.apk"},
        )
        collector.add(
            "configuration",
            {
                "configuration_kind": "apk_archive_entry",
                "container_artifact_id": "xapk-apk:base.apk",
                "central_directory_ordinal": 0,
                "path": "AndroidManifest.xml",
                "compression_method": 0,
                "crc32": 0,
                "compressed_size_bytes": 1,
                "uncompressed_size_bytes": 1,
                "sha256": "b" * 64,
            },
            dataset="apk_entries",
            artifact_id=None,
            source_artifact_id="xapk-apk:base.apk",
            sha256="b" * 64,
            size_bytes=1,
            official_source=None,
            parent_record_ids=[base_parent],
        )
        axml = {
            "package": "com.example",
            "target_sdk": 28,
            "min_sdk": 21,
            "features": [],
            "components": [
                ("activity", ".MainActivity", "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity[1]"),
                ("activity-alias", ".AliasActivity", "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity-alias[1]"),
            ],
            "nodes": [
                {"event_ordinal": 0, "name": "manifest", "qname": "Q{}manifest", "path": "axmlpath:/Q{}manifest[1]", "attributes": [], "attrs": {("", "package"): {"typed": "com.example", "raw": None}}},
                {"event_ordinal": 1, "name": "application", "qname": "Q{}application", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]", "attributes": [], "attrs": {}},
                {"event_ordinal": 2, "name": "activity", "qname": "Q{}activity", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity[1]", "attributes": [], "attrs": {(METHOD_A.ANDROID_NS, "name"): {"typed": ".MainActivity", "raw": None, "type": 3, "data": 0}}},
                {"event_ordinal": 3, "name": "activity-alias", "qname": "Q{}activity-alias", "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity-alias[1]", "attributes": [], "attrs": {(METHOD_A.ANDROID_NS, "name"): {"typed": ".AliasActivity", "raw": None, "type": 3, "data": 0}, (METHOD_A.ANDROID_NS, "targetActivity"): {"typed": ".MainActivity", "raw": None, "type": 3, "data": 0}}},
            ],
        }
        result = METHOD_A._add_manifest_records(
            collector,
            axml=axml,
            apk_artifact_id="xapk-apk:base.apk",
            include_installed_declarations=True,
        )
        components = [record for record in collector.records if record["record_type"] == "android_component"]
        target = next(record for record in components if record["payload"]["kind"] == "activity")
        alias = next(record for record in components if record["payload"]["kind"] == "activity_alias")
        alias_decl = result["node_record_ids_by_path"]["axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity-alias[1]"]
        self.assertEqual(alias["parent_record_ids"], sorted([base_parent, alias_decl, target["record_id"]]))

    def test_android_namespace_spoof_cannot_create_component_identity_or_alias_target(self) -> None:
        custom_ns = "urn:spoof"
        attrs = {
            (custom_ns, "name"): {"typed": ".SpoofAlias", "raw": None, "type": 3, "data": 0},
            (custom_ns, "targetActivity"): {"typed": ".SpoofTarget", "raw": None, "type": 3, "data": 0},
        }
        self.assertIsNone(METHOD_A._manifest_attr_text(attrs, "name"))
        self.assertIsNone(METHOD_A._manifest_attr_text(attrs, "targetActivity"))

    def test_deterministic_evidence_chronology_is_strict_and_repeatable(self) -> None:
        timestamps = [METHOD_A._deterministic_timestamp(index) for index in range(4)]
        self.assertEqual(
            timestamps,
            [
                "2024-01-01T00:00:00.000000Z",
                "2024-01-01T00:00:00.000001Z",
                "2024-01-01T00:00:00.000002Z",
                "2024-01-01T00:00:00.000003Z",
            ],
        )
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len(set(timestamps)), 4)

    def test_source_projection_self_check_does_not_discard_failures(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("source_match_failures[:0]", source)
        self.assertIn(
            '_assertion("source_match_failures", [], source_match_failures)',
            source,
        )

    def test_byte_owned_configuration_projects_designated_archive_bytes(self) -> None:
        archive_payload = {
            "configuration_kind": "apk_archive_entry",
            "container_artifact_id": "xapk-apk:fixture.apk",
            "central_directory_ordinal": 3,
            "path": "classes.dex",
            "compression_method": 8,
            "crc32": 7,
            "compressed_size_bytes": 11,
            "uncompressed_size_bytes": 13,
            "sha256": "a" * 64,
        }
        arm32_payload = {
            "configuration_kind": "arm32_native_library",
            "apk_artifact_id": "xapk-apk:fixture.apk",
            "abi": "armeabi-v7a",
            "archive_entry_record_id": "INV-" + "1" * 64,
            "path": "lib/armeabi-v7a/libfixture.so",
            "soname": "libfixture.so",
            "size_bytes": 17,
            "sha256": "b" * 64,
        }
        self.assertEqual(
            METHOD_A._payload_byte_evidence(archive_payload),
            ("a" * 64, 13),
        )
        self.assertEqual(
            METHOD_A._payload_byte_evidence(arm32_payload),
            ("b" * 64, 17),
        )
        payload_digest, payload_size = METHOD_A._payload_digest(archive_payload)
        self.assertNotEqual((payload_digest, payload_size), ("a" * 64, 13))

    def test_apk_archive_entry_parent_includes_exact_nested_frozen_parent(self) -> None:
        collector = METHOD_A.RecordCollector()
        apk_parent = collector.add(
            "frozen_artifact",
            "xapk-apk:fixture.apk",
            dataset="xapk",
            artifact_id="xapk-apk:fixture.apk",
            source_artifact_id="xapk-apk:fixture.apk",
            sha256="a" * 64,
            size_bytes=11,
            official_source={"type": "zip_member", "member_path": "fixture.apk"},
        )
        nested_parent = collector.add(
            "frozen_artifact",
            "extracted-dex:classes.dex",
            dataset="dex",
            artifact_id="extracted-dex:classes.dex",
            source_artifact_id="extracted-dex:classes.dex",
            sha256="b" * 64,
            size_bytes=13,
            official_source={"type": "zip_member", "member_path": "classes.dex"},
        )

        parents = METHOD_A._apk_archive_entry_parent_ids(
            collector,
            "xapk-apk:fixture.apk",
            nested_artifact_id="extracted-dex:classes.dex",
        )

        self.assertEqual(parents, sorted([apk_parent, nested_parent]))

    def test_readelf_section_display_label_canonicalizes_name_and_version_to_none(self) -> None:
        sample = """
Symbol table '.dynsym' contains 2 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND
     7: 0000000000001234     0 SECTION LOCAL  DEFAULT   19 .text@@LIB_1 (2)
"""
        _declared, included, _excluded = METHOD_A._parse_readelf_symbols(sample)
        self.assertEqual(included[0]["dynsym_index"], 7)
        self.assertEqual(included[0]["symbol_type"], "STT_SECTION")
        self.assertEqual(included[0]["section_index"], 19)
        self.assertIsNone(included[0]["name"])
        self.assertIsNone(included[0]["version"])

    def test_colon_prefixed_android_process_stays_literal_and_missing_defaults_to_package(self) -> None:
        self.assertEqual(
            METHOD_A._component_process("com.example.app", ":remote", "package"),
            ":remote",
        )
        self.assertEqual(
            METHOD_A._component_process("com.example.app", None, "package"),
            "com.example.app",
        )

    def test_certificate_payload_uses_v2_v3_v1_physical_order_and_ordinals(self) -> None:
        class FakeApk:
            def get_certificates_v1(self):
                return [b"v1-cert"]

            def get_certificates_der_v2(self):
                return [b"v2-cert"]

            def get_certificates_der_v3(self):
                return [b"v3-cert"]

            def get_certificates_der_v31(self):
                return []

        collector, _artifact = _collector_with_frozen_artifact(
            "xapk-apk:fixture.apk",
            dataset="xapk",
            kind="apk_member",
        )
        METHOD_A._analyze_certificates(
            collector,
            apk=FakeApk(),
            apk_artifact_id="xapk-apk:fixture.apk",
        )
        payloads = [
            record["payload"]
            for record in collector.records
            if record["record_type"] == "certificate"
        ]
        self.assertEqual([payload["scheme"] for payload in payloads], ["v2", "v3", "v1"])
        self.assertEqual(
            [payload["scheme_occurrence_ordinal"] for payload in payloads],
            [0, 0, 0],
        )
        self.assertEqual(
            [payload["encoded_certificate_ordinal"] for payload in payloads],
            [0, 1, 2],
        )
        self.assertEqual([payload["certificate_index"] for payload in payloads], [0, 0, 0])

    def test_raw_arsc_configuration_preserves_config_bytes_physical_ordinal_and_scalar_string_rule(self) -> None:
        class FakeConfig:
            raw_bytes = bytes(range(64))
            type_chunk_ordinal = 7
            entry_index_ordinal = 23

            def get_qualifier(self):
                return "en"

        class FakeReference:
            def get_data_type_string(self):
                return "TYPE_INT_DEC"

            def get_data_type(self):
                return 16

            def get_data(self):
                return 42

            def format_value(self):
                return "42"

        class FakeEntry:
            flags = 5
            index = 11
            key = FakeReference()

            def is_complex(self):
                return False

            def is_compact(self):
                return False

        class FakeResources:
            resource_values = {0x7F010002: {FakeConfig(): FakeEntry()}}

            def _analyse(self):
                return None

            def get_resource_xml_name(self, _resource_id):
                return "@com.example:string/title"

        class FakeApk:
            def get_android_resources(self):
                return FakeResources()

        collector, _artifact = _collector_with_frozen_artifact(
            "xapk-apk:fixture.apk",
            dataset="xapk",
            kind="apk_member",
        )
        METHOD_A._analyze_resources(
            collector,
            apk=FakeApk(),
            apk_artifact_id="xapk-apk:fixture.apk",
            resource_name_map={},
        )
        payload = next(
            record["payload"]
            for record in collector.records
            if record["record_type"] == "configuration"
            and record["payload"]["configuration_kind"] == "resource_configuration"
        )
        self.assertEqual(payload["configuration"]["size_bytes"], 64)
        self.assertEqual(payload["configuration"]["bytes_hex"], bytes(range(64)).hex())
        self.assertEqual(payload["type_chunk_ordinal"], 7)
        self.assertEqual(payload["entry_index_ordinal"], 23)
        self.assertNotIn("entry_index_slot", payload)
        self.assertEqual(payload["entry_id"], 2)
        self.assertEqual(payload["value"]["kind"], "scalar")
        self.assertEqual(payload["value"]["data_type"], 16)
        self.assertIsNone(payload["value"]["string_value"])

    def test_direct_arsc_parser_uses_physical_chunk_and_entry_ordinals(self) -> None:
        apk_artifact_id = "xapk-apk:fixture.apk"
        resources, configurations = METHOD_A._parse_arsc_resource_table(
            _minimal_arsc_fixture(),
            apk_artifact_id,
        )
        self.assertEqual(
            resources,
            [
                {
                    "apk_artifact_id": apk_artifact_id,
                    "package_chunk_ordinal": 0,
                    "package_id": 0x7F,
                    "package_name": "com.example",
                    "raw_type_id": 1,
                    "type_id_offset": 0,
                    "type_id": 1,
                    "entry_id": 0,
                    "resource_id": "0x7f010000",
                    "type_name": "string",
                    "entry_name": "title",
                }
            ],
        )
        resource_record_id = METHOD_A._record_id("resource", resources[0])
        self.assertEqual(
            configurations,
            [
                {
                    "configuration_kind": "resource_configuration",
                    "resource_record_id": resource_record_id,
                    "package_chunk_ordinal": 0,
                    "type_chunk_ordinal": 0,
                    "entry_index_ordinal": 0,
                    "entry_id": 0,
                    "entry_encoding": "full",
                    "entry_flags": 0,
                    "key_index": 0,
                    "configuration": {
                        "size_bytes": 8,
                        "bytes_hex": "0800000001020304",
                    },
                    "value": {
                        "kind": "scalar",
                        "data_type": 3,
                        "data": 0,
                        "string_value": "Hello",
                    },
                }
            ],
        )

    def test_dex_invoke_byte_offset_is_converted_to_code_unit_offset(self) -> None:
        method = _FakeMethod(
            "callLoader",
            "()V",
            instructions=[
                (
                    10,
                    _FakeInstruction(
                        "invoke-static",
                        ["Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;"],
                    ),
                )
            ],
        )
        collector, artifact = _collector_with_frozen_artifact("extracted-dex:classes.dex")
        with tempfile.TemporaryDirectory() as directory:
            dex_path = Path(directory) / "classes.dex"
            dex_path.write_bytes(b"dex")
            METHOD_A._analyze_dex(
                collector,
                dex_path=dex_path,
                source_artifact=artifact,
                dex_class=_dex_class_with_methods([method]),
            )
        dynamic = next(record for record in collector.records if record["record_type"] == "dynamic_loader")
        self.assertEqual(dynamic["payload"]["instruction_offset_code_units"], 5)

    def test_direct_dex_interpreter_resolves_register_string_and_rejects_truncated_invoke(self) -> None:
        methods = [
            (
                "Ljava/lang/Class;",
                "forName",
                "(Ljava/lang/String;)Ljava/lang/Class;",
            )
        ]
        units = (
            0x001A,
            0,
            0x1071,
            0,
            0,
        )
        targets = METHOD_A._interpret_dex_targets(
            units,
            1,
            ["com.example.Target"],
            [],
            methods,
        )
        expected = {
            "target_kind": "class",
            "class_descriptor": "Lcom/example/Target;",
        }
        self.assertEqual(targets[("dynamic_loader", 2)], expected)
        self.assertEqual(targets[("reflection_target", 2)], expected)
        truncated = METHOD_A._interpret_dex_targets(
            units[:-1],
            1,
            ["com.example.Target"],
            [],
            methods,
        )
        self.assertEqual(truncated, {})

    def test_direct_dex_target_recipes_follow_contract_resolution_limits(self) -> None:
        self.assertEqual(
            METHOD_A._evaluate_dex_target_recipe(
                "dex_path_list(arg0)",
                [("String", "first.dex:second.dex")],
                has_receiver=False,
            ),
            {
                "target_kind": "dex_path_list",
                "values": ["first.dex", "second.dex"],
            },
        )
        self.assertIsNone(
            METHOD_A._evaluate_dex_target_recipe(
                "jna_dispatch(jnidispatch)",
                [],
                has_receiver=False,
            )
        )

    def test_closed_dynamic_and_reflection_api_matching_are_independent(self) -> None:
        apis = [
            "Lcom/sun/jna/NativeLibrary;->getInstance(Ljava/lang/String;)Lcom/sun/jna/NativeLibrary;",
            "Ldalvik/system/DexFile;->loadDex(Ljava/lang/String;Ljava/lang/String;I)Ldalvik/system/DexFile;",
            "Ldalvik/system/DelegateLastClassLoader;-><init>(Ljava/lang/String;Ljava/lang/ClassLoader;)V",
            "Ljava/lang/ClassLoader;->findClass(Ljava/lang/String;)Ljava/lang/Class;",
            "Ljava/lang/Class;->getMethod(Ljava/lang/String;[Ljava/lang/Class;)Ljava/lang/reflect/Method;",
            "Ljava/lang/reflect/Method;->invoke(Ljava/lang/Object;[Ljava/lang/Object;)Ljava/lang/Object;",
        ]
        method = _FakeMethod(
            "touchApis",
            "()V",
            instructions=[
                (
                    2,
                    _FakeInstruction(
                        "invoke-static",
                        ["jnalib", apis[0]],
                    ),
                ),
                (
                    4,
                    _FakeInstruction(
                        "invoke-static",
                        ["/tmp/plugin.dex", apis[1]],
                    ),
                ),
                (
                    6,
                    _FakeInstruction(
                        "invoke-direct",
                        ["/tmp/classes.dex", apis[2]],
                    ),
                ),
                (
                    8,
                    _FakeInstruction(
                        "invoke-virtual",
                        ["com.example.Dynamic", apis[3]],
                    ),
                ),
                (
                    10,
                    _FakeInstruction(
                        "invoke-virtual",
                        ["methodName", apis[4]],
                    ),
                ),
                (
                    12,
                    _FakeInstruction(
                        "invoke-virtual",
                        [apis[5]],
                    ),
                ),
            ],
        )
        collector, artifact = _collector_with_frozen_artifact("extracted-dex:classes.dex")
        with tempfile.TemporaryDirectory() as directory:
            dex_path = Path(directory) / "classes.dex"
            dex_path.write_bytes(b"dex")
            METHOD_A._analyze_dex(
                collector,
                dex_path=dex_path,
                source_artifact=artifact,
                dex_class=_dex_class_with_methods([method]),
            )
        dynamic_methods = [
            record["payload"]["api"]["method_name"]
            for record in collector.records
            if record["record_type"] == "dynamic_loader"
        ]
        reflection_methods = [
            record["payload"]["api"]["method_name"]
            for record in collector.records
            if record["record_type"] == "reflection_target"
        ]
        self.assertEqual(
            dynamic_methods,
            ["getInstance", "loadDex", "<init>", "findClass"],
        )
        self.assertEqual(
            reflection_methods,
            ["getMethod", "invoke"],
        )

    def test_target_recipes_emit_class_native_library_and_canonical_unresolved_targets(self) -> None:
        method = _FakeMethod(
            "targets",
            "()V",
            instructions=[
                (
                    2,
                    _FakeInstruction(
                        "invoke-static",
                        [
                            "com.example.Target",
                            "Ljava/lang/Class;->forName(Ljava/lang/String;)Ljava/lang/Class;",
                        ],
                    ),
                ),
                (
                    4,
                    _FakeInstruction(
                        "invoke-static",
                        [
                            "thermal_jni",
                            "Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V",
                        ],
                    ),
                ),
                (
                    6,
                    _FakeInstruction(
                        "invoke-virtual",
                        ["Ljava/lang/ClassLoader;->loadClass(Ljava/lang/String;)Ljava/lang/Class;"],
                    ),
                ),
            ],
        )
        collector, artifact = _collector_with_frozen_artifact("extracted-dex:classes.dex")
        with tempfile.TemporaryDirectory() as directory:
            dex_path = Path(directory) / "classes.dex"
            dex_path.write_bytes(b"dex")
            METHOD_A._analyze_dex(
                collector,
                dex_path=dex_path,
                source_artifact=artifact,
                dex_class=_dex_class_with_methods([method]),
            )
        targets = [
            record["payload"]["target"]
            for record in collector.records
            if record["record_type"] == "dynamic_loader"
        ]
        self.assertEqual(
            targets,
            [
                {"target_kind": "class", "class_descriptor": "Lcom/example/Target;"},
                {"target_kind": "native_library_name", "value": "thermal_jni"},
                {"unresolved_token": "not_statically_resolved"},
            ],
        )

    def test_resolved_static_jni_parent_set_includes_symbol_and_export_aliases(self) -> None:
        dex_artifact_id = "extracted-dex:classes.dex"
        library_artifact_id = "extracted-native:lib/arm64-v8a/libsample.so"
        collector, _dex_artifact = _collector_with_frozen_artifact(dex_artifact_id)
        dex_parent = METHOD_A._record_id("frozen_artifact", dex_artifact_id)
        library_parent = collector.add(
            "frozen_artifact",
            library_artifact_id,
            dataset="elf",
            artifact_id=library_artifact_id,
            source_artifact_id=library_artifact_id,
            sha256="b" * 64,
            size_bytes=1,
            official_source={"type": "file", "path": library_artifact_id},
        )
        class_record_id = collector.add(
            "class",
            {
                "dex_artifact_id": dex_artifact_id,
                "descriptor": "Lcom/example/Native;",
                "access_flags": 1,
                "superclass": "Ljava/lang/Object;",
                "interfaces": [],
            },
            dataset="dex",
            artifact_id=None,
            source_artifact_id=dex_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[dex_parent],
        )
        family_record_id = collector.add(
            "method_family",
            {
                "dex_artifact_id": dex_artifact_id,
                "class_descriptor": "Lcom/example/Native;",
                "method_name": "call",
                "definitions": [{"descriptor": "()V", "access_flags": 0x0101}],
            },
            dataset="dex",
            artifact_id=None,
            source_artifact_id=dex_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[dex_parent, class_record_id],
        )
        native_symbol_record_id = collector.add(
            "native_symbol",
            {
                "library_artifact_id": library_artifact_id,
                "dynamic_symbol_index": 4,
                "name": "Java_com_example_Native_call",
                "version": None,
                "value": 4096,
                "size_bytes": 8,
                "symbol_type": "STT_FUNC",
                "binding": "STB_GLOBAL",
                "visibility": "STV_DEFAULT",
                "section_index": 1,
            },
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent],
        )
        native_export_record_id = collector.add(
            "native_export",
            {
                "native_symbol_record_id": native_symbol_record_id,
                "library_artifact_id": library_artifact_id,
                "dynamic_symbol_index": 4,
                "name": "Java_com_example_Native_call",
                "version": None,
                "binding": "STB_GLOBAL",
            },
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent, native_symbol_record_id],
        )
        inputs = METHOD_A.Inputs(
            repo_root=Path("."),
            xapk=Path("fixture.xapk"),
            official_manifest_path=Path("official-artifacts.json"),
            official_manifest={},
            artifacts=(),
            artifacts_by_id={
                dex_artifact_id: {"artifact_id": dex_artifact_id, "kind": "dex"},
                library_artifact_id: {"artifact_id": library_artifact_id, "kind": "native_library"},
            },
            artifact_set_id="artifact-set:test",
            base_member="base.apk",
            apk_member_artifact_by_path={},
            xapk_member_artifact_by_path={},
            base_entry_artifact_by_path={},
        )
        METHOD_A._add_jni_edges(
            collector,
            inputs=inputs,
            native_methods=[
                {
                    "dex_artifact_id": dex_artifact_id,
                    "class_descriptor": "Lcom/example/Native;",
                    "method_name": "call",
                    "descriptor": "()V",
                    "class_record_id": class_record_id,
                    "family_record_id": family_record_id,
                }
            ],
            native_exports=[
                {
                    "library_artifact_id": library_artifact_id,
                    "dynamic_symbol_index": 4,
                    "name": "Java_com_example_Native_call",
                    "version": None,
                    "native_symbol_record_id": native_symbol_record_id,
                    "native_export_record_id": native_export_record_id,
                    "virtual_address": 4096,
                }
            ],
        )
        edge = next(
            record for record in collector.records
            if record["record_type"] == "jni_edge"
            and record["payload"]["binding_form"] == "static_short"
        )
        self.assertEqual(
            edge["payload"]["native_endpoint"]["native_symbol_record_id"],
            native_symbol_record_id,
        )
        self.assertEqual(
            edge["payload"]["native_endpoint"]["native_export_record_id"],
            native_export_record_id,
        )
        self.assertEqual(
            edge["parent_record_ids"],
            sorted(
                [
                    dex_parent,
                    class_record_id,
                    family_record_id,
                    library_parent,
                    native_symbol_record_id,
                    native_export_record_id,
                ]
            ),
        )

    def test_orphan_parent_equation_remains_source_library_plus_native_export_only(self) -> None:
        library_artifact_id = "extracted-native:lib/arm64-v8a/liborphan.so"
        collector, _artifact = _collector_with_frozen_artifact(
            library_artifact_id,
            dataset="elf",
            kind="native_library",
        )
        library_parent = METHOD_A._record_id("frozen_artifact", library_artifact_id)
        native_symbol_record_id = collector.add(
            "native_symbol",
            {
                "library_artifact_id": library_artifact_id,
                "dynamic_symbol_index": 9,
                "name": "Java_com_example_Orphan_call",
                "version": None,
                "value": 8192,
                "size_bytes": 4,
                "symbol_type": "STT_FUNC",
                "binding": "STB_GLOBAL",
                "visibility": "STV_DEFAULT",
                "section_index": 1,
            },
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent],
        )
        native_export_record_id = collector.add(
            "native_export",
            {
                "native_symbol_record_id": native_symbol_record_id,
                "library_artifact_id": library_artifact_id,
                "dynamic_symbol_index": 9,
                "name": "Java_com_example_Orphan_call",
                "version": None,
                "binding": "STB_GLOBAL",
            },
            dataset="elf",
            artifact_id=None,
            source_artifact_id=library_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[library_parent, native_symbol_record_id],
        )
        inputs = METHOD_A.Inputs(
            repo_root=Path("."),
            xapk=Path("fixture.xapk"),
            official_manifest_path=Path("official-artifacts.json"),
            official_manifest={},
            artifacts=(),
            artifacts_by_id={library_artifact_id: {"artifact_id": library_artifact_id, "kind": "native_library"}},
            artifact_set_id="artifact-set:test",
            base_member="base.apk",
            apk_member_artifact_by_path={},
            xapk_member_artifact_by_path={},
            base_entry_artifact_by_path={},
        )
        METHOD_A._add_jni_edges(
            collector,
            inputs=inputs,
            native_methods=(),
            native_exports=[
                {
                    "library_artifact_id": library_artifact_id,
                    "dynamic_symbol_index": 9,
                    "name": "Java_com_example_Orphan_call",
                    "version": None,
                    "native_symbol_record_id": native_symbol_record_id,
                    "native_export_record_id": native_export_record_id,
                    "virtual_address": 8192,
                }
            ],
        )
        edge = next(record for record in collector.records if record["record_type"] == "jni_edge")
        self.assertEqual(edge["parent_record_ids"], sorted([library_parent, native_export_record_id]))


if __name__ == "__main__":
    unittest.main()
