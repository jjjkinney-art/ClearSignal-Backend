"""Streaming retention must preserve binding and fail closed through EOF."""
import tracemalloc

import pytest

from app.providers import sec_inline_facts as parser
from test_filing_metric_evidence import _xml, CIK, CONCEPTS


def observations(xml):
    return parser.parse_inline_observations(xml, cik=CIK, concepts=CONCEPTS)


def test_display_markup_does_not_grow_a_document_tree_or_namespace_index():
    xml = _xml().replace('</body>', '<span>unrelated display text</span>' * 100_000 + '</body>')
    baseline = observations(_xml())
    tracemalloc.start()
    try:
        actual = observations(xml)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert actual == baseline
    # A retained tree for these 100k nodes exceeds this bound by a wide margin.
    # Exclude fixture creation and imports; measure parser allocations only.
    assert peak < 6_000_000


def test_forward_references_and_late_duplicate_ids_are_checked_before_admission():
    xml = _xml()
    start = xml.index('<ix:header>')
    end = xml.index('</ix:header>') + len('</ix:header>')
    header = xml[start:end]
    reordered = xml[:start] + xml[end:]
    reordered = reordered.replace('</body>', header + '</body>')
    assert observations(reordered) == observations(xml)
    for identifier in ('f-current', 'current', 'usd'):
        assert all(item['fact_id'] != 'f-current' for item in observations(
            reordered.replace('</body>', f'<span id="{identifier}"/> </body>')))


def test_malformed_xml_after_qualified_facts_cannot_return_partial_observations():
    assert observations(_xml().replace('</html>', '<broken></html>')) == ()


def test_fact_child_markup_cannot_become_a_flat_literal_when_display_nodes_are_discarded():
    assert all(item['fact_id'] != 'f-current' for item in observations(
        _xml().replace('>1,100<', '>1,100<span/> <')))


def test_measure_namespace_rebinding_is_local_and_cannot_authorize_another_unit():
    xml = _xml().replace('<xbrli:measure>', '<xbrli:measure xmlns:iso4217="https://untrusted.example/units">')
    assert observations(xml) == ()
    # Fact-name prefixes declared on the fact itself remain supported.
    xml = _xml().replace('name="us-gaap:Revenues"',
        'xmlns:local="http://fasb.org/us-gaap/2026" name="local:Revenues"')
    assert observations(xml) == observations(_xml())


@pytest.mark.parametrize('limit,value', [('MAX_DEPTH', 3), ('MAX_IDS', 2),
    ('MAX_RESOURCES', 1), ('MAX_FACTS', 1), ('MAX_NAMESPACES', 2)])
def test_metadata_budget_exhaustion_withholds_entire_document(monkeypatch, limit, value):
    monkeypatch.setattr(parser, limit, value)
    assert observations(_xml()) == ()


def test_oversized_unsupported_context_does_not_retain_its_display_subtree():
    extra = '<xbrli:context id="oversized">' + '<span/>' * 1000 + '</xbrli:context>'
    assert observations(_xml().replace('</ix:resources>', extra + '</ix:resources>')) == observations(_xml())


def test_long_literal_and_deep_display_markup_fail_closed():
    assert all(item['fact_id'] != 'f-current' for item in observations(
        _xml().replace('>1,100<', '>' + '1' * 5000 + '<')))
    nested = '<span>' * (parser.MAX_DEPTH + 1) + '</span>' * (parser.MAX_DEPTH + 1)
    assert observations(_xml().replace('</body>', nested + '</body>')) == ()
