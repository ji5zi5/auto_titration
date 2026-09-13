import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android"
GRADLE = ROOT / ".tools" / "gradle" / "gradle-8.10.2" / "bin" / "gradle"
RELEASE_PRODUCING_TASKS = (
    "assembleRelease",
    "bundleRelease",
    "packageRelease",
    "packageReleaseBundle",
    "packageReleaseUniversalApk",
    "makeApkFromBundleForRelease",
    "extractApksForRelease",
    "extractApksFromBundleForRelease",
    "zipApksForRelease",
    "signReleaseBundle",
    "asarToCompatSplitsForRelease",
)


class G009ReleaseGovernanceTest(unittest.TestCase):
    maxDiff = None

    def run_gradle(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.setdefault("JAVA_HOME", str(ROOT / ".tools" / "jdk"))
        env.setdefault("ANDROID_HOME", str(ROOT / ".tools" / "android-sdk"))
        env.setdefault("ANDROID_SDK_ROOT", str(ROOT / ".tools" / "android-sdk"))
        return subprocess.run(
            [
                str(GRADLE),
                "--no-daemon",
                "--max-workers=1",
                *args,
            ],
            cwd=ANDROID,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )

    def test_legacy_boolean_cannot_authorize_any_available_release_route(self) -> None:
        task_inventory = self.run_gradle(":app:tasks", "--all")
        self.assertEqual(0, task_inventory.returncode, task_inventory.stdout)

        available_tasks = {
            line.split(maxsplit=1)[0]
            for line in task_inventory.stdout.splitlines()
            if line and not line[0].isspace()
        }
        self.assertTrue(
            set(RELEASE_PRODUCING_TASKS).issubset(available_tasks),
            sorted(set(RELEASE_PRODUCING_TASKS) - available_tasks),
        )
        self.assertFalse(
            {task for task in available_tasks if task.lower().startswith("publish")},
            "Any newly available publish route must be added to RELEASE_PRODUCING_TASKS",
        )

        for task in RELEASE_PRODUCING_TASKS:
            with self.subTest(task=task):
                result = self.run_gradle(
                    f":app:{task}",
                    "-PhikmicroRedistributionApproved=true",
                )

                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertIn("PUBLIC_DELIVERABLE_BLOCKED", result.stdout)
                self.assertIn(
                    "No Gradle boolean, including -PhikmicroRedistributionApproved=true",
                    result.stdout,
                )
                self.assertNotIn("BUILD SUCCESSFUL", result.stdout)

    def test_public_deliverable_audit_finds_manifest_bytes_and_vendor_paths(self) -> None:
        result = self.run_gradle(":app:auditPublicDeliverable")

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn("manifest-matching official bytes:", result.stdout)
        self.assertIn("official/vendor source path:", result.stdout)
        self.assertIn("Do not push/publish release APKs", result.stdout)

    def test_public_deliverable_archive_audit_matches_official_hash_at_renamed_path(
        self,
    ) -> None:
        official_dex = (
            ROOT
            / "mobile/android/app/src/main/assets/hikmicro/official/classes.dex"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "renamed-public-candidate.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.write(official_dex, "renamed/payload.bin")

            result = self.run_gradle(
                ":app:auditPublicDeliverable",
                f"-PpublicDeliverablePath={archive}",
            )

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(
            "manifest-matching official archive bytes: renamed/payload.bin",
            result.stdout,
        )

    def test_clean_synthetic_archive_passes_archive_only_audit_without_authorizing_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "clean-public-candidate.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("README.txt", "synthetic clean audit fixture\n")

            result = self.run_gradle(
                ":app:auditPublicDeliverableArchive",
                f"-PpublicDeliverablePath={archive}",
            )

        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("PUBLIC_DELIVERABLE_ARCHIVE_AUDIT_OK", result.stdout)
        self.assertIn(
            "This does not authorize the current source tree",
            result.stdout,
        )
        self.assertNotIn("PUBLIC_DELIVERABLE_BLOCKED", result.stdout)

    def test_debug_task_is_not_governance_blocked(self) -> None:
        result = self.run_gradle(":app:assembleDebug", "--dry-run")

        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn("PUBLIC_DELIVERABLE_BLOCKED", result.stdout)
        self.assertIn("BUILD SUCCESSFUL", result.stdout)


if __name__ == "__main__":
    unittest.main()
