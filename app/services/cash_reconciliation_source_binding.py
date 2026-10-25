"""Bind a reconstruction to supplied original filing bytes; no answer admission.

Caller metadata and receipt hashes are consistency inputs, not independent
authentication. The original source must come from the validated document path.
"""
from datetime import date
import hashlib
import json
import re

from app.integrity.provenance import ClaimDocumentReference
from app.providers import sec_cash_reconciliation as parser


def bind_cash_reconciliation(proof, *, source_body, content_hash, cik, currency,
                             url, filed_at, evaluated_at, title, document_type,
                             availability_status, freshness_status):
    """Return source-consistent row references, never publishable thesis evidence."""
    try:
        if (type(source_body) is not bytes or not 0 < len(source_body) <= parser.MAX_XML
                or not isinstance(cik, str) or not re.fullmatch(r'\d{1,10}', cik) or int(cik) == 0
                or document_type != '10-K' or availability_status != 'available'
                or freshness_status not in {'fresh', 'recent'}
                or not isinstance(title, str) or not 0 < len(title.strip()) <= 300
                or not isinstance(url, str) or not re.fullmatch(
                    rf'https://www\.sec\.gov/Archives/edgar/data/{int(cik)}/[0-9]{{18}}/[A-Za-z0-9_.-]+\.htm(?:l)?', url)
                or not isinstance(content_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', content_hash)
                or hashlib.sha256(source_body).hexdigest() != content_hash):
            return None
        filed, evaluated = date.fromisoformat(filed_at), date.fromisoformat(evaluated_at)
        if filed.isoformat() != filed_at or evaluated.isoformat() != evaluated_at or filed > evaluated:
            return None
        text = source_body.decode('utf-8')
        # Regenerate the complete capsule from the supplied source. Arithmetic
        # on the caller's capsule alone cannot detect offsetting omissions.
        rebuilt = parser.parse_cash_reconciliations(text, cik=cik, currency=currency)
        if len(rebuilt) != 1 or json.dumps(proof, sort_keys=True, allow_nan=False) != json.dumps(rebuilt[0], sort_keys=True, allow_nan=False):
            return None
        if rebuilt[0]['source_sha256'] != content_hash:
            return None
        bridge = parser.reconstruct_cash_reconciliation(rebuilt[0], cik=cik, currency=currency)
        if not bridge or any(date.fromisoformat(t['end']) > filed for t in bridge['totals']):
            return None
        root, _, _ = parser._read(text, parser.MAX_XML)
        source_rows = {}
        for tr in root.iter('{' + parser.XHTML + '}tr'):
            for fact in tr.iter('{' + parser.base.IX + '}nonFraction'):
                source_rows[fact.get('id')] = tr
        references = []
        for index, row in enumerate(bridge['rows']):
            fact_ids = [v['fact_id'] for v in row['values']]
            tr = source_rows[fact_ids[0]]
            if any(source_rows[fact_id] is not tr for fact_id in fact_ids):
                return None
            quote = ' '.join(' '.join(parser._clean(c) for c in tr).split())
            # Keep the complete printed row. Long rows stay gaps; do not widen
            # the normal quote cap or clip off a comparison column.
            ref = ClaimDocumentReference(
                reference_id=f'document:{content_hash}:cash_table:{proof["table_number"]}:row:{index}',
                title=title.strip(), provider='SEC EDGAR', url=url + '#' + fact_ids[0],
                published_at=filed_at, section='Consolidated annual statement of cash flows',
                content_hash=content_hash, quote=quote).to_dict()
            references.append({'label': row['label'], 'fact_ids': fact_ids,
                               'document_ref': ref})
        return {'bridge': {**bridge, 'source_binding_established': True},
            'row_references': references, 'source_sha256': content_hash,
            'source_url': url, 'filed_at': filed_at, 'evaluated_at': evaluated_at,
            'source_binding_scope': 'exact_supplied_document_bytes',
            'independent_origin_verification': False, 'admitted': False,
            'launch_ready': False}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError):
        return None
