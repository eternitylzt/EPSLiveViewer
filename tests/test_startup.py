"""Keep the file-association relay light and dependency discovery reusable."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eps_renderer import EpsRenderer


class StartupTests(unittest.TestCase):
    def test_relay_does_not_load_document_or_optional_tool_modules(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import main,sys; assert not set(('viewer','pypdf','video_dialog',"
             "'color_dialog','update_checker')).intersection(sys.modules)"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ghostscript_cache_revalidates_and_honors_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "gs"
            executable.touch()
            renderer = EpsRenderer()
            try:
                with patch("eps_renderer.find_ghostscript", return_value=executable) as find:
                    self.assertEqual(renderer.ghostscript_path, executable)
                    self.assertEqual(renderer.ghostscript_path, executable)
                    self.assertEqual(find.call_count, 1)
                    renderer.set_ghostscript_path(str(executable))
                    self.assertEqual(renderer.ghostscript_path, executable)
                    self.assertEqual(find.call_count, 2)
                    executable.unlink()
                    find.return_value = None
                    self.assertIsNone(renderer.ghostscript_path)
                    self.assertEqual(find.call_count, 3)
            finally:
                renderer.cache.cleanup()


if __name__ == "__main__":
    unittest.main()
