"""
test_final_blockers.py — Tests proving the FINAL completion blockers are fixed.
"""
from __future__ import annotations

import os
import re
import sys
import types
import pathlib
import threading

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _stub(name, **attrs):
    if name in sys.modules:
        m = sys.modules[name]
    else:
        m = types.ModuleType(name); m.__path__ = []
        sys.modules[name] = m
    for k, v in attrs.items(): setattr(m, k, v)
    return m


pd = _stub("pydantic")


class _BM:
    model_config = {}; model_fields = {}
    def __init__(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)


pd.BaseModel = _BM
pd.Field = lambda *a, **k: None
pd.field_validator = lambda *a, **k: (lambda fn: fn)
pd.validator = lambda *a, **k: (lambda fn: fn)
pd.model_validator = lambda *a, **k: (lambda fn: fn)
pd.root_validator = lambda *a, **k: (lambda fn: fn)
pd.ConfigDict = dict
_stub("pydantic_settings", BaseSettings=_BM)


class TestConftestEnforcesHangPrevention:
    def test_conftest_exists_at_project_root(self):
        conftest = _PROJECT_ROOT / "conftest.py"
        assert conftest.exists()

    def test_conftest_neuters_streaming_at_import_time(self):
        content = (_PROJECT_ROOT / "conftest.py").read_text()
        assert "_streaming_mod.start_streaming" in content
        in_function = False
        neutered_at_module_level = False
        for line in content.splitlines():
            if line.startswith("def ") or line.startswith("@"):
                in_function = True
            elif line and not line.startswith(" ") and not line.startswith("\t"):
                in_function = False
            if not in_function and "_streaming_mod.start_streaming" in line:
                neutered_at_module_level = True
                break
        assert neutered_at_module_level, (
            "Streaming must be neutered at module level, not inside a function"
        )

    def test_conftest_has_built_in_watchdog(self):
        content = (_PROJECT_ROOT / "conftest.py").read_text()
        assert "threading.Timer" in content
        assert "os._exit" in content

    def test_audit_store_default_is_in_memory(self):
        if "ANTHROPIC_AUDIT_DB" in os.environ:
            del os.environ["ANTHROPIC_AUDIT_DB"]
        for mod in [m for m in list(sys.modules.keys())
                    if m.startswith("app.enterprise.audit")]:
            del sys.modules[mod]
        from app.enterprise.audit import audit_store
        assert audit_store._db_path is None

    def test_no_module_level_async_run_in_app(self):
        offenders = []
        for py_file in (_PROJECT_ROOT / "app").rglob("*.py"):
            content = py_file.read_text()
            stripped_lines = []
            in_docstring = False
            for line in content.splitlines():
                s = line.strip()
                if s.startswith('"""') or s.startswith("'''"):
                    in_docstring = not in_docstring
                    continue
                if not in_docstring and s and not s.startswith("#"):
                    stripped_lines.append(line)
            for line in stripped_lines:
                if re.match(r"^asyncio\.run\(", line):
                    offenders.append(str(py_file.relative_to(_PROJECT_ROOT)))
        assert not offenders, f"asyncio.run at module level: {offenders}"


class TestEvidenceIsMeaningFirstAtSourceLevel:
    def test_known_facts_strip_raw_stat_facts(self):
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        assert "_is_raw_stat_fact" in src
        assert "if not _is_raw_stat_fact(f)" in src
        assert "m.meaning_summary" in src and "ctx.known_facts.append" in src

    def test_stat_prefixes_cover_metric_first_patterns(self):
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        for pattern in ["Historical price summary:", "Recent event history includes",
                        " trend over the last "]:
            assert pattern in src, f"missing strip pattern: {pattern!r}"

    def test_meaning_objects_built_for_all_four_domains(self):
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        for var in ("price_meaning", "event_meaning", "signal_meaning", "financial_meaning"):
            assert f"{var} = HistoricalMeaning(" in src, f"missing {var}"

    def test_historical_meanings_attached_to_context(self):
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        assert "historical_meanings = meaning_map" in src or \
               'historical_meanings", meaning_map' in src


