import hashlib
import json

import pytest

from validation import source_gap_analysis as analysis


def facts():
    def row(year, quarter, value):
        return {'start': f'{year}-' + ('01-01' if quarter == 1 else '04-01'),
            'end': f'{year}-' + ('03-31' if quarter == 1 else '06-30'),
            'filed': f'{year}-' + ('05-01' if quarter == 1 else '08-01'),
            'form': '10-Q', 'accn': f'0001520697-{str(year)[-2:]}-00000{quarter}', 'val': value}
    return {'cik': 1520697, 'facts': {'us-gaap': {'NetIncomeLoss': {'units': {'USD': [
        row(year, quarter, 100 + year - 2025) for quarter in (1, 2) for year in (2025, 2026)]}}}}}


def selected(report):
    return next(row for row in report['concept_diagnostics']
                if row['concept'] == 'NetIncomeLoss' and row['unit'] == 'USD')


def test_complete_latest_pairs_are_selected_and_amounts_not_exported():
    body = json.dumps(facts()).encode()
    report = analysis.analyze_achc_facts(body)
    row = selected(report)
    assert row['parsed_records'] == row['duration_eligible_records'] == 4
    assert row['latest_parsed_end'] == row['selected_end'] == '2026-06-30'
    assert report['body_sha256'] == hashlib.sha256(body).hexdigest()
    assert 'raw_value' not in json.dumps(report)


@pytest.mark.parametrize('mutation,parsed,eligible,chosen', [
    ('missing_q2', 2, 2, '2026-03-31'),
    ('invalid_duration', 4, 2, '2026-03-31'),
    ('missing_prior', 3, 3, None),
    ('conflict', 5, 5, None),
    ('malformed_value', 2, 2, '2026-03-31'),
])
def test_synthetic_failures_distinguish_unavailable_ineligible_and_unusable_pairs(mutation, parsed, eligible, chosen):
    data = facts(); rows = data['facts']['us-gaap']['NetIncomeLoss']['units']['USD']
    if mutation == 'missing_q2': rows[:] = rows[:2]
    if mutation == 'invalid_duration':
        for row in rows[2:]: row['start'] = None
    if mutation == 'missing_prior': rows.pop(2)
    if mutation == 'conflict': rows.append({**rows[-1], 'val': 999})
    if mutation == 'malformed_value':
        for row in rows[2:]: row['val'] = True
    row = selected(analysis.analyze_achc_facts(json.dumps(data).encode()))
    assert row['parsed_records'] == parsed and row['duration_eligible_records'] == eligible
    assert row['selected_end'] == chosen


@pytest.mark.parametrize('body', [b'[]', b'{"cik":80172}', b'{"cik":1520697,"value":NaN}'])
def test_facts_identity_and_nonfinite_json_are_refused(body):
    with pytest.raises(ValueError): analysis.analyze_achc_facts(body)


def html():
    sentences = [
        'Short statement.', 'Another short statement.',
        'We manufacture 12 product lines and operate facilities across many regions.',
        'We expect to expand manufacturing operations across additional markets in the coming year.',
        'We manufacture specialized components and distribute our products through independent dealers.',
        'We provide maintenance services to industrial customers through direct service contracts.',
    ]
    return ('<html><body><h1>Item 1. Business</h1><p>' + ' '.join(sentences)
            + '</p><h1>Item 1A. Risk Factors</h1><p>Risks exist.</p>'
            '<h1>Item 1B. Unresolved Staff Comments</h1></body></html>').encode()


def test_samples_are_bounded_complete_sentences_and_explicitly_not_final_admission():
    report = analysis.analyze_npk_html(html())
    assert report['complete_business_window']
    assert len(report['samples']) <= 6
    assert {row['review_bucket'] for row in report['samples']} == {
        'length_review', 'numeric_or_forward_review', 'other_review'}
    assert sum(len(row.get('complete_sentence', '')) for row in report['samples']) <= 1800
    for row in report['samples']:
        assert row['end_offset'] - row['start_offset'] == row['characters']
        if 'complete_sentence' in row:
            quote = row['complete_sentence']
            assert len(quote) == row['characters'] and quote.endswith('.')
            assert hashlib.sha256(quote.encode()).hexdigest() == row['sentence_sha256']
    assert 'not final rejection or admission' in report['sample_limitation']


def test_oversized_sentence_is_hashed_not_clipped():
    body = ('<h1>Item 1. Business</h1><p>' + 'Business activity ' * 50 + 'ends here.</p>'
            '<h1>Item 1A. Risk Factors</h1><p>Risks.</p><h1>Item 1B. Unresolved Staff Comments</h1>').encode()
    row = analysis.analyze_npk_html(body)['samples'][0]
    assert row['characters'] > 600 and 'complete_sentence' not in row


def test_missing_business_section_is_explicit():
    report = analysis.analyze_npk_html(b'<p>Unrelated public document.</p>')
    assert report['complete_business_window'] is None and report['samples'] == []


def test_cli_writes_fresh_non_authoritative_report_and_never_overwrites(tmp_path):
    a, n, out = tmp_path/'facts.json', tmp_path/'filing.html', tmp_path/'report.json'
    a.write_bytes(json.dumps(facts()).encode()); n.write_bytes(html())
    args = ['--achc-facts', str(a), '--npk-html', str(n), '--output', str(out)]
    assert analysis.main(args) == 0
    report = json.loads(out.read_text())
    assert report['admitted_evidence'] is False
    assert report['capture_authenticity_independently_verified'] is False
    before = out.read_bytes()
    with pytest.raises(FileExistsError): analysis.main(args)
    assert out.read_bytes() == before


def test_local_reader_enforces_size_and_refuses_symlinks(tmp_path):
    p = tmp_path/'source'; p.write_bytes(b'12345')
    with pytest.raises(ValueError): analysis._read_local(p, 4)
    link = tmp_path/'link'; link.symlink_to(p)
    with pytest.raises(ValueError): analysis._read_local(link, 10)
    assert analysis._read_local(p, 5) == b'12345'


def test_analysis_functions_enforce_fixed_input_envelopes(monkeypatch):
    monkeypatch.setattr(analysis, 'FACTS_LIMIT', 3)
    monkeypatch.setattr(analysis, 'DOCUMENT_LIMIT', 3)
    with pytest.raises(ValueError): analysis.analyze_achc_facts(b'1234')
    with pytest.raises(ValueError): analysis.analyze_npk_html(b'1234')
