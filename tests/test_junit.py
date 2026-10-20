from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from quality_pilot.junit import classify_test_cases, parse_junit


class JUnitTests(unittest.TestCase):
    def test_parses_and_classifies_test_cases_across_attempts(self) -> None:
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.xml"
            second = Path(directory) / "second.xml"
            first.write_text(
                '<testsuite><testcase classname="suite" name="intermittent" time="0.2">'
                '<failure message="timed out">stack</failure></testcase>'
                '<testcase classname="suite" name="stable" /></testsuite>',
                encoding="utf-8",
            )
            second.write_text(
                '<testsuite><testcase classname="suite" name="intermittent" time="0.1" />'
                '<testcase classname="suite" name="stable"><skipped /></testcase></testsuite>',
                encoding="utf-8",
            )
            results = classify_test_cases([parse_junit(first), parse_junit(second)])
            self.assertEqual(results[0]["outcome"], "flaky")
            self.assertEqual(results[1]["outcome"], "passed")


if __name__ == "__main__":
    unittest.main()
