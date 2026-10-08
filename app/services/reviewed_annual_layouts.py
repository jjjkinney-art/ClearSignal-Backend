"""Document-specific reviewed integrated annual layouts; never a generic override."""
from copy import deepcopy

_ASML = {
    'registry_id': 'asml-2025-integrated-risk-v1',
    'cik': '937966',
    'url': 'https://www.sec.gov/Archives/edgar/data/937966/000162828026011378/asml-20251231.htm',
    'form': '20-F',
    'filed_at': '2026-02-25',
    'content_hash': 'c7f397cd04b206b5b93a2ee338626885b1dab3b310243b02f78ffa7fd849f1f3',
    'section': 'Strategic report - Risk and security - Risk factors',
    'opening': r'\bRisk and security\s+Risk factors\s+The risk factors outlined in this section\b',
    'closing': r'\bRisk and security\s+Information security\s+We believe\b',
    'mapping': 'D. Risk Factors Risk – Risk factors 66 4 Information on the Company',
    'max_bytes': 30_000_000,
}
REVIEWED_ANNUAL_LAYOUTS = (_ASML,)


def reviewed_annual_layout(url, form, filed_at, *, content_hash=None, cik=None):
    for value in REVIEWED_ANNUAL_LAYOUTS:
        if (url == value['url'] and form == value['form'] and filed_at == value['filed_at']
                and (content_hash is None or content_hash == value['content_hash'])
                and (cik is None or str(cik) == value['cik'])):
            return deepcopy(value)
    return None
