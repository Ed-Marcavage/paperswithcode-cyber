"""Validation of reviewed industry-post fields; no database."""
import unittest

from import_post_details import post_details

REVIEW = {
    "tier": "featured", "post_type": "vulnerability-writeup", "tldr": " One sentence. ",
    "original_title": "Title | Publisher", "subtopics": ["memory-safety", "other: agent memory"],
    "authors": ["A. Writer"], "caveat": "", "timeliness": "dated",
    "technical_depth": 3, "originality": 2, "agent_relevance": 0,
    "reports_benchmark_results": False, "agent_harness_engineering": True,
    "entities": [{"type": "cve", "name": "CVE-2026-0001", "role": "subject", "extra": 1}],
    "text_sha256": "not kept", "version_id": "not kept",
}


class PostDetailsTest(unittest.TestCase):
    def test_keeps_reviewed_fields_only(self):
        details = post_details("industry-1", REVIEW)
        self.assertEqual(details["tldr"], "One sentence.")
        self.assertIsNone(details["caveat"])
        self.assertEqual(details["entities"], [{"type": "cve", "name": "CVE-2026-0001", "role": "subject"}])
        self.assertNotIn("text_sha256", details)
        self.assertNotIn("version_id", details)

    def test_rejects_values_outside_the_vocabulary(self):
        for field, value in [("tier", "top"), ("post_type", "news"), ("technical_depth", 5),
                             ("originality", True), ("agent_harness_engineering", "yes"), ("tldr", " ")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                post_details("industry-1", {**REVIEW, field: value})


if __name__ == "__main__":
    unittest.main()
