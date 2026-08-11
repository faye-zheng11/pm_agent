#!/usr/bin/env python3
"""项目资料入口的确定性契约测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.cockpit_server import (
    ContractError,
    material_is_active,
    material_version,
    normalize_material_version,
    normalize_upload_name,
    record_import,
)


class ProjectContextContract(unittest.TestCase):
    def make_project(self, root: Path) -> dict:
        project = root / "projects" / "demo"
        project.mkdir(parents=True)
        (project / "project.yaml").write_text("version: v0.1\n", encoding="utf-8")
        return {"id": "demo", "name": "Demo", "path": project}

    def test_upload_name_keeps_unicode_basename_and_drops_path(self):
        self.assertEqual(normalize_upload_name("/tmp/资料/中文 ZIP.zip"), "中文 ZIP.zip")

    def test_material_version_is_bounded(self):
        self.assertEqual(normalize_material_version("v0.2", "v0.1"), "v0.2")
        with self.assertRaises(ContractError):
            normalize_material_version("../escape", "v0.1")

    def test_legacy_import_gets_project_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))
            item = record_import(project, {"name": "资料.md", "path": ".workbench/uploads/资料.md"})
            self.assertEqual(item["material_version"], "v0.1")
            self.assertEqual(material_version(project, item), "v0.1")
            self.assertTrue(material_is_active(item))

    def test_import_index_is_json_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = self.make_project(Path(temp_dir))
            item = record_import(project, {"name": "资料.md", "material_version": "v0.2", "description": "当前版本"})
            index = json.loads((project["path"] / ".workbench" / "imports" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], "1.1")
            self.assertEqual(index["items"][0]["id"], item["id"])
            self.assertEqual(index["items"][0]["description"], "当前版本")


if __name__ == "__main__":
    unittest.main(verbosity=2)
