import unittest

from diskblame.format import (
    format_delta,
    format_size,
    human_age,
    parse_duration,
    parse_size,
)


class FormatTests(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1024), "1.0 KiB")
        self.assertEqual(format_size(1536), "1.5 KiB")
        self.assertEqual(format_size(-1024), "-1.0 KiB")
        self.assertEqual(format_size(1024**3), "1.0 GiB")

    def test_format_delta(self):
        self.assertEqual(format_delta(1024), "+1.0 KiB")
        self.assertEqual(format_delta(-1024), "-1.0 KiB")
        self.assertEqual(format_delta(0), "0 B")

    def test_parse_size(self):
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size("1KiB"), 1024)
        self.assertEqual(parse_size("1.5 MiB"), 1572864)
        self.assertEqual(parse_size("500MB"), 524288000)

    def test_parse_size_invalid(self):
        with self.assertRaises(ValueError):
            parse_size("many")
        with self.assertRaises(ValueError):
            parse_size("10XB")

    def test_parse_duration(self):
        self.assertEqual(parse_duration("30m"), 1800)
        self.assertEqual(parse_duration("7d"), 604800)
        self.assertEqual(parse_duration("1w2d"), 777600)

    def test_parse_duration_invalid(self):
        with self.assertRaises(ValueError):
            parse_duration("7 days")
        with self.assertRaises(ValueError):
            parse_duration("1y")

    def test_human_age(self):
        now = 1000000
        self.assertEqual(human_age(now - 10, now=now), "just now")
        self.assertEqual(human_age(now - 120, now=now), "2m ago")
        self.assertEqual(human_age(now - 7200, now=now), "2h ago")
        self.assertEqual(human_age(now - 172800, now=now), "2d ago")


if __name__ == "__main__":
    unittest.main()
