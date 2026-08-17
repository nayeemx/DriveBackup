"""AI (Gemini) tests - all Gemini calls mocked, no API key needed."""
import sys
import unittest
from unittest.mock import patch

from app.ai import llm

FAKE_INVENTORY = [
    {"Path": "docs/report.pdf", "Name": "report.pdf", "Size": 1000,
     "Hashes": {"MD5": "a" * 32}, "ModTime": "2026-01-15T10:00:00"},
    {"Path": "misc/weird.xyz", "Name": "weird.xyz", "Size": 500,
     "Hashes": {"MD5": "b" * 32}, "ModTime": "2025-06-01T08:00:00"},
    {"Path": "misc/archivefile.zzz", "Name": "archivefile.zzz", "Size": 700,
     "Hashes": {"MD5": "c" * 32}, "ModTime": "2024-03-03T03:00:00"},
]

FAKE_MANIFEST = [
    {"path": "docs/report.pdf", "size": 1000, "md5": "a" * 32,
     "modtime": "2026-01-15T10:00:00"},
    {"path": "misc/weird.xyz", "size": 500, "md5": "b" * 32,
     "modtime": "2025-06-01T08:00:00"},
    {"path": "misc/archivefile.zzz", "size": 700, "md5": "c" * 32,
     "modtime": "2024-03-03T03:00:00"},
]


def _fake_resp(text):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    return R()


class TestParseJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(llm._parse_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(llm._parse_json('```json\n{"a": 1}\n```'), {"a": 1})


class TestCategorize(unittest.TestCase):
    def test_valid_and_dropped(self):
        payload = '{"weird.xyz": "Documents", "archivefile.zzz": "Bogus"}'
        with patch("app.ai.llm.requests.post",
                   return_value=_fake_resp(payload)) as m:
            result = llm.ai_categorize("k", ["weird.xyz", "archivefile.zzz"])
        self.assertEqual(result, {"weird.xyz": "Documents"})
        self.assertEqual(m.call_count, 1)

    def test_batching(self):
        names = [f"f{i}.xyz" for i in range(250)]
        with patch("app.ai.llm.requests.post",
                   return_value=_fake_resp("{}")) as m:
            llm.ai_categorize("k", names)
        self.assertEqual(m.call_count, 2)

    def test_network_failure(self):
        with patch("app.ai.llm.requests.post",
                   side_effect=Exception("boom")):
            self.assertEqual(llm.ai_categorize("k", ["a.xyz"]), {})

    def test_empty(self):
        self.assertEqual(llm.ai_categorize("k", []), {})


class TestOrgPlan(unittest.TestCase):
    def test_valid_and_dropped(self):
        payload = ('{"docs/report.pdf": "Work/Reports/report.pdf", '
                   '"misc/weird.xyz": "misc\\\\bad.xyz", '
                   '"misc/archivefile.zzz": "Archives/archivefile.zzz"}')
        with patch("app.ai.llm.requests.post",
                   return_value=_fake_resp(payload)):
            result = llm.ai_organization_plan(
                "k", [{"source": "docs/report.pdf"},
                      {"source": "misc/weird.xyz"},
                      {"source": "misc/archivefile.zzz"}])
        self.assertEqual(result, {
            "docs/report.pdf": "Work/Reports/report.pdf",
            "misc/archivefile.zzz": "Archives/archivefile.zzz",
        })


class TestQualityCheck(unittest.TestCase):
    def test_valid(self):
        payload = ('[{"severity": "high", "message": "Verify failed"}, '
                   '{"severity": "bogus", "message": "drop me"}, '
                   '{"severity": "low", "message": "ok"}]')
        with patch("app.ai.llm.requests.post",
                   return_value=_fake_resp(payload)):
            result = llm.ai_quality_check("k", {"count": 3, "size": 1})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["severity"], "high")

    def test_failure_returns_empty(self):
        with patch("app.ai.llm.requests.post",
                   side_effect=Exception("boom")):
            self.assertEqual(llm.ai_quality_check("k", {"count": 3}), [])


