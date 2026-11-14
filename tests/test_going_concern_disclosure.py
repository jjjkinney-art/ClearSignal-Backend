"""A current substantial-doubt conclusion is quoted as the filing states it; nothing else qualifies.

The passages are excerpts of retained SEC filings (Galectin Therapeutics 10-Q for the quarter ended
2026-06-30 and 10-K for 2025). No network access is used.
"""
import copy
from types import SimpleNamespace

import pytest

from app.integrity.provenance import ClaimDocumentReference
from app.schemas import RetrievedEvidence
from app.services import going_concern_disclosure as gc
from app.services.financial_thesis_foundation import build_financial_foundation
from test_financial_thesis_foundation import evidence, reference

CIK = '1133416'
URL = f'https://www.sec.gov/Archives/edgar/data/{CIK}/000114036126032945/ef20075252_10q.htm'
HASH = 'b' * 64
CASH = 'As of June 30, 2026, the Company had $13.3 million of unrestricted cash and cash equivalents available to fund future operations.'
MATURITY = ('All of the Company’s borrowings and accrued interest under related party debt to its chairman '
            'are due to mature on June 30, 2027.')
BELIEF = ('The Company believes there is sufficient cash, including availability of the line of credit, '
          'to fund currently planned operations through June 2027.')
CONCLUSION = ('These factors raise substantial doubt about the Company’s ability to continue as a going concern '
              'for a period of 12 months from the issuance date of these financial statements.')
DEPENDENCE = ('The ability of the Company to continue as a going concern is dependent on its ability to raise '
              'capital; however, the Company’s cash position may not be sufficient to support its daily '
              'operations after June 2027.')
NOTE = ' '.join([CASH, MATURITY, BELIEF, CONCLUSION, DEPENDENCE,
                 'To meet its future capital needs, the Company intends to raise additional capital.'])
RISK_SUMMARY = '• we have from time to time faced substantial doubt about our ability to continue as a going concern;'
RISK_FACTOR_10K = ('We have from time to time faced substantial doubt about our ability to continue as a going concern. '
                   'Although management believes that we have sufficient cash to cover operating expenses requiring cash '
                   'for a period of 12 months from the date of this annual report on Form 10-K, we have from time to time '
                   'faced periods where there was substantial doubt as to our ability to continue as a going concern.')


def document(text, *, published_at='2026-08-14', document_type='10-Q'):
    return SimpleNamespace(document_type=document_type, publisher='SEC EDGAR', source_type='regulatory_filing',
                           source_tier='primary', extraction_method='html', text=text, final_url=URL,
                           content_hash=HASH, published_at=published_at, title='GALT 10-Q')


def extract(text, **kw):
    return gc.extract_going_concern(document(text, **kw), ticker='GALT', cik=CIK, period_end='2026-06-30')


# --- the classification: what is, and is not, a current conclusion ----------------------------------------

def test_the_issuers_own_present_conclusion_is_current():
    assert gc.classify(CONCLUSION, BELIEF, DEPENDENCE) == 'current'
    assert gc.classify('Management has concluded that there is substantial doubt about our ability to '
                       'continue as a going concern.') == 'current'
    assert gc.classify('Substantial doubt exists about the Company’s ability to continue as a going concern.') == 'current'
    # An opinion of management is the issuer's own conclusion, not an auditor's.
    assert gc.classify('In the opinion of management, these conditions raise substantial doubt about the '
                       'Company’s ability to continue as a going concern.') == 'current'


@pytest.mark.parametrize('sentence,reason', [
    # Boilerplate and conditional risk language.
    ('If we cannot raise capital, these conditions could raise substantial doubt about our ability to continue as a going concern.',
     'conditional'),
    ('Failure to obtain financing may raise substantial doubt about the Company’s ability to continue as a going concern.',
     'conditional'),
    # Historical statements.
    ('We have from time to time faced substantial doubt about our ability to continue as a going concern.', 'historical'),
    ('In 2023 these conditions raised substantial doubt about the Company’s ability to continue as a going concern.', 'historical'),
    ('Previously, there was substantial doubt about our ability to continue as a going concern.', 'historical'),
    # Alleviated or negated.
    ('Management’s plans alleviate the substantial doubt about the Company’s ability to continue as a going concern.',
     'alleviated_or_negated'),
    ('These conditions do not raise substantial doubt about our ability to continue as a going concern.',
     'alleviated_or_negated'),
    ('The substantial doubt about the Company’s ability to continue as a going concern has been alleviated.',
     'alleviated_or_negated'),
    ('There is no longer substantial doubt about the Company’s ability to continue as a going concern.',
     'alleviated_or_negated'),
    # The auditor's opinion is not the issuer's conclusion.
    ('Our independent registered public accounting firm included an explanatory paragraph that raises substantial '
     'doubt about our ability to continue as a going concern.', 'auditor_statement'),
    # Another entity.
    ('Our largest customer’s liquidity raises substantial doubt about its ability to continue as a going concern.',
     'other_entity_or_no_issuer_subject'),
    # Mentions the assumption, not a conclusion of doubt.
    ('These statements have been prepared assuming the Company will continue as a going concern.',
     'not_a_going_concern_conclusion'),
    ('The Company has had substantial doubt about liquidity.', 'not_a_going_concern_conclusion'),
])
def test_everything_else_that_mentions_the_doubt_does_not_qualify(sentence, reason):
    assert gc.classify(sentence) == reason


