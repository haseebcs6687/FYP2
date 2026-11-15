"""
=============================================================================
EduGen - JavaScript Syntax Checker Test Suite (scripts/test_js.py)
=============================================================================
Validates that every JavaScript file in static/js/ has valid syntax without errors.
Uses `node --check` if Node.js is present; else uses quickjs if available;
if neither is available, fails immediately with an informative message.
Also verifies that the syntax-check engine correctly detects injected syntax errors.
=============================================================================
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_JS_DIR = BASE_DIR / "static" / "js"


def get_js_checker():
    """
    Returns (engine_name, check_callable) where check_callable(file_path) -> (bool, str).
    Returns (True, "") on valid syntax or (False, error_message) on syntax errors.
    If neither node nor quickjs is available, raises RuntimeError.
    """
    node_path = shutil.which("node")
    if node_path:
        def check_node(file_path):
            res = subprocess.run(
                [node_path, "--check", str(file_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if res.returncode == 0:
                return True, ""
            return False, res.stderr or res.stdout or f"Syntax error (code {res.returncode})"
        return "node", check_node

    try:
        import quickjs
        def check_quickjs(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                code = f.read()
            ctx = quickjs.Context()
            try:
                ctx.eval(f"(function(){{\n{code}\n}})")
                return True, ""
            except Exception as exc:
                return False, str(exc)
        return "quickjs", check_quickjs
    except ImportError:
        pass

    raise RuntimeError(
        "Neither Node.js ('node --check') nor python-quickjs is available. "
        "Cannot perform JavaScript syntax verification."
    )


class TestJavaScriptSyntax(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            name, fn = get_js_checker()
            cls.engine_name = name
            cls.checker = staticmethod(fn)
        except RuntimeError as exc:
            cls.engine_name = None
            cls.checker = None
            cls.engine_error = str(exc)

    def test_checker_available(self):
        """Engine must be available; skipping is strictly forbidden."""
        if not getattr(self, "checker", None):
            self.fail(f"JavaScript syntax check engine unavailable: {getattr(self, 'engine_error', 'Unknown error')}")
        self.assertIn(self.engine_name, ("node", "quickjs"))

    def test_syntax_checker_catches_injected_error(self):
        """Proof of detection: inject a deliberate syntax error and assert detection."""
        if not getattr(self, "checker", None):
            self.fail(f"JavaScript syntax check engine unavailable: {getattr(self, 'engine_error', 'Unknown error')}")

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tmp:
            tmp.write("function brokenSyntax( { return let 123; } finally { }")
            tmp_path = Path(tmp.name)

        try:
            is_valid, err = self.checker(tmp_path)
            self.assertFalse(is_valid, "Checker failed to catch deliberate syntax error!")
            self.assertTrue(len(err.strip()) > 0, "Checker failed to produce error diagnostics.")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def test_all_static_js_files_syntax(self):
        """Syntax-check every file in static/js/."""
        if not getattr(self, "checker", None):
            self.fail(f"JavaScript syntax check engine unavailable: {getattr(self, 'engine_error', 'Unknown error')}")

        js_files = list(STATIC_JS_DIR.glob("**/*.js"))
        self.assertGreater(len(js_files), 0, f"No JavaScript files found in {STATIC_JS_DIR}")

        for js_file in js_files:
            rel_name = js_file.relative_to(BASE_DIR)
            is_valid, err = self.checker(js_file)
            self.assertTrue(
                is_valid,
                f"JavaScript syntax error in {rel_name}:\n{err}",
            )

    def test_charts_edge_cases_and_banned_strings(self):
        """Render all EGCharts helpers across edge cases and assert no banned strings."""
        node_path = shutil.which("node")
        if not node_path:
            self.skipTest("Node.js not available for rendering execution check.")

        node_script = """
        const EGCharts = require('./static/js/charts.js');
        const banned = [
            'rule r', 'adaptive content agent', 'agent pipeline', 'cosine', '.pdf',
            'ollama', 'embedder', 'passages indexed', 'how this quiz is built',
            'fixed question bank', 'evidence behind'
        ];

        const outputs = [
            EGCharts.ring(0, 0),
            EGCharts.ring(null, 100),
            EGCharts.ring(120, 100, {label: '<b>bold</b>', sub: '<script>'}),
            EGCharts.bars([]),
            EGCharts.bars([{label: 'A', value: 0}, {label: 'B', value: 0}]),
            EGCharts.bars([{label: 'Over', value: 150}], {max: 100}),
            EGCharts.bars([{label: 'X'.repeat(300), value: 50}]),
            EGCharts.bars([{label: '<script>alert(1)</script>', value: 20}]),
            EGCharts.line([]),
            EGCharts.line([75]),
            EGCharts.line([0, 0]),
            EGCharts.line([20, 50, 80], {refLine: 70, labels: ['<tag1>', '<tag2>', '<tag3>']}),
            EGCharts.stacked([]),
            EGCharts.stacked([{label: 'Zero', value: 0}]),
            EGCharts.stacked([{label: '<script>', value: 10}, {label: 'B', value: 34}], {total: 44}),
            EGCharts.spark([]),
            EGCharts.spark([50]),
            EGCharts.spark([0, 0, 0]),
            EGCharts.spark([10, 40, 20, 80]),
            EGCharts.statCard({value: '<val>', unit: '<unit>', label: '<label>', sub: '<sub>', chart: '<svg></svg>'})
        ];

        outputs.forEach((out, i) => {
            if (typeof out !== 'string' || out.length === 0) {
                throw new Error('Output ' + i + ' is not a valid non-empty string');
            }
            if (out.includes('<script>') || out.includes('<tag1>') || out.includes('<val>')) {
                throw new Error('Output ' + i + ' contains unescaped HTML characters');
            }
            for (const b of banned) {
                if (out.toLowerCase().includes(b)) {
                    throw new Error('Output ' + i + ' contains banned string: ' + b);
                }
            }
        });
        console.log('ALL_EDGE_CASES_OK');
        """

        res = subprocess.run(
            [node_path, "-e", node_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(BASE_DIR),
        )
        self.assertEqual(res.returncode, 0, f"Node script execution failed:\n{res.stderr}")
        self.assertIn("ALL_EDGE_CASES_OK", res.stdout)


if __name__ == "__main__":
    unittest.main()
