import os
import tempfile
import unittest
from pathlib import Path

from diskblame.scan import _stat_size, scan, should_exclude


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "a.txt").write_bytes(b"a" * 100)
        (self.root / "dir").mkdir()
        (self.root / "dir" / "b.txt").write_bytes(b"b" * 200)
        (self.root / "dir" / "sub").mkdir()
        (self.root / "dir" / "sub" / "c.txt").write_bytes(b"c" * 300)
        (self.root / "empty").mkdir()
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_bytes(b"x" * 999)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_totals(self):
        result = scan(self.root, exclude=[".git"], min_file_size=1)
        expected_size = (
            _stat_size(os.stat(self.root / "a.txt"))
            + _stat_size(os.stat(self.root / "dir" / "b.txt"))
            + _stat_size(os.stat(self.root / "dir" / "sub" / "c.txt"))
        )
        self.assertEqual(result.total_size, expected_size)
        self.assertEqual(result.total_files, 3)
        self.assertEqual(result.total_dirs, 4)
        self.assertEqual(result.skipped, 0)

        directories = {row[0]: row for row in result.dirs}
        self.assertNotIn(".git", directories)
        self.assertEqual(directories["."][1], expected_size)
        self.assertEqual(directories["."][2], 3)
        self.assertEqual(directories["."][3], 4)
        self.assertEqual(directories["dir"][3], 2)
        self.assertEqual(directories["empty"][3], 1)

    def test_min_file_size(self):
        result = scan(self.root, exclude=[".git"], min_file_size=250)
        paths = {row[0] for row in result.files}
        self.assertIn("dir/sub/c.txt", paths)
        self.assertNotIn("a.txt", paths)
        self.assertNotIn("dir/b.txt", paths)

    def test_should_exclude(self):
        self.assertTrue(should_exclude(".git", ".git", [".git"]))
        self.assertTrue(should_exclude("foo.log", "foo.log", ["*.log"]))
        self.assertTrue(should_exclude("cache", "dir/cache", ["dir/cache"]))
        self.assertFalse(should_exclude("keep.txt", "keep.txt", [".git"]))

    def test_symlink_skipped_by_default(self):
        try:
            os.symlink(self.root / "dir", self.root / "link")
        except OSError:
            self.skipTest("symlinks are not available")
        result = scan(self.root, exclude=[".git"], min_file_size=1)
        directories = {row[0] for row in result.dirs}
        self.assertNotIn("link", directories)
        self.assertEqual(result.total_files, 3)

    def test_follow_symlinks_does_not_duplicate(self):
        try:
            os.symlink(self.root / "dir", self.root / "link")
        except OSError:
            self.skipTest("symlinks are not available")
        result = scan(
            self.root,
            exclude=[".git"],
            min_file_size=1,
            follow_symlinks=True,
        )
        self.assertEqual(result.total_files, 3)
        self.assertEqual(result.total_dirs, 4)

    def test_missing_root(self):
        with self.assertRaises(FileNotFoundError):
            scan(self.root / "missing")

    def test_file_root(self):
        with self.assertRaises(ValueError):
            scan(self.root / "a.txt")


if __name__ == "__main__":
    unittest.main()
