"""Invented sentinel homes only. Never inspect the developer's real home/netrc."""
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('probe', ['normal_and_copy', 'session_drift', 'sessions_alias',
                                  'utils_alias', 'saved_alias', 'saved_prepare'])
def test_netrc_never_read_before_synthetic_sec_send(tmp_path, probe):
    sentinel = tmp_path / 'sentinel-home'
    sentinel.mkdir()
    contact_canary = 'invented-netrc-contact-canary'
    password_canary = 'invented-netrc-password-canary'
    for name in ('.netrc', '_netrc', 'custom-netrc'):
        (sentinel / name).write_text('machine www.sec.gov login ' + contact_canary
                                    + ' password ' + password_canary + '\n')
    home = tmp_path / 'isolated-home'
    home.mkdir()
    # Construct, never copy, the environment. NETRC and passwd's home point to
    # readable synthetic sentinels, while HOME is a fresh empty directory.
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(home),
                   'NETRC': str(sentinel / 'custom-netrc'),
                   'PYTHONDONTWRITEBYTECODE': '1',
                   'CLEARSIGNAL_BENCHMARK_CAPTURE_ENABLED': 'false'}
    code = r'''
import copy,json,os,pwd,socket,sys
from pathlib import Path
from types import SimpleNamespace
root, sentinel, probe = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0,str(root))
socket.has_ipv6=False
reads=[]
pwd_calls=[]
def audit(event,args):
    if event.startswith('socket.'):
        raise RuntimeError('offline test prohibits sockets')
    if event=='open' and isinstance(args[0],(str,bytes)):
        path=Path(args[0]).resolve()
        if path.is_relative_to(sentinel):
            reads.append('forbidden_sentinel_read')
            raise RuntimeError('synthetic sentinel must not be read')
sys.addaudithook(audit)
def synthetic_passwd(uid):
    pwd_calls.append(True)
    return SimpleNamespace(pw_dir=str(sentinel))
pwd.getpwuid=synthetic_passwd
import requests
saved_alias=requests.utils.get_netrc_auth
saved_prepare=requests.sessions.Session.prepare_request
from validation.capture_budget import AttemptLedger,BudgetError
from validation.pilot_policy import policy_for,AUDITED_DEPENDENCIES,PILOT_SETTINGS
from validation.pilot_fixtures import SYNTHETIC_CONTACT
from validation.pilot_boundary import PilotBoundary
policy=policy_for({'revision':'synthetic-unit','source_sha256':'synthetic-unit'},dict(AUDITED_DEPENDENCIES))
book=AttemptLedger(Path.cwd()/'ledger.sqlite',policy,create=True)
boundary=PilotBoundary(book,'happy')
boundary.settings=SimpleNamespace(**PILOT_SETTINGS,sec_user_agent=SYNTHETIC_CONTACT,
                                 fmp_api_key='',fred_api_key='')
boundary.install()
boundary.begin(boundary.cases[0])
token=boundary.stage.set('evidence.sec')
url='https://www.sec.gov/files/company_tickers.json'
refused=False
try:
    session=requests.Session()
    assert session.trust_env is False
    if probe=='normal_and_copy':
        for client in (session,copy.copy(session)):
            assert client.trust_env is False
            assert client.get(url,timeout=15).status_code==200
    else:
        try:
            if probe=='session_drift':
                session.trust_env=True
                session.get(url,timeout=15)
            elif probe=='sessions_alias': requests.sessions.get_netrc_auth(url)
            elif probe=='utils_alias': requests.utils.get_netrc_auth(url)
            elif probe=='saved_alias': saved_alias(url)
            elif probe=='saved_prepare':
                session.trust_env=True
                saved_prepare(session,requests.Request('GET',url))
        except BudgetError:
            refused=True
finally:
    boundary.stage.reset(token)
    boundary.close()
summary=book.summary()
assert not reads and not pwd_calls
assert boundary.sec_authorization_header_absent
assert summary['attempts']==(2 if probe=='normal_and_copy' else 0)
assert refused==(probe!='normal_and_copy')
print(json.dumps({'sentinel_reads':len(reads),'passwd_fallbacks':len(pwd_calls),
                  'auth_header_absent':boundary.sec_authorization_header_absent,
                  'refused':refused,'attempts':summary['attempts']}))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
                             str(ROOT), str(sentinel), probe], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert contact_canary not in result.stdout + result.stderr
    assert password_canary not in result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value['sentinel_reads'] == value['passwd_fallbacks'] == 0
    assert value['auth_header_absent']
    for path in tmp_path.rglob('*'):
        if path.is_file() and not path.is_relative_to(sentinel):
            assert contact_canary.encode() not in path.read_bytes()
            assert password_canary.encode() not in path.read_bytes()
