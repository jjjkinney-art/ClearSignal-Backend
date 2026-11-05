#!/usr/bin/env bash
# "Full repository regression (isolated per file)".
# Same files, same flags, one fresh interpreter per file. Most files run in a pool;
# files that bind fixed loopback ports, drive the isolated workers or depend on
# deadlines run one at a time afterwards, because a busy port would make a test
# SKIP and a loaded runner would make a deadline test mean something else.
set -uo pipefail
PY="${PY:-python}"; WORKERS="${WORKERS:-4}"
results=$(mktemp -d); export results PY
SERIAL_RE="_ordinary_loopback_sec|_ordinary_rehearsal_worker|_pilot_worker|_source_capture_worker|8443|127\\.0\\.0\\.1', 80"
run_one() {
  local f=$1 key s st; key=${f//\//__}; s=$SECONDS
  "$PY" -m pytest -q -o addopts="" --disable-warnings --tb=short "$f" >"$results/$key.out" 2>&1; st=$?
  printf '%s\t%s\t%s\n' "$st" "$((SECONDS-s))" "$f" >"$results/$key.status"
  # One short line as each file ends, so a timed-out job still shows its progress.
  printf 'finished status=%s seconds=%s %s\n' "$st" "$((SECONDS-s))" "$f"
}
export -f run_one
if [ $# -gt 0 ]; then test_files=("$@"); else mapfile -d '' test_files < <(find tests -name 'test_*.py' -print0 | sort -z); fi
pool=(); serial=()
for f in "${test_files[@]}"; do
  case "$f" in
    */test_ordinary_*|*/test_pilot_*) serial+=("$f") ;;
    *) if grep -Eq "$SERIAL_RE" "$f"; then serial+=("$f"); else pool+=("$f"); fi ;;
  esac
done
start=$SECONDS
((${#pool[@]})) && printf '%s\0' "${pool[@]}" | xargs -0 -n 1 -P "$WORKERS" bash -c 'run_one "$1"' _
pool_s=$((SECONDS-start)); start=$SECONDS
for f in "${serial[@]:-}"; do [ -n "$f" ] && run_one "$f"; done
failures=()
for f in "${test_files[@]}"; do
  key=${f//\//__}; printf '=== %s\n' "$f"; cat "$results/$key.out" 2>/dev/null; echo
  # Every discovered file must have reported: a crash or lost worker is a failure, not a pass.
  if [ ! -s "$results/$key.status" ]; then failures+=("$f (no result)"); continue; fi
  st=$(cut -f1 "$results/$key.status")
  if [ "$st" = 5 ] && grep -Eq '[0-9]+ skipped' "$results/$key.out"; then continue; fi
  [ "$st" = 0 ] || failures+=("$f")
done
printf 'files=%s pool=%s (%ss) serial=%s (%ss)\n' "${#test_files[@]}" "${#pool[@]}" "$pool_s" "${#serial[@]}" "$((SECONDS-start))"
printf 'Slowest:\n'; cat "$results"/*.status | sort -t$'\t' -k2,2nr | head -10
if ((${#failures[@]})); then printf 'Failed test files:\n'; printf ' - %s\n' "${failures[@]}"; exit 1; fi