def test_a_neighbour_that_withdraws_the_doubt_withdraws_the_conclusion():
    assert gc.classify(CONCLUSION, BELIEF, 'However, management’s plans alleviate these conditions.') == \
        'alleviated_by_adjacent_sentence'
    assert gc.classify(CONCLUSION, 'Management’s plans have overcome the conditions that raised doubt.', DEPENDENCE) == \
        'alleviated_by_adjacent_sentence'
    # A neighbour that merely uses the word elsewhere does not.
    assert gc.classify(CONCLUSION, 'Costs were mitigated by lower headcount.', DEPENDENCE) == 'current'


# --- extraction ------------------------------------------------------------------------------------------

def test_the_conclusion_is_quoted_with_its_neighbours_verbatim():
    (item,) = extract(NOTE)
    value = item.going_concern_disclosures[0]
    # One contiguous passage of the filing, from management's stated belief to the stated dependence.
    assert value['quote'] == ' '.join([BELIEF, CONCLUSION, DEPENDENCE])
    assert value['quote'] in NOTE and value['conclusion'] == CONCLUSION
    assert value['quote'][value['conclusion_offset']:].startswith(CONCLUSION)
    # Stated as the filing states it, without saying more.
    assert item.summary.startswith('GALT stated in its 10-Q filed 2026-08-14 (period ended 2026-06-30): “')
    assert 'not an independent assessment, a prediction that operations will cease' in item.summary
    assert gc.bound_going_concern(item, ticker='GALT', cik=CIK) == value
    for word in ('bankrupt', 'insolven', 'will fail', 'imminent'):
        assert word not in item.summary.lower()


def test_only_the_first_current_statement_is_used():
    (item,) = extract(NOTE + ' ' + CONCLUSION.replace('these financial statements', 'this Form 10-Q'))
    assert item.going_concern_disclosures[0]['start_offset'] == NOTE.index(BELIEF)


@pytest.mark.parametrize('text', [
    RISK_SUMMARY, RISK_FACTOR_10K, RISK_SUMMARY + ' ' + RISK_FACTOR_10K,
    'These statements have been prepared assuming the Company will continue as a going concern. '
    'The going concern assumption contemplates the realization of assets in the normal course of business.',
    f'{BELIEF} Management’s plans alleviate the substantial doubt about the Company’s ability to continue as a going concern.',
    f'{BELIEF} {CONCLUSION} However, management’s plans alleviate these conditions.',
])
def test_boilerplate_historical_and_alleviated_text_yields_nothing(text):
    assert extract(text) == []


def test_a_document_that_is_not_the_issuers_primary_filing_yields_nothing():
    base = document(NOTE)
    for change in ({'publisher': 'Other'}, {'extraction_method': 'pdf_text'}, {'content_hash': 'x'},
                   {'final_url': 'https://www.sec.gov/Archives/edgar/data/999/000114036126032945/x.htm'},
                   {'document_type': '8-K'}, {'source_tier': 'secondary'}, {'text': ''}):
        doc = SimpleNamespace(**{**vars(base), **change})
        assert gc.extract_going_concern(doc, ticker='GALT', cik=CIK, period_end='2026-06-30') == []
    # A period end after the filing date is not a period of this filing.
    assert gc.extract_going_concern(base, ticker='GALT', cik=CIK, period_end='2026-09-30') == []


def test_a_long_neighbour_is_left_out_rather_than_clipped():
    long = 'The Company ' + 'has operated at a loss ' * 30 + 'since inception.'
    (item,) = extract(' '.join([long, CONCLUSION, DEPENDENCE]))
    quote = item.going_concern_disclosures[0]['quote']
    assert quote.startswith(CONCLUSION) and long not in quote and quote.endswith('June 2027.')


# --- the binder rechecks everything -----------------------------------------------------------------------

def _forged(item, **changes):
    """The same item with fields changed, the reference and summary rebuilt to match."""
    value = copy.deepcopy(item.going_concern_disclosures[0])
    value.update({k: v for k, v in changes.items() if k in value})
    ref = dict(value['document_ref'])
    ref['quote'] = value['quote']
    value['document_ref'] = ClaimDocumentReference(**ref).to_dict()
    fields = {k: v for k, v in changes.items() if k not in value}
    data = item.model_dump()
    data.update(going_concern_disclosures=[value], summary=gc._summary(value), **fields)
    return RetrievedEvidence(**data)


