import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autodrive_console.case_store import CaseStore
from autodrive_console.case_workspace import CasePackageError, CaseWorkspace


class CaseWorkspaceTests(unittest.TestCase):
    filename = "园区_1_2_3_4.json"

    def _case(self, root: Path):
        task_dir = root / "tasks"
        task_dir.mkdir()
        target = task_dir / self.filename
        target.write_text('{"tasks": []}\n', encoding="utf-8")
        return task_dir, CaseStore(task_dir).get_case(self.filename)

    def test_metadata_is_persistent_without_rewriting_on_every_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir, case = self._case(root)
            workspace = CaseWorkspace(root / "config", task_dir)
            first = workspace.describe(case)
            second = workspace.describe(case)
            self.assertEqual(first["updated_at"], second["updated_at"])
            saved = workspace.update(case, {"version": "1.2", "lifecycle": "local_verified", "tags": ["电梯", "回环"], "summary": "电梯回环验证"})
            self.assertEqual(saved["version"], "1.2")
            self.assertEqual(workspace.load()["cases"][case.id]["tags"], ["电梯", "回环"])

    def test_export_import_round_trip_is_portable_but_no_overwrite(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as target_directory:
            source_root, target_root = Path(source_directory), Path(target_directory)
            task_dir, case = self._case(source_root)
            source = CaseWorkspace(source_root / "config", task_dir)
            source.update(case, {"version": "0.6", "lifecycle": "published", "tags": ["室内", "回环"], "summary": "可交付的回环用例"})
            filename, package = source.export_package(case, "室内回环")
            self.assertTrue(filename.endswith(".rycase.zip"))
            target_dir = target_root / "tasks"
            result = CaseWorkspace(target_root / "config", target_dir).import_package(package)
            self.assertEqual(result["status"], "imported")
            self.assertEqual((target_dir / self.filename).read_text(encoding="utf-8"), '{"tasks": []}\n')
            same = CaseWorkspace(target_root / "config", target_dir).import_package(package)
            self.assertEqual(same["status"], "already_present")
            (target_dir / self.filename).write_text('{"tasks": ["different"]}\n', encoding="utf-8")
            with self.assertRaisesRegex(CasePackageError, "同名但内容不同"):
                CaseWorkspace(target_root / "config", target_dir).import_package(package)

    def test_rejects_unexpected_or_tampered_package_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_dir, case = self._case(root)
            workspace = CaseWorkspace(root / "config", task_dir)
            _, package = workspace.export_package(case)
            archive = zipfile.ZipFile(io.BytesIO(package))
            broken = io.BytesIO()
            with zipfile.ZipFile(broken, "w") as output:
                for item in archive.infolist():
                    output.writestr(item.filename, archive.read(item.filename))
                output.writestr("unexpected.txt", "no")
            with self.assertRaisesRegex(CasePackageError, "只能包含"):
                workspace.import_package(broken.getvalue())

            manifest = {"schema": 1, "type": "ry-aletheia.test-case", "task_filename": self.filename, "task_sha256": "0" * 64}
            tampered = io.BytesIO()
            with zipfile.ZipFile(tampered, "w") as output:
                output.writestr("manifest.json", json.dumps(manifest))
                output.writestr("task.json", "{}")
                output.writestr("checksums.sha256", "0" * 64 + "  manifest.json\n" + "0" * 64 + "  task.json\n")
            with self.assertRaisesRegex(CasePackageError, "校验和不匹配"):
                workspace.import_package(tampered.getvalue())


if __name__ == "__main__":
    unittest.main()