class TestSummarize(unittest.TestCase):
    def test_ok(self):
        with patch("app.ai.llm.requests.post",
                   return_value=_fake_resp("Nice summary")):
            self.assertEqual(llm.summarize("k", {"count": 1}), "Nice summary")

    def test_no_key(self):
        with self.assertRaises(RuntimeError):
            llm.summarize("", {"count": 1})


class TestOpenRouter(unittest.TestCase):
    def test_routing(self):
        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content":
                                                 '{"a.xyz": "Other"}'}}]}

        with patch("app.ai.llm.requests.post",
                   return_value=R()) as m:
            result = llm.ai_categorize("sk-test", ["a.xyz"],
                                       provider="openrouter")
        self.assertEqual(result, {"a.xyz": "Other"})
        kwargs = m.call_args
        self.assertEqual(kwargs[0][0], llm.OPENROUTER_API)
        self.assertEqual(kwargs[1]["headers"]["Authorization"],
                         "Bearer sk-test")
        self.assertEqual(kwargs[1]["json"]["model"], "openrouter/auto")

    def test_custom_model(self):
        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

        with patch("app.ai.llm.requests.post", return_value=R()) as m:
            llm.summarize("sk", {"count": 1}, provider="openrouter",
                          model="anthropic/claude-sonnet-4")
        self.assertEqual(
            m.call_args[1]["json"]["model"], "anthropic/claude-sonnet-4")


class TestAnalyzerIntegration(unittest.TestCase):
    def test_analyze_ai_reclassify(self):
        from app.ai import analyzer
        with patch.object(analyzer, "load_inventory",
                          return_value=FAKE_INVENTORY), \
                patch.object(analyzer, "get_manifest",
                             return_value=FAKE_MANIFEST), \
                patch("app.ai.llm.ai_categorize",
                      return_value={"weird.xyz": "Documents",
                                    "archivefile.zzz": "Other"}):
            result = analyzer.analyze("fake-key")
        self.assertEqual(result["ai_classified"], 1)
        self.assertEqual(result["categories"]["Other"]["count"], 1)
        self.assertEqual(result["categories"]["Documents"]["count"], 2)

    def test_analyze_no_key_no_ai(self):
        from app.ai import analyzer
        with patch.object(analyzer, "load_inventory",
                          return_value=FAKE_INVENTORY), \
                patch.object(analyzer, "get_manifest",
                             return_value=FAKE_MANIFEST), \
                patch("app.ai.llm.ai_categorize",
                      side_effect=AssertionError("should not be called")):
            result = analyzer.analyze("")
        self.assertEqual(result["ai_classified"], 0)
        self.assertEqual(result["categories"]["Other"]["count"], 2)

    def test_org_plan_ai_targets(self):
        from app.ai import analyzer
        payload = {"docs/report.pdf": "Work/Reports/report.pdf"}
        with patch.object(analyzer, "get_manifest",
                          return_value=FAKE_MANIFEST), \
                patch("app.ai.llm.ai_organization_plan",
                      return_value=payload):
            plan = analyzer.organization_plan("fake-key")
        by_src = {e["source"]: e for e in plan}
        self.assertEqual(by_src["docs/report.pdf"]["target"],
                         "Work/Reports/report.pdf")
        self.assertTrue(by_src["misc/weird.xyz"]["target"].
                        endswith("Organized/Other/2025/weird.xyz"))

    def test_org_plan_no_key_rules(self):
        from app.ai import analyzer
        with patch.object(analyzer, "get_manifest",
                          return_value=FAKE_MANIFEST), \
                patch("app.ai.llm.ai_organization_plan",
                      side_effect=AssertionError("should not be called")):
            plan = analyzer.organization_plan("")
        self.assertEqual(len(plan), 3)

    def test_quality_no_key(self):
        from app.ai import analyzer
        self.assertEqual(analyzer.quality_check(""), [])

    def test_quality_with_key(self):
        from app.ai import analyzer
        with patch.object(analyzer, "analyze", return_value={"count": 1}), \
                patch("app.ai.llm.ai_quality_check",
                      return_value=[{"severity": "low", "message": "ok"}]):
            result = analyzer.quality_check("fake-key",
                                            analysis={"count": 1},
                                            verify={"passed": True})
        self.assertEqual(result[0]["message"], "ok")


if __name__ == "__main__":
    sys.exit(unittest.main(verbosity=2))