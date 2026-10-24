import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from diskblame.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        self.db = Path(self.temp.name) / "diskblame.db"
        (self.root / "one.txt").write_bytes(b"1" * 100)
        (self.root / "two.txt").write_bytes(b"2" * 200)
        (self.root / "sub").mkdir()
        (self.root / "sub" / "three.txt").write_bytes(b"3" * 300)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args):
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--db", str(self.db), *args])
        return code, output.getvalue(), errors.getvalue()

    def snap(self):
        code, output, errors = self.run_cli(
            "snap", str(self.root), "--min-file-size", "1"
        )
        self.assertEqual(code, 0, errors)
        return output

    def test_snap_and_diff(self):
        first = self.snap()
        self.assertIn("snapshot 1", first)
        self.assertIn("files", first)

        (self.root / "four.txt").write_bytes(b"4" * 400)
        (self.root / "one.txt").write_bytes(b"1" * 5000)
        second = self.snap()
        self.assertIn("snapshot 2", second)
        self.assertIn("since 1", second)

        code, output, errors = self.run_cli(
            "diff", "--from", "1", "--to", "2", "--files"
        )
        self.assertEqual(code, 0, errors)
        self.assertIn("total", output)
        self.assertIn("four.txt", output)
        self.assertIn("one.txt", output)

    def test_diff_files(self):
        self.snap()
        (self.root / "four.txt").write_bytes(b"4" * 400)
        self.snap()
        code, output, errors = self.run_cli(
            "diff", "--from", "1", "--to", "2", "--files"
        )
        self.assertEqual(code, 0, errors)
        self.assertIn("directories", output)
        self.assertIn("files", output)
        self.assertIn("added", output)
        self.assertIn("four.txt", output)

    def test_top(self):
        self.snap()
        code, output, errors = self.run_cli("top", "--depth", "2")
        self.assertEqual(code, 0, errors)
        self.assertIn("sub", output)

    def test_top_files(self):
        self.snap()
        code, output, errors = self.run_cli("top", "--files")
        self.assertEqual(code, 0, errors)
        self.assertIn("three.txt", output)
        self.assertIn("two.txt", output)

    def test_why(self):
        self.snap()
        code, output, errors = self.run_cli("why", str(self.root / "sub" / "three.txt"))
        self.assertEqual(code, 0, errors)
        self.assertIn("type:", output)
        self.assertIn("size:", output)
        self.assertIn("verdict:", output)

    def test_prune(self):
        self.snap()
        (self.root / "four.txt").write_bytes(b"4" * 400)
        self.snap()
        code, output, errors = self.run_cli("prune", "--keep", "1")
        self.assertEqual(code, 0, errors)
        self.assertIn("deleted 1 snapshots", output)

    def test_chart(self):
        self.snap()
        code, output, errors = self.run_cli("chart", "--days", "0")
        self.assertEqual(code, 0, errors)
        self.assertIn(str(self.root), output)
        self.assertIn("#", output)

    def test_json_output(self):
        self.snap()
        code, output, errors = self.run_cli("top", "--json")
        self.assertEqual(code, 0, errors)
        payload = json.loads(output)
        self.assertEqual(payload["snapshot"]["id"], 1)
        self.assertTrue(payload["items"])

    def test_diff_requires_two_snapshots(self):
        self.snap()
        code, output, errors = self.run_cli("diff")
        self.assertEqual(code, 1)
        self.assertIn("need at least two snapshots", errors)


if __name__ == "__main__":
    unittest.main()
