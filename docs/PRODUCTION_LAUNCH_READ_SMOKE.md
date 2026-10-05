# Production launch read-smoke runbook

Status: **non-mutating release check.** This harness reads public and
account-owned production surfaces only. It does not create an analysis, append a
message, update preferences, mark notices, log out, import data, or delete
anything.

## What it verifies

1. Backend health, database readiness and deployed version.
2. Frontend Intelligence and History pages respond.
3. Protected research routes reject unsigned requests with HTTP 401.
4. A signed-in token resolves to an authenticated, non-bypass account.
5. Private conversation, personalization, notice, recall and export reads work.
6. Research export carries `Cache-Control: private, no-store` and an attachment
   filename.

The harness prints aggregate pass/fail metadata only. It never prints the token,
authorization header, account ID, email, conversation content, notices,
preferences, recall results or export body.

## Full signed-in production check

Use a fresh bearer token copied from a signed-in ClearSignal browser request.
Copy only the JWT after `Bearer `.

Because copying a shell command would replace the token in the clipboard,
manually type this command immediately after copying the token:

```bash
export CLEARSIGNAL_SMOKE_ACCESS_TOKEN="$(pbpaste)"
```

Confirm only its structure and length:

```bash
printf '%s\n' "$CLEARSIGNAL_SMOKE_ACCESS_TOKEN" \
  | awk -F. '{print "JWT parts:", NF, "characters:", length}'
```

A valid JWT has three parts. Never paste the token into chat, a commit, a file,
or a command-line argument.

From the backend repository:

```bash
python3 scripts/launch_read_smoke.py
```

Success requires exit code 0, `"passed": true`, and zero failed checks.

## Public and unsigned boundary check

This limited mode does not require a token:

```bash
python3 scripts/launch_read_smoke.py --public-only
```

It is useful for deployment triage but does not establish signed-in launch
readiness.

## Failure handling

- HTTP 401 on signed-in checks: copy a fresh token and re-export the environment
  variable.
- Readiness mismatch: inspect Render database and migration state; do not proceed
  with launch.
- Frontend failure: inspect the active Vercel production deployment.
- Protected route returns anything other than 401 unsigned: treat as a security
  release blocker.
- Export header mismatch: treat as a privacy release blocker.
- Any failure: record only the check name, HTTP status and deployment commit.
  Do not record response bodies or tokens.

Unset the token after the run:

```bash
unset CLEARSIGNAL_SMOKE_ACCESS_TOKEN
```
