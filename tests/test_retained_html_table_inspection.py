"""Local inspection maps bind bytes and preserve uninterpreted table structure."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location('table_inspector',
    Path(__file__).resolve().parents[1] / 'scripts/inspect_retained_html_table.py')
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def inspect(source, index=0, **receipt_changes):
    body = source.encode('utf-8')
    receipt = {'body_sha256': hashlib.sha256(body).hexdigest(), 'body_bytes': len(body),
               'media_type': 'text/html', 'url': 'https://example.invalid/retained.html'}
    return module.inspect(body, receipt | receipt_changes, index)


def test_exact_unicode_source_span_and_cell_structure():
    source = 'É\n<p>Basis &amp; period</p><table><tr><th colspan="2">(in thousands)</th></tr>\n<tr><td>Loss</td><td>( <ix:nonFraction name="x:Loss" contextRef="c1" unitRef="u1" scale="3" sign="-">9,292</ix:nonFraction> )</td></tr></table>'
    result = inspect(source)
    table = result['selected_table']
    assert source[table['html_start']:table['html_end']].startswith('<table>')
    assert source[table['html_start']:table['html_end']].endswith('</table>')
    assert table['raw_html_utf8_sha256'] == hashlib.sha256(source[table['html_start']:table['html_end']].encode()).hexdigest()
    assert table['preceding_visible_context'] == 'É Basis & period'
    cells = table['rows'][1]['cells']
    assert cells[1]['text'] == '( 9,292 )'
    assert source[cells[1]['html_start']:cells[1]['html_end']].startswith('<td>')
    assert cells[1]['inline_facts'][0]['attributes'] == {'name': 'x:Loss', 'contextref': 'c1', 'unitref': 'u1', 'scale': '3', 'sign': '-'}
    assert table['rows'][0]['cells'][0]['attributes']['colspan'] == '2'
    assert result['source']['independent_origin_verification'] is False


@pytest.mark.parametrize('change', [{'body_sha256': '0' * 64}, {'body_bytes': 1}, {'media_type': 'application/json'}])
def test_refuses_receipt_mismatch(change):
    with pytest.raises(ValueError):
        inspect('<table><tr><td>x</td></tr></table>', **change)


@pytest.mark.parametrize('source', ['<table><tr><td>x</td></tr>', '<table><tr><td>x</tr></table>'])
def test_refuses_incomplete_structure(source):
    with pytest.raises(ValueError):
        inspect(source)


def test_nested_tables_require_explicit_innermost_selection():
    source = '<table><tr><td>Outer<table><tr><td>Inner</td></tr></table></td></tr></table>'
    with pytest.raises(ValueError, match='nested'):
        inspect(source)
    assert inspect(source, 1)['selected_table']['rows'][0]['cells'][0]['text'] == 'Inner'
    assert inspect(source, None)['tables'][0]['nested_table_indices'] == [1]


def test_invalid_index_cannot_select_another_table():
    with pytest.raises(ValueError, match='index'):
        inspect('<table></table>', -1)