def test_the_binder_rejects_a_changed_binding():
    (item,) = extract(NOTE)
    assert gc.bound_going_concern(item, ticker='GALT', cik=CIK)
    assert gc.bound_going_concern(item, ticker='OTHER', cik=CIK) is None
    assert gc.bound_going_concern(item, ticker='GALT', cik='999') is None
    for fields in ({'summary': item.summary + ' It is certain.'}, {'reporting_period_end': '2026-03-31'},
                   {'document_type': '8-K'}, {'section': 'Item 1A. Risk Factors'}, {'timestamp': '2026-08-15'},
                   {'freshness_status': 'stale'}, {'extraction_method': 'publisher_feed'}, {'url': URL + '?x=1'},
                   {'source_tier': 'secondary'}):
        assert gc.bound_going_concern(item.model_copy(update=fields), ticker='GALT', cik=CIK) is None, fields
    value = item.going_concern_disclosures[0]
    for key, bad in (('quote', value['quote'] + ' '), ('conclusion', CONCLUSION[:-1]), ('conclusion_offset', 0),
                     ('start_offset', value['start_offset'] + 1), ('end_offset', value['end_offset'] + 1),
                     ('claim_kind', 'issuer_disclosed_risk'), ('period_end', '2026-03-31')):
        tampered = copy.deepcopy(item.going_concern_disclosures[0])
        tampered[key] = bad
        assert gc.bound_going_concern(item.model_copy(update={'going_concern_disclosures': [tampered]}),
                                      ticker='GALT', cik=CIK) is None, key


@pytest.mark.parametrize('sentence', [
    'We have from time to time faced substantial doubt about our ability to continue as a going concern.',
    'If we cannot raise capital, these conditions could raise substantial doubt about our ability to continue as a going concern.',
    'Management’s plans alleviate the substantial doubt about the Company’s ability to continue as a going concern.',
])
def test_the_binder_re_applies_the_classification_not_just_the_quote(sentence):
    (item,) = extract(NOTE)
    # A consistent, correctly sourced passage whose conclusion is not a current one is refused.
    forged = _forged(item, quote=sentence, conclusion=sentence, conclusion_offset=0,
                     end_offset=item.going_concern_disclosures[0]['start_offset'] + len(sentence))
    assert gc.bound_going_concern(forged, ticker='GALT', cik=CIK) is None


def test_the_binder_re_applies_the_neighbour_check():
    (item,) = extract(NOTE)
    quote = f'{BELIEF} {CONCLUSION} However, management’s plans alleviate these conditions.'
    value = item.going_concern_disclosures[0]
    forged = _forged(item, quote=quote, end_offset=value['start_offset'] + len(quote))
    assert gc.bound_going_concern(forged, ticker='GALT', cik=CIK) is None


# --- the answer ------------------------------------------------------------------------------------------

def _answer(text=NOTE):
    items = [evidence('Revenues', 'revenue', ticker='GALT', cik=CIK),
             evidence('OperatingIncomeLoss', 'operating income', ticker='GALT', cik=CIK)]
    items += extract(text)
    refs = [reference(item, f'E{n}') for n, item in enumerate(items, start=1)]
    return build_financial_foundation('GALT', items, refs, expected_cik=CIK), refs


def test_the_going_concern_conclusion_is_stated_first_and_cited():
    result, refs = _answer()
    claim = next(row for row in result['claims'] if row['claim_kind'] == 'issuer_going_concern_disclosure')
    assert claim['reference_id'] == 'E3' and any(r['id'] == 'E3' for r in refs)
    answer = result['answer']
    heading = answer.index('Going-concern disclosure in the latest periodic filing')
    assert heading < answer.index('Reported evidence')
    assert claim['claim'] in answer and CONCLUSION in claim['claim'] and '[E3]' in answer
    assert claim['going_concern']['period_end'] == '2026-06-30'
    # It does not turn into a sampled risk or change the unverified parts.
    assert answer.count(CONCLUSION) == 1
    assert 'issuer_disclosed_risk' not in {row['claim_kind'] for row in result['claims']}


def test_no_current_conclusion_means_no_section_and_an_unchanged_answer():
    with_gc, _ = _answer()
    without, _ = _answer(RISK_FACTOR_10K)
    assert 'Going-concern disclosure' not in without['answer']
    assert {row['claim_kind'] for row in without['claims']} == {'reported_financial_comparison'}
    assert without['unanswered_parts'] == with_gc['unanswered_parts']


def test_a_disclosure_only_answer_leads_with_the_going_concern_conclusion():
    from app.services import disclosure_only_answer as only
    assert 'issuer_going_concern_disclosure' in only.DISCLOSURE_ONLY_KINDS
    items = extract(NOTE)
    refs = [reference(item, f'E{n}') for n, item in enumerate(items, start=1)]
    result = only.build_disclosure_only('GALT', items, refs, expected_cik=CIK)
    assert [row['claim_kind'] for row in result['claims']] == ['issuer_going_concern_disclosure']
    assert result['content_scope'] == 'disclosures_only' and CONCLUSION in result['answer']
