from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "package_plugin", ROOT / "scripts" / "package_plugin.py"
)
assert SPEC and SPEC.loader
package_plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_plugin)


class PackagePluginTests(unittest.TestCase):
    def test_package_contains_manifest_and_required_runtime_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dist").mkdir()
            (root / "scripts").mkdir()
            (root / "manifest.json").write_text(
                json.dumps({"pluginId": "org.example.capy", "pluginVersion": "1.2.3"}),
                encoding="utf-8",
            )
            for name in (
                "README.md",
                "LICENSE",
                "LICENSE-AGPL-3.0.txt",
                "NOTICE.md",
                "plugin.py",
                "anyflows_plugin.py",
            ):
                (root / name).write_text(name, encoding="utf-8")

            previous_root = package_plugin.ROOT
            package_plugin.ROOT = root
            try:
                output = package_plugin.package(None)
            finally:
                package_plugin.ROOT = previous_root

            self.assertEqual(output.name, "capy-free-provider-1.2.3.afplugin")
            with zipfile.ZipFile(output) as archive:
                metadata = json.loads(archive.read("anyflows-plugin.json"))
                self.assertEqual(metadata["executablePath"], "plugin.py")
                self.assertEqual(metadata["manifest"]["pluginVersion"], "1.2.3")
                self.assertEqual(
                    set(archive.namelist()),
                    {
                        "anyflows-plugin.json",
                        "payload/",
                        "payload/README.md",
                        "payload/LICENSE",
                        "payload/LICENSE-AGPL-3.0.txt",
                        "payload/NOTICE.md",
                        "payload/manifest.json",
                        "payload/plugin.py",
                        "payload/anyflows_plugin.py",
                    },
                )

    def test_package_rejects_output_outside_dist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            previous_root = package_plugin.ROOT
            package_plugin.ROOT = root
            try:
                with self.assertRaisesRegex(ValueError, "dist"):
                    package_plugin.package(root / "outside.afplugin")
            finally:
                package_plugin.ROOT = previous_root

    def test_force_replaces_an_existing_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dist").mkdir()
            (root / "manifest.json").write_text(
                json.dumps({"pluginId": "org.example.capy", "pluginVersion": "1.2.3"}),
                encoding="utf-8",
            )
            for name in (
                "README.md", "LICENSE", "LICENSE-AGPL-3.0.txt", "NOTICE.md",
                "plugin.py", "anyflows_plugin.py",
            ):
                (root / name).write_text(name, encoding="utf-8")
            output = root / "dist" / "capy-free-provider-1.2.3.afplugin"
            output.write_bytes(b"old package")

            previous_root = package_plugin.ROOT
            package_plugin.ROOT = root
            try:
                with self.assertRaisesRegex(ValueError, "已存在"):
                    package_plugin.package(None)
                package_plugin.package(None, overwrite=True)
            finally:
                package_plugin.ROOT = previous_root

            with zipfile.ZipFile(output) as archive:
                self.assertIn("anyflows-plugin.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
