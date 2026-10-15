import json
import shutil

import pytest

from scripts.benchmark_company_quality_expansion import main
from validation import company_quality_expansion as expansion
from validation.intelligence_benchmark import BenchmarkContractError


def test_frozen_scope_and_authority_remain_separate(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('DNS forbidden'))
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('network forbidden'))
    p = expansion.build_expansion_plan()
    assert p['total'] == {'issuer_count': 100, 'case_count': 600,
                         'by_market_cap': {'mega_large': 40, 'mid': 30, 'small_micro': 30}}
    assert p['development']['case_count'] == 480 and p['reserved_holdout']['case_count'] == 120
    assert p['development']['issuer_count'] == len(set(p['development_issuers'])) == 80
    assert p['stages'][1]['case_count'] == 160
    assert p['external_prior_holdout_exposure'] == 'unknown'
    assert p['quality_pass_rate'] is None and p['quality_status'] == 'not_adjudicated'
    for field in ('execution_authorized', 'spending_authorized', 'production_activation_authorized', 'launch_ready'):
        assert p[field] is False
    assert p['captures_executed_by_this_plan'] == 0
    assert p['acceptance_targets']['material_claim_source_binding_minimum'] == '1.00'
    assert len(p['question_families']) == 6


@pytest.fixture
def copied_setup(tmp_path):
    for name in (*expansion.FROZEN_SETUP_SHA256, 'fixtures.v2.json'):
        shutil.copyfile(expansion.SETUP_DIR / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize('name', [*expansion.FROZEN_SETUP_SHA256, 'fixtures.v2.json'])
def test_changed_setup_is_not_rebaselined(copied_setup, name):
    path = copied_setup / name
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(BenchmarkContractError):
        expansion.build_expansion_plan(setup_dir=copied_setup)


@pytest.mark.parametrize('name', [*expansion.FROZEN_SETUP_SHA256, 'fixtures.v2.json'])
def test_missing_setup_does_not_make_a_smaller_plan(copied_setup, name):
    (copied_setup / name).unlink()
    with pytest.raises(OSError):
        expansion.build_expansion_plan(setup_dir=copied_setup)


def test_builder_drift_is_rejected(monkeypatch):
    monkeypatch.setattr(expansion, 'build_matrix', lambda **k: {'case_count': 6})
    with pytest.raises(BenchmarkContractError, match='canonical'):
        expansion.build_expansion_plan()


def test_symlinked_setup_is_rejected(copied_setup, tmp_path):
    path = copied_setup / 'issuer_registry.v2.json'
    target = tmp_path / 'copy.json'
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(BenchmarkContractError):
        expansion.build_expansion_plan(setup_dir=copied_setup)


def test_cli_never_overwrites_input_or_existing_result(tmp_path):
    output = tmp_path / 'plan.json'
    assert main(['--output', str(output)]) == 0
    original = output.read_bytes()
    assert json.loads(original)['execution_authorized'] is False
    with pytest.raises(SystemExit): main(['--output', str(output)])
    assert output.read_bytes() == original


def test_cli_has_no_execution_path(tmp_path):
    output = tmp_path / 'plan.json'
    with pytest.raises(SystemExit): main(['--output', str(output), '--execute'])
    assert not output.exists()
