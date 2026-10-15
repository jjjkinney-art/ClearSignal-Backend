"""Separate fixed monitoring-freshness pilot policy; offline by default."""
from validation.capture_budget import BudgetError, digest
from validation.pilot_fixtures import SOURCE_MONITORING_SCENARIOS

VARIANT = 'source_monitoring_freshness'
DISABLED_PURPOSE = 'disabled_monitoring_freshness_validation'
APPROVED_PURPOSE = 'approved_monitoring_freshness_pilot'
SCENARIOS = SOURCE_MONITORING_SCENARIOS | frozenset({'freshness_financial_inputs'})


def stage_quotas(case_ids):
    result = {}
    for case in case_ids:
        core = case.endswith(':core_thesis')
        stages = ['evidence.sec', 'evidence.sec_metrics', 'evidence.filing_metrics']
        if core:
            stages.append('evidence.thesis_disclosures')
        result[case] = {stage: {'sec/directory': 1, 'sec/submissions': 0,
                               'sec/facts': 0, 'sec/document': 0} for stage in stages}
        result[case]['evidence.sec']['sec/submissions'] = 1
        result[case]['evidence.sec_metrics']['sec/facts'] = 1
        result[case]['evidence.filing_metrics'].update({'sec/submissions': 1, 'sec/document': 1})
        if core:
            result[case]['evidence.thesis_disclosures'].update({'sec/submissions': 1, 'sec/document': 1})
    return result


def policy_for(binding, dependencies, *, approved=False, approval=None, execution=None):
    from validation.pilot_policy import policy_for as base_policy
    from validation.pilot_approved import validate_execution, validate_approval
    if approved:
        validate_execution(execution)
        validate_approval(approval, binding, execution, monitoring=True, freshness=True)
    elif approval is not None or execution is not None:
        raise BudgetError('offline freshness validation has no authority')
    p = base_policy(binding, dependencies, mode='source_monitoring')
    p['configuration']['variant'] = VARIANT
    p['configuration']['settings']['decision_monitoring_filing_fallback_enabled'] = True
    p['configuration_version'] = digest(p['configuration'])
    p.update(purpose=DISABLED_PURPOSE, pilot_id='frozen-v2-six-case-monitoring-freshness', maximum_attempts=39)
    p['quotas']['overall'] = {'model': 0, 'sec': 39}
    for case, limits in p['quotas']['per_case'].items():
        if case.endswith(':decision_threshold'):
            limits.update({'sec': 5, 'sec/submissions': 2, 'sec/document': 1})
    p['stage_quotas'] = stage_quotas(p['approved_case_ids'])
    if approved:
        p.update(purpose=APPROVED_PURPOSE, pilot_id=approval['run_id'], approval_reference=approval['reference'],
                 approval=approval, execution_configuration=execution, execution_allowed=True, spending_authorized=True)
    return p


def main(argv=None):
    from validation.pilot_rehearsal import main as launch
    return launch(argv, mode='freshness')


def financial_fixture(identity, *, facts):
    """Invented older Company Facts and newer same-concept annual inline pairs."""
    import json
    from validation.pilot_fixtures import monitoring_fact_fixture
    if facts:
        data = monitoring_fact_fixture(identity)
        for concept in data['facts']['us-gaap'].values():
            for row in concept['units']['USD']:
                year = int(row['end'][:4]) - 1
                row.update(start=f'{year}-01-01', end=f'{year}-12-31',
                           filed=f'{year+1}-03-01', accn=f"{identity['cik']}-{str(year+1)[-2:]}-000001")
        return json.dumps(data).encode()
    def context(key, year):
        return f'<xbrli:context id="{key}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{identity["cik"]}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{year}-01-01</xbrli:startDate><xbrli:endDate>{year}-12-31</xbrli:endDate></xbrli:period></xbrli:context>'
    values = {'Revenues':(300,200), 'OperatingIncomeLoss':(60,40),
              'NetIncomeLoss':(45,30), 'NetCashProvidedByUsedInOperatingActivities':(70,50)}
    rows=[]
    for concept,(current,prior) in values.items():
        for key,value in [('current',current),('prior',prior)]:
            rows.append(f'<ix:nonFraction id="{concept}-{key}" name="us-gaap:{concept}" contextRef="{key}" unitRef="usd" decimals="0">{value}</ix:nonFraction>')
    return (f'<html xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"><body><ix:header><ix:resources>{context("current",2025)}{context("prior",2024)}<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header>'
            + ''.join(rows) + '<h2>Item 1. Business</h2><p>We manufacture specialized products and sell them to independent retailers.</p><h2>Item 1A. Risk Factors</h2><p>Supply disruption could adversely affect our product sales and results.</p><h2>Item 2. Properties</h2></body></html>').encode()


if __name__ == '__main__':
    raise SystemExit(main())
