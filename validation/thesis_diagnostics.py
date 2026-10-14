"""Bounded, allowlisted extraction diagnostics; no document text or secrets."""
import logging
from threading import Lock


def safe_thesis_diagnostic(value):
    if type(value) is not dict:
        return None
    stages = {'eligibility', 'identity', 'annual_discovery', 'quarterly_discovery',
              'quarterly_document', 'annual_document', 'extraction'}
    statuses = {'not_requested', 'identity_unavailable', 'annual_metadata_absent',
                'quarterly_document_unavailable', 'unsupported_form',
                'document_unavailable', 'extraction_complete', 'document_error',
                'retrieval_or_extraction_error'}
    if (type(value.get('stage')) is not str or type(value.get('status')) is not str
            or value['stage'] not in stages or value['status'] not in statuses):
        return None
    result = {k: value[k] for k in ('stage', 'status')}
    for key in ('business_count', 'competition_count', 'risk_count'):
        count = value.get(key)
        if type(count) is int and 0 <= count <= 2000:
            result[key] = count
    if type(value.get('document_failure_kind')) is str and value['document_failure_kind'] in {
            'http_error', 'dns_error', 'timeout', 'document_rejected', 'network_error'}:
        result['document_failure_kind'] = value['document_failure_kind']
    status = value.get('http_status')
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    extraction = value.get('business_extraction')
    if type(extraction) is dict:
        accepted = {}
        if type(extraction.get('status')) is str and extraction['status'] in {'document_ineligible', 'no_complete_business_section',
                'no_qualifying_business_sentence', 'business_extracted',
                'reviewed_predecessor_risk_context_only'}:
            accepted['status'] = extraction['status']
        for key in ('sentences', 'heading_prefixes_removed', 'extracted_descriptions'):
            count = extraction.get(key)
            if type(count) is int and 0 <= count <= 2000:
                accepted[key] = count
        reasons = extraction.get('rejection_counts')
        if type(reasons) is dict:
            accepted['rejection_counts'] = {key: count for key, count in reasons.items()
                if key in {'length', 'numeric_or_forward_looking', 'subject_or_activity',
                           'aspirational_or_promotional', 'internal_employee_activity',
                           'internal_hosting_activity'}
                and type(count) is int and 0 <= count <= 2000}
        result['business_extraction'] = accepted
    return result


class ThesisDiagnosticCollector(logging.Handler):
    """One case at a time; the worker drains before advancing to another case."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.case_id = None
        self.sealed = False
        self.lock = Lock()

    def begin(self, case_id):
        with self.lock:
            if not self.sealed:
                self.case_id = case_id

    def snapshot(self):
        with self.lock:
            self.sealed = True
            return list(self.rows)

    def emit(self, record):
        if record.name != 'app.services.thesis_disclosures':
            return
        row = safe_thesis_diagnostic(getattr(record, 'thesis_disclosure_diagnostics', None))
        if not self.sealed and row is not None and self.case_id is not None:
            # Logging owns self.lock during emit. No exception message or
            # formatted log record is ever used here.
            if len(self.rows) < 6:
                self.rows.append({'case_id': self.case_id, **row})
