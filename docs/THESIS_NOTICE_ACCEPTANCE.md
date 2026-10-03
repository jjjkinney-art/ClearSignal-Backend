# Thesis Notice Positive-Path Acceptance

This rehearsal proves the positive thesis-notice lifecycle without changing
production research, notices, or delivery state.

## What it exercises

The protected endpoint runs the deployed evidence-admission, owner-selected
notice-candidate, persistence, deduplication, and owner-isolation code against
an ephemeral in-memory database. It verifies that:

- newer, related, admitted evidence creates one eligible candidate;
- repeating the same candidate leaves exactly one notice;
- another account cannot read the notice;
- stale evidence creates no candidate and no row;
- candidate and persisted delivery flags remain disabled; and
- no production database or external-delivery path is used.

All identities and evidence in this rehearsal are synthetic. The response is
aggregate-only and contains no account or research content.

## Production-equivalent command

Use a current admin access token. Do not include Markdown link syntax around
the URL.

```bash
export T="$(pbpaste)"

curl -fsS -X POST \
  -H "Authorization: Bearer $T" \
  'https://clearsignal-backend-dlsc.onrender.com/admin/research-memory/thesis-notice-rehearsal' \
  | python3 -m json.tool
```

Acceptance requires `passed: true`, every check `true`,
`persisted_count: 1`, `foreign_owner_count: 0`, and
`delivery_enabled: false`.

This rehearsal does not replace a later natural-evidence UI acceptance run.
That live run must use a real owner-selected thesis and genuinely newer public
evidence; ClearSignal must never manufacture either condition merely to create
a notice.
