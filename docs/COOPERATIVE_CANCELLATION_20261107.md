# Cooperative cancellation and stage timing (2026-11-07)

Run 7's `MNST:core_thesis` halted with one worker still running after the application abandoned its filing task. A running task could not be stopped, because abandonment only took effect at the next I/O step and processing has none. The cause of the delay in Run 7 is not established: see the offline diagnosis, which is not in this repository.

## What changed
- **Checkpoints:** filing tasks check for abandonment between processing stages, including inside filing parsing. A cancelled task stops at the next checkpoint. Cancellation is a `BaseException`, so a broad `except Exception` in an extractor cannot absorb it.
- **Evidence:** cancellation is signalled only after the application has read its results, so a stopping task cannot be among them. Abandoned evidence is excluded and the answer's gap is stated.
- **Status:** a case keeps `answered_degraded_unadjudicated`, or gets `unanswered_evidence_abandoned` when the application reports insufficient evidence. Ledgers from before this change export as they did.
- **Stage timing:** each stage is recorded durably with names, times and thread CPU, so a stalled worker shows the last stage it finished. The export refuses a timing that falls after the next case began.
- **Host readings:** the parent records load, power, CPU limits and worker CPU every 2 s from launch to exit, in `host_readings.json`, with a summary in the packet. A failed reading never affects the run.

## Unchanged
All deadlines and limits. The next case still starts only after every task has ended. Checkpoints do nothing unless the threshold switch is on.

## The limit
Code between two checkpoints cannot be interrupted. A stage that never reaches a checkpoint still halts the run with `stage_timeout`, tested with an invented 45 s stage. This reduces halts from slow processing; it does not end them. How long the real stages take under heavy throttling has not been measured.

## Testing
Offline on invented data, with an invented stage held by `time.sleep`, not real slow parsing. This has never run live. Using it needs a new freeze, pre-registration, package and approval. Do not merge. It is separate from the evidence-gap notice change.