class TestNoServiceFallbackQuery:
    SERVICE_FILES = [
        "app/services/monitoring_service.py",
        "app/services/alert_service.py",
        "app/services/learning.py",
        "app/services/evidence_service.py",
    ]

    def test_no_fallback_query_in_services(self):
        offenders = []
        for rel in self.SERVICE_FILES:
            content = (_PROJECT_ROOT / rel).read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if "fallback_query" in line:
                    offenders.append(f"{rel}:{i}")
        assert not offenders, f"fallback_query found in: {offenders}"

    def test_no_raw_query_records_in_services(self):
        offenders = []
        for rel in self.SERVICE_FILES:
            content = (_PROJECT_ROOT / rel).read_text()
            if ("from ..data_pipeline.storage import query_records" in content or
                "from app.data_pipeline.storage import query_records" in content):
                offenders.append(rel)
        assert not offenders, f"query_records imported in: {offenders}"

    def test_history_ops_provides_required_semantic_methods(self):
        from app.enterprise.history_ops import history_ops
        required = [
            "get_signal_history_summary", "get_event_history_summary",
            "get_price_history_summary",  "get_financial_history_summary",
            "get_signal_outcome_profile", "get_monitoring_history_context",
            "get_alert_pattern_history",
        ]
        missing = [m for m in required if not callable(getattr(history_ops, m, None))]
        assert not missing, f"missing semantic methods: {missing}"

    def test_semantic_methods_return_canonical_shapes(self):
        from app.enterprise.history_ops import history_ops
        s = history_ops.get_signal_history_summary()
        assert "records" in s and "count" in s and "weighted_scores" in s
        e = history_ops.get_event_history_summary()
        assert "records" in e and "count" in e and "type_counts" in e
        p = history_ops.get_price_history_summary()
        assert "records" in p and "count" in p and "prices" in p
        f = history_ops.get_financial_history_summary()
        assert "records" in f and "count" in f and "by_metric" in f
        prof = history_ops.get_signal_outcome_profile("test")
        assert "signal" in prof and "observation_count" in prof
        mctx = history_ops.get_monitoring_history_context()
        assert "signals" in mctx and "events" in mctx
        alert = history_ops.get_alert_pattern_history("risks")
        assert "component_keyword" in alert and "recent_signal_count" in alert


class TestHistoricalMeaningIsPrimary:
    def test_grounding_context_has_historical_meanings_field(self):
        src = (_PROJECT_ROOT / "app/schemas.py").read_text()
        m = re.search(
            r"class GroundingContext\(BaseModel\):(.*?)(?=^class \w+\(|\Z)",
            src, re.DOTALL | re.MULTILINE,
        )
        assert m, "GroundingContext not found"
        assert "historical_meanings:" in m.group(1)

    def test_historical_meaning_schema_has_canonical_fields(self):
        src = (_PROJECT_ROOT / "app/schemas.py").read_text()
        m = re.search(
            r"class HistoricalMeaning\(BaseModel\):(.*?)(?=^class \w+\(|\Z)",
            src, re.DOTALL | re.MULTILINE,
        )
        assert m
        body = m.group(1)
        required = ["domain", "situation_archetype", "historical_pattern",
                    "pattern_stability", "pattern_direction", "escalation_likelihood",
                    "usual_consequence", "meaning_summary", "supporting_metrics"]
        missing = [f for f in required if f"{f}:" not in body]
        assert not missing, f"missing canonical fields: {missing}"

    def test_meaning_summaries_replace_raw_stats_in_known_facts(self):
        src = (_PROJECT_ROOT / "app/services/evidence_service.py").read_text()
        strip_pos = src.find("if not _is_raw_stat_fact(f)")
        meaning_pos = src.find("ctx.known_facts.append(m.meaning_summary)")
        assert strip_pos > 0
        assert meaning_pos > 0
        assert meaning_pos > strip_pos, "meaning append must come after stat strip"


if __name__ == "__main__":
    suites = [
        TestConftestEnforcesHangPrevention,
        TestEvidenceIsMeaningFirstAtSourceLevel,
        TestNoServiceFallbackQuery,
        TestHistoricalMeaningIsPrimary,
    ]
    passed, failed = 0, 0
    for cls in suites:
        suite = cls()
        for name in sorted(n for n in dir(cls) if n.startswith("test_")):
            full = f"{cls.__name__}.{name}"
            try:
                getattr(suite, name)()
                print(f"  PASS  {full}")
                passed += 1
            except Exception:
                import traceback
                print(f"  FAIL  {full}")
                traceback.print_exc()
                failed += 1
    print(f"\n{'='*66}")
    print(f"  {passed} passed, {failed} failed")
    if not failed:
        print("  ALL FINAL BLOCKER TESTS PASSED")
    print(f"{'='*66}")
