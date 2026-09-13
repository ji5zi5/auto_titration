"""Producer-B v10 regressions for direct canonical candidate construction."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import shlex
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
METHOD_B_PATH = ROOT / "tools/hik_whole_apk/g002_method_b.py"
CONTRACT_PATH = (
    ROOT
    / ".omx/research/hikmicro-viewer-2.6.0/governance/"
    / "g002-neutral-normalization-contract.json"
)
SCRATCH_ROOT = Path("/tmp/g002-producer-b-v10")
EXPECTED_CANDIDATE_PATHS = {
    "bundle.json",
    "command.json",
    "inventory.json",
    "review.json",
    "run.json",
    "source-index.json",
    "raw/apk-entries.json",
    "raw/dex.json",
    "raw/elf.json",
    "raw/jni.json",
    "raw/manifests.json",
    "raw/resources.json",
    "raw/signing.json",
    "raw/xapk.json",
}
EXPECTED_FAMILY_MEMBERSHIPS = {
    "android_component": (
        32,
        "67dcc350d8686985efedcd4b59fbe4113aeacb86deba5599a62c1e990da5c63c",
        "ec3ff298c2e5fedc00ce4256c66d2736324856e9cb846f6a549188640749c642",
    ),
    "asset": (
        762,
        "932c0fcf7ea28e399d3b4d4c964fa7550e679439d8f20a80f5fa035c2f38c816",
        "e448166f4e64ab110851d633532e1fe097f0e5f659f4ca5199bc838802d6a548",
    ),
    "certificate": (
        56,
        "69dc9d7fc04338a85f77a23efd9a3613fb6d330e68612951dc48b5a47fae20e0",
        "4a95e4b103830b88ec1b3ff1eae26dc3523e313ffbe7bcbbff5932f1dc25401d",
    ),
    "class": (
        30635,
        "ba221b75a9be1c388efe24c5aaac7625edfdb86b0b33849029922f9047f18fa6",
        "07dfa7ec1b08dc5203b9c75681fdc6e628970edf0bb7fa59fd48e755d694f044",
    ),
    "configuration:apk_archive_entry": (
        4314,
        "a040f7ae2115ddc2fb7d19bb761ff764de536571cf7bd360054a8f83ef13fc26",
        "a830541670021959f0a10d219ff041e3863ffe8b5af94cdaeb3572aece2782eb",
    ),
    "configuration:arm32_native_library": (
        90,
        "d546d62c397e50f7c7cc2a711c58abd76f44e8c5d16636fab44a302a920174ef",
        "8cb337ab5d0d8acabe88644a5e521df7cfc55239b5544b5cf84b28e374a08a08",
    ),
    "configuration:native_library_summary": (
        88,
        "14c10a6d6dddf99f49f1b234cf5ecbef72ce6bf16990de40a5391dec234d5699",
        "b1fb14494d9fe6d34c16fc83579587244fbee467bcfe1e4a7f052e20cc6c0809",
    ),
    "configuration:resource_configuration": (
        36498,
        "c230ec6f272e51a967174e8cb9ded5df12ff85b12ee92d7dc9168ce2c00cd8a9",
        "b4565a5bc4996510bd15a3bec5698254c0ea065da717bab90a99d6be4a817a21",
    ),
    "configuration:xapk_archive_entry": (
        21,
        "1316260de71a90bddb5df1aa2867db005bd7e38221fcacada5b94a291ec9ada3",
        "0c976f5aa7f2b0ccd185364f2aba1b7892a0e1c6d013f5de16bdffd4874e2978",
    ),
    "dynamic_loader": (
        239,
        "27934a08ec1a9e1b638b363f345dd5e3ec2051417c74ac6387ab488b627b7711",
        "00f33e4707c4cb6dd992eb7cc3a4c7cc4f3c2cd99b369cbabe6b199907740b9d",
    ),
    "feature": (
        3,
        "114991461ac721bddda786268020b981b7013957618d5c23069bc6534093181a",
        "1f5e00f52691da2a8a19ffaf2246698aa4f5f7d9dbec0ca623537e6983c75bdd",
    ),
    "frozen_artifact": (
        121,
        "4811adccd137d2842b3ee042a95049b716d0031fb08cd681115ccd78d25156a5",
        "bd4b1c12a3990f20f8da2559cfcde26adb72478a0fc9e13c2b77589a8abb82d8",
    ),
    "jni_edge": (
        3395,
        "d2339ccfa217d3aaa77ca12e1c7cb28abd2f93f6c69cf75c8615f45db61724b6",
        "3071b3e9cf6844ccf25ec8bd0e89ea5795f6afcdbf62d9c1ca94376a432b211b",
    ),
    "manifest_node": (
        188,
        "8f83cceff9ceb57c7c2f0edb071d9c7962c6f82012415058268a823c57b37115",
        "d48570a2ba388b581a9359cd43ca8e5ed4b5bf8bd6d151c77e847feb6dc63e3b",
    ),
    "method_family": (
        184508,
        "572226c9f78ba6d2e6183e97ca2e48768058870ae4b0ae2b0cdaab85013a8ee5",
        "4de861a43e3e3699a2d983841bcb618728820bab089972e7d77896392be37103",
    ),
    "native_export": (
        99414,
        "39aee67ef721ef2e4b7d0bd64f4f259aa58784fc3680f8e77bea2a7fbe5421cc",
        "1a824f1a9570606994e073babd81934b11a33b0caadd4c4654b27d2796a543be",
    ),
    "native_import:dt_needed": (
        490,
        "c77b256bf0d9e7ff0afbd9500758626d97d89632668abe4929b4a957a5b7a972",
        "7e8970eaa07fc131bcee6b88cc35886129853f12867cee9c56a22efdfbbe1028",
    ),
    "native_import:undefined_dynsym": (
        12137,
        "55246aba7bc84c28ad4158dab9a61e7210ad9e49c89ee98b675766a5bcbcdd86",
        "16acef4314f6167dc1b740b89198707590ff892b1d61e95893faf55c67dd8013",
    ),
    "native_symbol": (
        111643,
        "69ea003f586027493407c998239c5e80afedc7e62f4ff1de3e75bf7f3723487e",
        "44779f86cfc6cec94ab7cd8125cd1b982c8e98258137f5d30c4c740497f7f1ba",
    ),
    "reflection_target": (
        1372,
        "b0c6a6c502ec031e96248bd903457a4b0c85f86ac279b368cf69d032e5bac2ea",
        "4d67d81bd598e18524f579b2336396ad900b2f655cb9f2633504b853407bcc8a",
    ),
    "resource": (
        33431,
        "7e8e29a15df93bc7a8dc150bf138a2eb5015649bd419d22b9a5278987d2cc33d",
        "6179a927ae25ea84f0b772efd6e1a88646aaed58db6630acc64757f32b379435",
    ),
}


def load_method_b():
    spec = importlib.util.spec_from_file_location("g002_method_b_under_test", METHOD_B_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def recursive_hash_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


class G002MethodBV10RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.method_b = load_method_b()
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def test_frozen_v10_contract_and_output_roots_are_pinned(self) -> None:
        self.assertEqual(
            hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
            "c378fe00e906fbf492d970d3cdc02df30601b416e61449de271ac4433087da29",
        )
        self.assertEqual(self.contract["schema"], "g002-neutral-normalization-contract/v10")
        definitions = self.contract["record_model"]["definitions"]
        self.assertEqual(
            definitions["candidate_bundle_evidence"]["properties"]["schema"]["values"],
            ["g002-candidate-bundle/v2"],
        )
        self.assertEqual(
            definitions["inventory_evidence"]["properties"]["schema"]["values"],
            ["g002-normalized-inventory/v2"],
        )
        self.assertEqual(self.method_b.SCRIPT_VERSION, "g002-method-b-v10")
        self.assertEqual(self.method_b.DEFAULT_CANDIDATE_ROOT.name, "g002-method-b-v10")
        self.assertEqual(self.method_b.SCRATCH_ROOT, SCRATCH_ROOT)

    def test_candidate_replay_command_wires_contract_and_candidate_root(self) -> None:
        args = argparse.Namespace(
            xapk=Path("/tmp/input.xapk"),
            timestamp="2026-07-20T00:00:00Z",
            contract=CONTRACT_PATH,
            candidate_root=SCRATCH_ROOT / "candidate",
            llvm_readobj="llvm-readobj-16",
            llvm_readelf="llvm-readelf-16",
            llvm_nm="llvm-nm-16",
            llvm_objdump="llvm-objdump-16",
        )
        command = self.method_b.build_replay_command(
            args,
            SCRATCH_ROOT / "out",
            Path("/opt/aapt2"),
        )
        tokens = shlex.split(command)
        self.assertEqual(
            (ROOT / tokens[tokens.index("--contract") + 1]).resolve(),
            CONTRACT_PATH.resolve(),
        )
        self.assertEqual(
            tokens[tokens.index("--candidate-root") + 1],
            str(SCRATCH_ROOT / "candidate"),
        )

    def test_direct_cli_arguments_reach_actual_canonical_constructor(self) -> None:
        seen = {}

        def fake_produce(args):
            seen["contract"] = args.contract
            seen["candidate_root"] = args.candidate_root
            seen["xapk"] = args.xapk
            return {"status": "pass"}

        candidate_root = SCRATCH_ROOT / "main-dispatch-candidate"
        xapk = Path("/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk")
        with mock.patch.object(self.method_b, "produce_remediated", side_effect=fake_produce):
            exit_code = self.method_b.main(
                [
                    "--xapk",
                    str(xapk),
                    "--out",
                    str(SCRATCH_ROOT / "main-dispatch-out"),
                    "--contract",
                    str(CONTRACT_PATH),
                    "--candidate-root",
                    str(candidate_root),
                    "--timestamp",
                    "2026-07-20T00:00:00Z",
                ]
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["contract"].resolve(), CONTRACT_PATH.resolve())
        self.assertEqual(seen["candidate_root"], candidate_root)
        self.assertEqual(seen["xapk"], xapk)

        tree = ast.parse(METHOD_B_PATH.read_text(encoding="utf-8"))
        producer = function_node(tree, "produce_remediated")
        constructor_calls = [
            node
            for node in ast.walk(producer)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "write_canonical_candidate_bundle"
        ]
        self.assertEqual(len(constructor_calls), 1)
        keyword_values = {
            keyword.arg: ast.unparse(keyword.value)
            for keyword in constructor_calls[0].keywords
            if keyword.arg is not None
        }
        self.assertIn("args.candidate_root", keyword_values["candidate_root"])
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "load_json"
                and node.args
                and ast.unparse(node.args[0]) == "args.contract"
                for node in ast.walk(producer)
            ),
            "produce_remediated must consume the parsed contract directly",
        )

    def test_manifest_nonroot_parent_is_immediate_parent_identity(self) -> None:
        nodes = [
            {
                "event_ordinal": 0,
                "qname": "Q{}manifest",
                "path": "axmlpath:/Q{}manifest[1]",
                "attributes": [],
            },
            {
                "event_ordinal": 1,
                "qname": "Q{}application",
                "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]",
                "attributes": [],
            },
            {
                "event_ordinal": 2,
                "qname": "Q{}activity",
                "path": "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity[1]",
                "attributes": [],
            },
        ]
        payloads = self.method_b.manifest_node_payloads("xapk-apk:base.apk", nodes)
        by_path = {row["xpath"]: row for row in payloads}
        app = by_path["axmlpath:/Q{}manifest[1]/Q{}application[1]"]
        activity = by_path[
            "axmlpath:/Q{}manifest[1]/Q{}application[1]/Q{}activity[1]"
        ]
        self.assertEqual(
            activity["parent_manifest_node_record_id"],
            self.method_b.record_id("manifest_node", app),
        )

    def test_parent_ids_are_canonical_sorted_unique(self) -> None:
        official = {
            "artifact-a": {
                "artifact_id": "artifact-a",
                "kind": "apk_member",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "a"},
            },
            "artifact-b": {
                "artifact_id": "artifact-b",
                "kind": "apk_member",
                "sha256": "1" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "b"},
            },
        }
        builder = self.method_b.RecordBuilder(official)
        parent_a = builder.add_artifact(official["artifact-a"])
        parent_b = builder.add_artifact(official["artifact-b"])
        builder.add_discovered(
            "asset",
            {
                "apk_artifact_id": "artifact-a",
                "archive_entry_record_id": parent_b,
                "path": "assets/x",
                "sha256": "2" * 64,
                "size_bytes": 1,
            },
            "artifact-a",
            additional_parent_ids=(parent_b, parent_a, parent_b),
        )
        asset = next(
            row
            for row in builder.records_for_candidate()
            if row["record_type"] == "asset"
        )
        self.assertEqual(asset["parent_record_ids"], sorted(set(asset["parent_record_ids"])))

    def test_nested_frozen_apk_parent_index_is_exact_container_path_hash_and_size(self) -> None:
        official = {
            "base": {
                "artifact_id": "base",
                "kind": "apk_member",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "base.apk"},
            },
            "extracted-dex:classes.dex": {
                "artifact_id": "extracted-dex:classes.dex",
                "kind": "dex",
                "sha256": "1" * 64,
                "size_bytes": 123,
                "source": {"type": "file", "path": "/frozen/evidence/apk/classes.dex"},
            },
        }
        builder = self.method_b.RecordBuilder(official)
        base_parent = builder.add_artifact(official["base"])
        dex_parent = builder.add_artifact(official["extracted-dex:classes.dex"])
        index = self.method_b.build_nested_frozen_occurrence_index(
            official,
            builder.artifact_record_ids,
        )
        self.assertEqual(
            self.method_b.nested_frozen_parent_ids(
                index,
                container_artifact_id="xapk-apk:com.hikvision.thermalGoogle.apk",
                path="classes.dex",
                sha256="1" * 64,
                size_bytes=123,
            ),
            (dex_parent,),
        )
        self.assertEqual(
            self.method_b.nested_frozen_parent_ids(
                index,
                container_artifact_id="xapk-apk:other.apk",
                path="classes.dex",
                sha256="1" * 64,
                size_bytes=123,
            ),
            (),
        )
        archive_payload = {
            "configuration_kind": "apk_archive_entry",
            "container_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "central_directory_ordinal": 0,
            "path": "classes.dex",
            "compression_method": 8,
            "crc32": 1,
            "compressed_size_bytes": 99,
            "uncompressed_size_bytes": 123,
            "sha256": "1" * 64,
        }
        builder.add_discovered(
            "configuration",
            archive_payload,
            "base",
            additional_parent_ids=self.method_b.nested_frozen_parent_ids(
                index,
                container_artifact_id=archive_payload["container_artifact_id"],
                path=archive_payload["path"],
                sha256=archive_payload["sha256"],
                size_bytes=archive_payload["uncompressed_size_bytes"],
            ),
        )
        archive = next(
            row
            for row in builder.records_for_candidate()
            if row["record_type"] == "configuration"
        )
        self.assertEqual(archive["parent_record_ids"], sorted([base_parent, dex_parent]))

    def test_android_component_parents_include_all_declarations_and_alias_target(self) -> None:
        android_ns = self.method_b.V5_ANDROID_NS

        def attr(namespace: str, name: str, value: str) -> dict[str, object]:
            return {
                "attribute_ordinal": 0,
                "qname": self.method_b.v5_qname_value(namespace, name),
                "raw_value": value,
                "resource_id": None,
                "data_type": 3,
                "data": 0,
                "typed_string": value,
            }

        manifest_payload = {
            "apk_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "event_ordinal": 0,
            "qname": "Q{}manifest",
            "xpath": "axmlpath:/Q{}manifest[1]",
            "parent_manifest_node_record_id": None,
            "attributes": [attr("", "package", "pkg")],
        }
        activity_one = {
            "apk_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "event_ordinal": 1,
            "qname": "Q{}activity",
            "xpath": "axmlpath:/Q{}manifest[1]/Q{}activity[1]",
            "parent_manifest_node_record_id": self.method_b.record_id("manifest_node", manifest_payload),
            "attributes": [attr(android_ns, "name", ".A")],
        }
        activity_two = {**activity_one, "event_ordinal": 2, "xpath": "axmlpath:/Q{}manifest[1]/Q{}activity[2]"}
        alias = {
            "apk_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "event_ordinal": 3,
            "qname": "Q{}activity-alias",
            "xpath": "axmlpath:/Q{}manifest[1]/Q{}activity-alias[1]",
            "parent_manifest_node_record_id": self.method_b.record_id("manifest_node", manifest_payload),
            "attributes": [attr(android_ns, "name", ".Alias"), attr(android_ns, "targetActivity", ".A")],
        }
        manifest_records = [
            {"record_id": self.method_b.record_id("manifest_node", payload), "payload": payload}
            for payload in (manifest_payload, activity_one, activity_two, alias)
        ]
        declaration_index = self.method_b.build_android_component_declaration_index(manifest_records)
        activity_payload = {
            "package": "pkg",
            "kind": "activity",
            "name": "pkg.A",
            "enabled": True,
            "exported": False,
            "permission": None,
            "process": "pkg",
            "direct_boot_aware": False,
            "foreground_service_type": None,
            "target_activity": None,
            "effective_target_sdk": 35,
        }
        alias_payload = {
            **activity_payload,
            "kind": "activity_alias",
            "name": "pkg.Alias",
            "target_activity": "pkg.A",
        }
        component_ids = {
            ("activity", "pkg", "pkg.A"): self.method_b.record_id("android_component", activity_payload),
            ("activity_alias", "pkg", "pkg.Alias"): self.method_b.record_id("android_component", alias_payload),
        }
        activity_parents = self.method_b.android_component_additional_parent_ids(
            activity_payload,
            declaration_index,
            component_ids,
        )
        self.assertEqual(
            activity_parents,
            tuple(sorted([manifest_records[1]["record_id"], manifest_records[2]["record_id"]])),
        )
        alias_parents = self.method_b.android_component_additional_parent_ids(
            alias_payload,
            declaration_index,
            component_ids,
        )
        self.assertEqual(
            alias_parents,
            tuple(sorted([manifest_records[3]["record_id"], component_ids[("activity", "pkg", "pkg.A")]])),
        )

    def test_android_namespace_spoof_does_not_create_component_or_alias_parent(self) -> None:
        android_ns = self.method_b.V5_ANDROID_NS

        def attr(namespace: str, name: str, value: str) -> dict[str, object]:
            return {
                "attribute_ordinal": 0,
                "qname": self.method_b.v5_qname_value(namespace, name),
                "raw_value": value,
                "resource_id": None,
                "data_type": 3,
                "data": 0,
                "typed_string": value,
            }

        manifest_payload = {
            "apk_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "event_ordinal": 0,
            "qname": "Q{}manifest",
            "xpath": "axmlpath:/Q{}manifest[1]",
            "parent_manifest_node_record_id": None,
            "attributes": [attr("", "package", "pkg")],
        }
        spoofed_activity = {
            "apk_artifact_id": "xapk-apk:com.hikvision.thermalGoogle.apk",
            "event_ordinal": 1,
            "qname": "Q{}activity",
            "xpath": "axmlpath:/Q{}manifest[1]/Q{}activity[1]",
            "parent_manifest_node_record_id": self.method_b.record_id("manifest_node", manifest_payload),
            "attributes": [attr("", "name", ".Spoof")],
        }
        real_activity = {**spoofed_activity, "event_ordinal": 2, "attributes": [attr(android_ns, "name", ".Real")]}
        custom_alias = {
            **spoofed_activity,
            "event_ordinal": 3,
            "qname": "Q{}activity-alias",
            "xpath": "axmlpath:/Q{}manifest[1]/Q{}activity-alias[1]",
            "attributes": [attr(android_ns, "name", ".Alias"), attr("urn:custom", "targetActivity", ".Real")],
        }
        manifest_records = [
            {"record_id": self.method_b.record_id("manifest_node", payload), "payload": payload}
            for payload in (manifest_payload, spoofed_activity, real_activity, custom_alias)
        ]
        declaration_index = self.method_b.build_android_component_declaration_index(manifest_records)
        self.assertNotIn(("activity", "pkg", "pkg.Spoof"), declaration_index)
        self.assertIn(("activity", "pkg", "pkg.Real"), declaration_index)
        alias_payload = {
            "package": "pkg",
            "kind": "activity_alias",
            "name": "pkg.Alias",
            "enabled": True,
            "exported": False,
            "permission": None,
            "process": "pkg",
            "direct_boot_aware": False,
            "foreground_service_type": None,
            "target_activity": "",
            "effective_target_sdk": 35,
        }
        with self.assertRaises(self.method_b.ProducerError):
            self.method_b.android_component_additional_parent_ids(
                alias_payload,
                declaration_index,
                {("activity", "pkg", "pkg.Real"): "INV-TARGET"},
            )

    def test_v10_resource_configuration_source_and_parent_follow_linked_resource(self) -> None:
        official = {
            "artifact-a": {
                "artifact_id": "artifact-a",
                "kind": "apk_member",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "a"},
            }
        }
        resource_payload = {
            "apk_artifact_id": "artifact-a",
            "entry_id": 1,
            "entry_name": "fixture_1",
            "package_chunk_ordinal": 0,
            "package_id": 127,
            "package_name": "fixture",
            "raw_type_id": 1,
            "resource_id": "0x7f010001",
            "type_id": 1,
            "type_id_offset": 0,
            "type_name": "string",
        }
        resource_record_id = self.method_b.record_id("resource", resource_payload)
        configuration_payload = {
            "configuration": {"bytes_hex": "04000000", "size_bytes": 4},
            "configuration_kind": "resource_configuration",
            "entry_encoding": "full",
            "entry_flags": 0,
            "entry_id": 1,
            "entry_index_ordinal": 1,
            "key_index": 1,
            "package_chunk_ordinal": 0,
            "resource_record_id": resource_record_id,
            "type_chunk_ordinal": 0,
            "value": {
                "data": 0,
                "data_type": 16,
                "kind": "scalar",
                "string_value": None,
            },
        }
        self.assertEqual(
            set(configuration_payload),
            {
                "configuration",
                "configuration_kind",
                "entry_encoding",
                "entry_flags",
                "entry_id",
                "entry_index_ordinal",
                "key_index",
                "package_chunk_ordinal",
                "resource_record_id",
                "type_chunk_ordinal",
                "value",
            },
        )
        builder = self.method_b.RecordBuilder(official)
        frozen_parent = builder.add_artifact(official["artifact-a"])
        actual_resource_id = builder.add_discovered("resource", resource_payload, "artifact-a")
        self.assertEqual(actual_resource_id, resource_record_id)
        builder.add_discovered(
            "configuration",
            configuration_payload,
            resource_payload["apk_artifact_id"],
            additional_parent_ids=(resource_record_id,),
        )
        records = builder.records_for_candidate()
        by_variant = {self.method_b.candidate_payload_variant(row): row for row in records}
        configuration = by_variant["configuration:resource_configuration"]
        resource = by_variant["resource"]
        self.assertEqual(configuration["source_artifact_id"], resource["payload"]["apk_artifact_id"])
        self.assertEqual(configuration["parent_record_ids"], sorted([frozen_parent, resource_record_id]))
        self.assertNotIn("apk_artifact_id", configuration["payload"])
        self.assertNotIn("container_artifact_id", configuration["payload"])
        self.assertNotIn("library_artifact_id", configuration["payload"])

    def test_v10_resource_configuration_link_is_order_independent(self) -> None:
        official = {
            "artifact-a": {
                "artifact_id": "artifact-a",
                "kind": "apk_member",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "a"},
            }
        }
        builder = self.method_b.RecordBuilder(official)
        builder.add_artifact(official["artifact-a"])
        selected = None
        for entry_id in range(1, 200):
            resource_payload = {
                "apk_artifact_id": "artifact-a",
                "entry_id": entry_id,
                "entry_name": f"fixture_{entry_id}",
                "package_chunk_ordinal": 0,
                "package_id": 127,
                "package_name": "fixture",
                "raw_type_id": 1,
                "resource_id": f"0x7f01{entry_id:04x}",
                "type_id": 1,
                "type_id_offset": 0,
                "type_name": "string",
            }
            resource_record_id = self.method_b.record_id("resource", resource_payload)
            configuration_payload = {
                "configuration": {"bytes_hex": "04000000", "size_bytes": 4},
                "configuration_kind": "resource_configuration",
                "entry_encoding": "full",
                "entry_flags": 0,
                "entry_id": entry_id,
                "entry_index_ordinal": entry_id,
                "key_index": entry_id,
                "package_chunk_ordinal": 0,
                "resource_record_id": resource_record_id,
                "type_chunk_ordinal": 0,
                "value": {"data": 0, "data_type": 16, "kind": "scalar", "string_value": None},
            }
            configuration_record_id = self.method_b.record_id("configuration", configuration_payload)
            if configuration_record_id < resource_record_id:
                selected = (resource_payload, configuration_payload, resource_record_id, configuration_record_id)
                break
        self.assertIsNotNone(selected, "fixture must prove configuration can sort before resource")
        resource_payload, configuration_payload, resource_record_id, configuration_record_id = selected
        builder.add_discovered("resource", resource_payload, "artifact-a")
        builder.add_discovered(
            "configuration",
            configuration_payload,
            "artifact-a",
            additional_parent_ids=(resource_record_id,),
        )
        records = builder.records_for_candidate()
        ids = [row["record_id"] for row in records]
        self.assertLess(ids.index(configuration_record_id), ids.index(resource_record_id))
        configuration = next(row for row in records if row["record_id"] == configuration_record_id)
        self.assertIn(resource_record_id, configuration["parent_record_ids"])

    def test_v10_static_sources_have_no_stale_prior_version_markers_except_android_abi(self) -> None:
        stale = []
        for path in (METHOD_B_PATH, Path(__file__)):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "arm64-v8a" in line:
                    continue
                if ("v" + "9") in line or ("V" + "9") in line:
                    stale.append((path.name, lineno, line.strip()))
        self.assertEqual(stale, [])

    def test_facts_and_source_rows_follow_fact_id_positional_order(self) -> None:
        records = [
            {
                "record_id": "INV-" + "B" * 64,
                "record_type": "feature",
                "scope_key": "{}",
                "artifact_id": None,
                "source_artifact_id": "artifact-a",
                "sha256": None,
                "size_bytes": None,
                "official_source": None,
                "parent_record_ids": [],
                "payload": {},
            },
            {
                "record_id": "INV-" + "A" * 64,
                "record_type": "feature",
                "scope_key": "{}2",
                "artifact_id": None,
                "source_artifact_id": "artifact-a",
                "sha256": None,
                "size_bytes": None,
                "official_source": None,
                "parent_record_ids": [],
                "payload": {},
            },
        ]
        document = self.method_b.build_candidate_raw_attachment(
            "features",
            "raw/manifests.json",
            "android.normalized_record",
            records,
            ["artifact-a"],
            [],
        )
        normalized = [row for row in document["facts"] if row["fact_kind"] == "normalized"]
        self.assertEqual(document["schema_version"], "g002-raw-attachment/v1")
        self.assertEqual(document["facts"], sorted(document["facts"], key=lambda row: row["fact_id"]))
        self.assertEqual(
            [row["source_row_index"] for row in normalized],
            list(range(len(document["source_rows"]))),
        )
        self.assertEqual(
            [document["source_rows"][row["source_row_index"]]["source_locator"] for row in normalized],
            [f"raw/manifests.json#/source_rows/{i}" for i in range(len(normalized))],
        )

    def test_v10_orphan_parent_equation_and_jni_counts(self) -> None:
        counts = self.method_b.v10_expected_counts(self.contract)
        self.assertEqual(counts["jni_edge"], 3395)
        self.assertEqual(counts["orphan_java_export"], 129)
        self.assertEqual(
            self.method_b.orphan_java_export_parent_ids(
                "INV-FROZEN-LIBRARY",
                "INV-NATIVE-EXPORT",
            ),
            ["INV-FROZEN-LIBRARY", "INV-NATIVE-EXPORT"],
        )

    def test_v10_includes_all_92_unnamed_nonzero_stt_section_symbols(self) -> None:
        unnamed_section = {
            "dynamic_symbol_index": "7",
            "value": "1000",
            "size": "0",
            "type": "SECTION",
            "binding": "LOCAL",
            "visibility": "DEFAULT",
            "section": "7",
            "name": "",
        }
        reserved_zero = {**unnamed_section, "dynamic_symbol_index": "0"}
        self.assertTrue(self.method_b.canonical_symbol_included(unnamed_section))
        self.assertFalse(self.method_b.canonical_symbol_included(reserved_zero))
        self.assertEqual(self.method_b.v10_expected_counts(self.contract)["unnamed_stt_section"], 92)

    def test_v10_callsite_membership_oracles_total_1372_and_239(self) -> None:
        oracles = self.method_b.v10_callsite_oracles(self.contract)
        self.assertEqual(sum(row["reflection_target_count"] for row in oracles), 1372)
        self.assertEqual(sum(row["dynamic_loader_count"] for row in oracles), 239)
        self.assertEqual(
            [row["artifact_id"] for row in oracles],
            [
                "extracted-dex:classes.dex",
                "extracted-dex:classes2.dex",
                "extracted-dex:classes3.dex",
                "extracted-dex:classes4.dex",
            ],
        )
        for row in oracles:
            self.assertRegex(row["reflection_target_payloads_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["dynamic_loader_payloads_sha256"], r"^[0-9a-f]{64}$")

    def test_complete_v10_family_membership_set_is_exactly_pinned(self) -> None:
        actual = {
            row["family"]: (
                row["count"],
                row["payloads_sha256"],
                row["record_ids_sha256"],
            )
            for row in self.contract["provenance"]["whole_candidate"]["family_memberships"]
        }
        self.assertEqual(len(actual), 21)
        self.assertEqual(actual, EXPECTED_FAMILY_MEMBERSHIPS)
        self.assertEqual(
            set(self.contract["provenance"]["whole_candidate"]["required_family_variants"]),
            set(EXPECTED_FAMILY_MEMBERSHIPS),
        )

    def test_private_post_write_summary_uses_validated_v10_universes(self) -> None:
        tree = ast.parse(METHOD_B_PATH.read_text(encoding="utf-8"))
        validator = function_node(tree, "validate_private_output_remediated")
        returned = next(
            node.value
            for node in ast.walk(validator)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        )
        values = {
            key.value: ast.unparse(value)
            for key, value in zip(returned.keys, returned.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertEqual(values["apk_members"], "coverage['apk_members']")
        self.assertEqual(values["dex_files"], "coverage['dex_files']")
        self.assertEqual(values["native_libraries"], "coverage['native_libraries']")


    def test_v10_dex_derivation_uses_byte_derived_native_declaration_digest(self) -> None:
        records = [
            {
                "record_id": "INV-" + "A" * 64,
                "record_type": "class",
                "payload": {"dex_artifact_id": "extracted-dex:classes.dex", "descriptor": "LA;"},
            }
        ]
        memberships = [
            {
                "family": "class",
                "count": 1,
                "payloads_sha256": "0" * 64,
                "record_ids_sha256": "1" * 64,
            }
        ]
        byte_digest = "92908f34d2cb5998b778d6beacdd14e3dbccc64b34825246fe41db7b81142a0d"
        groups = self.method_b.v10_derivation_groups(
            self.contract,
            memberships,
            records,
            dex_native_declarations_sha256=byte_digest,
        )
        self.assertEqual(groups["raw/dex.json"]["native_declarations_sha256"], byte_digest)
        self.assertNotEqual(
            groups["raw/dex.json"]["native_declarations_sha256"],
            self.contract["jni"]["byte_membership_oracles"]["declaration_membership_sha256"],
        )

    def test_canonical_writer_emits_complete_deterministic_v10_topology(self) -> None:
        official = {
            "artifact-a": {
                "artifact_id": "artifact-a",
                "kind": "apk_member",
                "sha256": "0" * 64,
                "size_bytes": 1,
                "source": {"type": "file", "path": "a"},
            }
        }
        builder = self.method_b.RecordBuilder(official)
        builder.add_artifact(official["artifact-a"])
        records = builder.records_for_candidate()
        roots = [SCRATCH_ROOT / "writer-regression-1", SCRATCH_ROOT / "writer-regression-2"]
        for index, root in enumerate(roots, start=1):
            self.method_b.write_canonical_candidate_bundle(
                candidate_root=root,
                artifact_set_id="artifact-set",
                records=records,
                source_records=[],
                canonical_inventory_hash="0" * 64,
                source_index_hash="1" * 64,
                commands=[
                    shlex.join(
                        [
                            "python3",
                            "tools/hik_whole_apk/g002_method_b.py",
                            "--out",
                            str(SCRATCH_ROOT / f"private-{index}"),
                            "--contract",
                            str(CONTRACT_PATH),
                            "--candidate-root",
                            str(root),
                        ]
                    )
                ],
                timestamp="2026-07-20T00:00:00Z",
                generated_at="2026-07-20T00:00:00Z",
                contract=self.contract,
                enforce_complete=False,
            )
        maps = [recursive_hash_map(root) for root in roots]
        self.assertEqual(set(maps[0]), EXPECTED_CANDIDATE_PATHS)
        self.assertEqual(maps[0], maps[1])
        self.assertEqual(
            json.loads((roots[0] / "bundle.json").read_text(encoding="utf-8"))["schema"],
            "g002-candidate-bundle/v2",
        )
        self.assertEqual(
            json.loads((roots[0] / "inventory.json").read_text(encoding="utf-8"))["schema"],
            "g002-normalized-inventory/v2",
        )
        source_index = json.loads((roots[0] / "source-index.json").read_text(encoding="utf-8"))
        self.assertEqual(set(source_index), {"schema_version", "bundle_id", "rows"})
        self.assertEqual(source_index["schema_version"], "g002-source-index/v2")
        command = json.loads((roots[0] / "command.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(command),
            {"schema", "bundle_id", "operator_id", "argv", "exit_code", "started_at", "ended_at"},
        )
        self.assertEqual(
            command["argv"],
            [
                "python3",
                "tools/hik_whole_apk/g002_method_b.py",
                "--out",
                str(self.method_b.DEFAULT_OUT),
                "--contract",
                str(CONTRACT_PATH),
                "--candidate-root",
                self.method_b.display_path(self.method_b.DEFAULT_CANDIDATE_ROOT),
            ],
        )


if __name__ == "__main__":
    unittest.main()
