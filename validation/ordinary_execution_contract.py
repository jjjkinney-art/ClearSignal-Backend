"""Pending twelve-case execution contract. This module cannot launch anything.

Human approval, identity, price certainty, safe output creation, actual network
enforcement, and code binding verification must be handled by a future launcher.
Never use this validator alone as authority to access a provider.
"""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from .ordinary_pilot_contract import CASES, quota_contract, validate_contract

# Projection of the twelve run-3 case records in tests/ordinary_run3_cases.json
# (file SHA-256 28e88911a66fc4d19af4c4562df67307623d043a413a8a8c71ec84e2c04046c5).
PACKET_CASE_PROJECTION_SHA256 = 'a87bd50548790b0e3e42ed1a3fc31513764296352a3d4cd54dd4c49ac2cfdfa6'
# Runs 1 and 2: the review packet's cases.json (file SHA-256
# af2fd4a2c5edbd9fab88390553baed840350499753a70f5c75a38a42145c258e).
RUN_1_2_CASE_PROJECTION_SHA256 = 'fa9159abaf5b396bee5a5d51c55031044a148f94997709ea601e49f0508747e3'

def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def pending_manifest(*, cases, source_sha256, dependency_sha256, output_dir,
                     all_in_usd, retention_reference):
    """Bind supplied inputs into a proposed manifest; no approval is generated."""
    if (type(cases) is not list or len(cases) != len(CASES)
            or any(type(c) is not dict or set(c) != {'case_id', 'issuer_id', 'expected_cik', 'question', 'question_id'}
                   or c['case_id'] != case or c['issuer_id'] != case.split(':')[0]
                   or c['question_id'] != case.split(':')[1]
                   or type(c['expected_cik']) is not str or not re.fullmatch(r'[0-9]{10}', c['expected_cik'])
                   or type(c['question']) is not str or not c['question'].strip()
                   for c, case in zip(cases, CASES))):
        raise ValueError('exact ordered case records required')
    if _digest(cases) != PACKET_CASE_PROJECTION_SHA256:
        raise ValueError('case records differ from review packet')
    if any(type(v) is not str or not re.fullmatch(r'[0-9a-f]{64}', v)
           for v in (source_sha256, dependency_sha256)):
        raise ValueError('source and dependency digests required')
    if (type(output_dir) is not str or not output_dir.startswith('/')
            or str(PurePosixPath(output_dir)) != output_dir or '..' in PurePosixPath(output_dir).parts
            or output_dir == '/'):
        raise ValueError('normalized absolute output directory required')
    if (type(retention_reference) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', retention_reference)):
        raise ValueError('reviewable retention terms reference required')
    if type(all_in_usd) is not str or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})\.[0-9]{2}', all_in_usd):
        raise ValueError('explicit all-in USD ceiling required')
    try:
        if not Decimal(all_in_usd).is_finite() or Decimal(all_in_usd) < 0:
            raise ValueError('invalid cost ceiling')
    except InvalidOperation:
        raise ValueError('invalid cost ceiling') from None
    return {'purpose': 'ordinary_twelve_case_pilot_pending', 'schema_version': 1,
            'case_records_sha256': _digest(cases), 'case_order': list(CASES),
            'source_sha256': source_sha256, 'dependency_sha256': dependency_sha256,
            'output_dir': output_dir, 'all_in_usd': all_in_usd,
            'retention_reference': retention_reference, 'limits': quota_contract(),
            'case_seconds': {'core_thesis': 30, 'decision_threshold': 20},
            'sec_dispatches_per_second': 10, 'follow_redirects': False,
            'retry_attempts': 0, 'approval_status': 'pending',
            'invoice_ceiling_verified': False, 'execution_authorized': False}


def matches_separate_approval(manifest, approval):
    """Check proposal/approval binding only; return no execution capability."""
    manifest_keys = {'purpose', 'schema_version', 'case_records_sha256', 'case_order',
                     'source_sha256', 'dependency_sha256', 'output_dir', 'all_in_usd',
                     'retention_reference', 'limits', 'case_seconds', 'sec_dispatches_per_second',
                     'follow_redirects', 'retry_attempts', 'approval_status',
                     'invoice_ceiling_verified', 'execution_authorized'}
    keys = {'reference', 'manifest_sha256', 'output_dir', 'all_in_usd',
            'execution_allowed', 'spending_authorized'}
    if type(manifest) is not dict or set(manifest) != manifest_keys:
        raise ValueError('invalid proposal manifest')
    validate_contract(manifest['limits'])
    output = manifest['output_dir']
    if (manifest.get('purpose') != 'ordinary_twelve_case_pilot_pending'
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or manifest.get('approval_status') != 'pending' or manifest.get('execution_authorized') is not False
            or manifest['invoice_ceiling_verified'] is not False
            or manifest.get('case_records_sha256') != PACKET_CASE_PROJECTION_SHA256
            or type(manifest['case_order']) is not list or manifest['case_order'] != list(CASES)
            or type(manifest['case_seconds']) is not dict
            or set(manifest['case_seconds']) != {'core_thesis', 'decision_threshold'}
            or any(type(manifest['case_seconds'][k]) is not int or manifest['case_seconds'][k] != v
                   for k, v in {'core_thesis': 30, 'decision_threshold': 20}.items())
            or type(manifest['sec_dispatches_per_second']) is not int or manifest['sec_dispatches_per_second'] != 10
            or manifest['follow_redirects'] is not False or type(manifest['retry_attempts']) is not int
            or manifest['retry_attempts'] != 0
            or any(type(manifest[k]) is not str or not re.fullmatch(r'[0-9a-f]{64}', manifest[k])
                   for k in ('source_sha256', 'dependency_sha256'))
            or type(output) is not str or not output.startswith('/') or output == '/'
            or str(PurePosixPath(output)) != output or '..' in PurePosixPath(output).parts
            or type(manifest['all_in_usd']) is not str
            or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})\.[0-9]{2}', manifest['all_in_usd'])
            or type(manifest['retention_reference']) is not str
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', manifest['retention_reference'])
            or type(approval) is not dict or set(approval) != keys
            or type(approval['reference']) is not str
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', approval['reference'])
            or approval['reference'] in {'pending', 'NO_SPENDING_AUTHORITY'}
            or approval['manifest_sha256'] != _digest(manifest)
            or approval['output_dir'] != manifest.get('output_dir')
            or approval['all_in_usd'] != manifest.get('all_in_usd')
            or approval['execution_allowed'] is not True or approval['spending_authorized'] is not True):
        raise ValueError('separate matching approval required')
    return {'binding_matches': True, 'execution_authorized': False,
            'invoice_ceiling_verified': False, 'identity_verified': False}
