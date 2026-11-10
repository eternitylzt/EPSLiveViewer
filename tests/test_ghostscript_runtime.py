"""Bundled discovery must not depend on, or alter, installed Ghostscript."""

import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import config
import ghostscript_runtime
from diagnostics import Diagnostics
from eps_renderer import EpsRenderer


class GhostscriptRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="eps_gs_")
        self.addCleanup(self.temporary.cleanup)
        # CI may provide an 8.3 TEMP path (RUNNER~1); compare canonical paths.
        self.root = Path(self.temporary.name).resolve() / "runtime with spaces 中文"
        self.root.mkdir()
        self.enterContext(patch.object(ghostscript_runtime, "__file__", str(self.root / "ghostscript_runtime.py")))
        self.enterContext(patch.object(sys, "_MEIPASS", None, create=True))

    @staticmethod
    def executable(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def bundle(self):
        name = "gswin64c.exe" if sys.platform == "win32" else "gs"
        return self.executable(self.root / "vendor" / "ghostscript" / "bin" / name)

    def test_source_and_frozen_layouts_select_native_executable(self):
        for platform, filename in (("win32", "gswin64c.exe"), ("linux", "gs"), ("darwin", "gs")):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                source = self.executable(self.root / "vendor" / "ghostscript" / "bin" / filename)
                self.assertEqual(ghostscript_runtime.bundled_ghostscript_path(), source)
                frozen = self.root / "frozen"
                target = self.executable(frozen / "ghostscript" / "bin" / filename)
                with patch.object(sys, "_MEIPASS", str(frozen)):
                    self.assertEqual(ghostscript_runtime.bundled_ghostscript_path(), target)

    def test_explicit_override_wins_and_bundle_precedes_installed_version(self):
        bundled = self.bundle()
        external = self.executable(self.root / "external" / "gs")
        with patch.dict(os.environ, {"GSWIN64C": str(external)}), patch.object(config.shutil, "which") as which:
            self.assertEqual(config.find_ghostscript(str(external)), external)
            self.assertEqual(config.find_ghostscript(), bundled)
            self.assertEqual(config.find_ghostscript(str(self.root / "missing")), bundled)
            which.assert_not_called()

    def test_absent_bundle_keeps_external_environment_and_path_discovery(self):
        external = self.executable(self.root / "external" / "gs")
        with patch.dict(os.environ, {"GSWIN64C": str(external)}):
            self.assertEqual(config.find_ghostscript(), external)
        with patch.dict(os.environ, {"GSWIN64C": "", "GSWIN32C": ""}), patch.object(config.shutil, "which", return_value=str(external)):
            self.assertEqual(config.find_ghostscript(), external)

    def test_legacy_settings_drop_external_path_and_preserve_preferences(self):
        bundled = self.bundle()
        external = self.executable(self.root / "old-installation" / "gs")
        manager = config.ConfigManager()
        manager.base_dir = self.root
        manager.path = self.root / "config.json"
        manager.path.write_text(json.dumps({
            "ghostscript_path": str(external), "suppress_ghostscript_help": True,
            "auto_refresh": False, "export_dpi": 600, "language": "en",
        }), encoding="utf-8")
        preferences = manager.load()
        self.assertFalse(preferences.auto_refresh)
        self.assertEqual(preferences.export_dpi, 600)
        self.assertEqual(preferences.language, "en")
        manager.save(preferences)
        saved = json.loads(manager.path.read_text(encoding="utf-8"))
        self.assertNotIn("ghostscript_path", saved)
        self.assertNotIn("suppress_ghostscript_help", saved)
        renderer = EpsRenderer()
        self.addCleanup(renderer.cache.cleanup)
        self.assertEqual(renderer.ghostscript_path, bundled)

    def test_bundle_environment_is_private_and_preserves_system_font_context(self):
        bundled = self.bundle()
        external = self.executable(self.root / "external" / "gs")
        overrides = {
            "GS_LIB": "obsolete installation", "GS_OPTIONS": "-dNODISPLAY",
            "GS_FONTPATH": "obsolete fonts", "GS_DLL": "wrong.dll",
            "GS_DEVICE": "wrong device", "PATH": "test search path",
            "SYSTEMROOT": "test windows", "HOME": "test user home",
        }
        with patch.dict(os.environ, overrides):
            before = dict(os.environ)
            environment = ghostscript_runtime.ghostscript_environment(bundled)
            self.assertEqual(environment["GS_LIB"], os.pathsep.join(("%rom%Resource/Init/", "%rom%lib/")))
            for key in ("GS_OPTIONS", "GS_FONTPATH", "GS_DLL", "GS_DEVICE"):
                self.assertNotIn(key, environment)
            for key in ("PATH", "SYSTEMROOT", "HOME"):
                self.assertEqual(environment[key], before[key])
            self.assertIsNone(ghostscript_runtime.ghostscript_environment(external))
            self.assertEqual(dict(os.environ), before)

    def test_render_and_manual_diagnostics_use_the_same_child_environment(self):
        bundled = self.bundle()
        renderer = EpsRenderer()
        self.addCleanup(renderer.cache.cleanup)
        with patch.dict(os.environ, {"GS_OPTIONS": "-dNODISPLAY", "GS_DLL": "wrong.dll"}):
            expected = ghostscript_runtime.ghostscript_environment(bundled)
            with patch("eps_renderer.subprocess.Popen") as popen:
                popen.return_value.communicate.return_value = ("ok", "")
                popen.return_value.returncode = 0
                self.assertEqual(renderer._capture_ghostscript([str(bundled), "-h"], None), (0, "ok", ""))
                self.assertEqual(popen.call_args.kwargs["env"], expected)
            with patch("diagnostics.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Ghostscript", "")) as run:
                Diagnostics().report({}, bundled, probe=True)
                self.assertEqual(run.call_args.kwargs["env"], expected)
            external = self.executable(self.root / "external" / "gs")
            with patch("eps_renderer.subprocess.Popen") as popen:
                popen.return_value.communicate.return_value = ("ok", "")
                popen.return_value.returncode = 0
                renderer._capture_ghostscript([str(external), "-h"], None)
                self.assertIsNone(popen.call_args.kwargs["env"])

    def test_main_import_does_not_discover_or_load_bundled_runtime(self):
        result = subprocess.run(
            [sys.executable, "-c", "import main,sys; assert 'ghostscript_runtime' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaging_verifier_never_falls_back_to_system_ghostscript(self):
        from scripts.verify_bundled_ghostscript import verify

        with patch("scripts.verify_bundled_ghostscript.bundled_ghostscript_path", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "does not contain a Ghostscript runtime"):
                verify()


if __name__ == "__main__":
    unittest.main()
