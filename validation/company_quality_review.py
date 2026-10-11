"""Offline integrity checks and pending-review worksheets; never a quality grader."""
from __future__ import annotations

from collections import Counter
from typing import Any
import math

from .benchmark_registry import IssuerRegistry, load_registry
from .company_quality_matrix import build_matrix
from .intelligence_benchmark import BenchmarkContractError, content_hash
from .pipeline_capture import MAX_CASES


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkContractError(message)


def _json_value(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise BenchmarkContractError('inputs must contain only finite JSON values')


def _same(actual: Any, expected: Any, name: str) -> None:
    # Canonical JSON distinguishes booleans from integers (unlike Python ==).
    _require(content_hash(actual) == content_hash(expected), f"{name} does not match canonical value")


def reconcile_captures(plan: dict, batches: list[dict], *, registry: IssuerRegistry | None = None) -> dict:
    """Validate all inputs before returning any worksheet; no provider imports/calls."""
    _json_value(plan)
    _json_value(batches)
    registry = registry or load_registry()
    _require(isinstance(plan, dict) and isinstance(plan.get('cases'), list) and bool(plan['cases']),
             'canonical plan requires nonempty cases')
    _require(all(isinstance(row, dict) and isinstance(row.get('issuer_id'), str) for row in plan['cases']),
             'plan cases require issuer identities')
    families = plan.get('question_families')
    _require(isinstance(families, list) and all(isinstance(x, str) for x in families), 'invalid question families')
    canonical = build_matrix(registry=registry, tickers=sorted({row['issuer_id'] for row in plan['cases']}), families=families)
    _same(plan, canonical, 'plan')
    _require(isinstance(batches, list), 'batches must be a list')
    rows = canonical['cases']
    observed: dict[int, dict] = {}
    origins: dict[int, list[int]] = {}
    batch_hashes = []
    safety = dict(research_memory_enabled=False, personalization_enabled=False,
                  persistence_enabled=False, notification_delivery_enabled=False, authenticated_api_tested=False)
    for batch_index, batch in enumerate(batches):
        _require(isinstance(batch, dict), 'batch must be an object')
        for key, expected in canonical.items():
            if key != 'cases':
                _same(batch.get(key), expected, f'batch {key}')
        _same(batch.get('capture_safety'), safety, 'capture safety')
        _same(batch.get('quality_status'), 'not_adjudicated', 'quality status')
        _require('quality_pass_rate' in batch and batch['quality_pass_rate'] is None, 'quality must remain unset')
        _require(batch.get('launch_ready') is False, 'capture cannot establish launch readiness')
        execute = batch.get('execution_enabled')
        _require(type(execute) is bool, 'execution_enabled must be boolean')
        offset, selected = batch.get('offset'), batch.get('selected_case_count')
        _require(type(offset) is int and 0 <= offset < len(rows), 'invalid batch offset')
        _require(type(selected) is int and 1 <= selected <= min(MAX_CASES, len(rows)-offset), 'invalid selected count')
        cases = batch.get('cases')
        _require(isinstance(cases, list) and len(cases) <= selected, 'invalid batch cases')
        _same(batch.get('next_offset'), offset + len(cases), 'next offset')
        _same(batch.get('batch_complete'), len(cases) == selected, 'batch completion')
        for index, row in enumerate(cases, offset):
            _require(isinstance(row, dict), 'capture case must be an object')
            for key, expected in rows[index].items():
                _same(row.get(key), expected, f'case {key}')
            _same(row.get('review_status'), 'not_reviewed', 'review status')
            status = row.get('capture_status')
            _require(status in (('captured', 'execution_failed') if execute else ('not_executed',)), 'invalid capture status')
            if status == 'captured':
                _require(isinstance(row.get('response'), dict), 'captured response must be an object')
                _same(row.get('response_sha256'), content_hash(row['response']), 'response hash')
            else:
                _require('response' not in row and 'response_sha256' not in row, 'uncaptured case contains response')
            if status == 'execution_failed':
                _require(isinstance(row.get('error_class'), str) and bool(row['error_class'].strip()), 'failed case requires error class')
            if index in observed:
                _same(row, observed[index], 'overlapping case')
            else:
                observed[index] = row
            origins.setdefault(index, []).append(batch_index)
        statuses = Counter(row['capture_status'] for row in cases)
        _same(batch.get('capture_counts'), dict(statuses), 'capture counts')
        for field, dimension, values in (
            ('capture_by_market_cap', 'market_cap_tier', canonical['market_cap_counts']),
            ('capture_by_question_family', 'question_id', families),
        ):
            expected = {value: dict(Counter(row['capture_status'] for row in cases
                if (row['dimensions'][dimension] if dimension != 'question_id' else row[dimension]) == value)) for value in values}
            _same(batch.get(field), expected, field)
        active = batch.get('active_case')
        if active is not None:
            _require(execute and len(cases) < selected and isinstance(active, dict), 'invalid active checkpoint')
            for key in ('issuer_id', 'question_id'):
                _same(active.get(key), rows[offset + len(cases)][key], 'active case')
        batch_hashes.append(content_hash(batch))
    worksheet = []
    for index, expected in enumerate(rows):
        captured = observed.get(index)
        row = dict(expected, capture_status=captured['capture_status'] if captured else 'missing',
                   source_batch_indexes=origins.get(index, []), factual_review_status='pending',
                   citation_review_status='pending', usefulness_review_status='pending')
        if captured and captured['capture_status'] == 'captured':
            row.update(response=captured['response'], response_sha256=captured['response_sha256'])
        elif captured and captured['capture_status'] == 'execution_failed':
            row['error_class'] = captured.get('error_class')
        worksheet.append(row)
    return dict(schema_version=1, matrix_sha256=canonical['matrix_sha256'], registry_sha256=registry.registry_sha256,
        input_batch_sha256=batch_hashes, case_count=len(rows), cases=worksheet,
        capture_counts=dict(Counter(row['capture_status'] for row in worksheet)),
        capture_by_market_cap={tier: dict(Counter(row['capture_status'] for row in worksheet if row['dimensions']['market_cap_tier'] == tier)) for tier in canonical['market_cap_counts']},
        capture_by_question_family={family: dict(Counter(row['capture_status'] for row in worksheet if row['question_id'] == family)) for family in families},
        quality_status='not_adjudicated', quality_pass_rate=None, launch_ready=False,
        provenance_status='build_and_execution_provenance_unavailable',
        limitations=['Hashes verify supplied artifact consistency, not authenticity or live execution.',
                     'Matrix run_id is deterministic and does not identify a deployment or execution.',
                     'Primary-source factual/citation adjudication and independent usefulness reviews remain pending.',
                     'No representative coverage, unseen holdout or signed-in acceptance is established.'])
