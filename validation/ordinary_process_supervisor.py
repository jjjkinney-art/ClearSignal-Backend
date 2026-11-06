"""Parent-owned deadlines for the disabled rehearsal child; no live authority.

A child must announce each fixed case and wait for acknowledgment. The parent
arms its own monotonic deadline before acknowledging. Completion includes drain,
retention and lifecycle finish. A timeout kills/reaps the whole worker, including
its threads; no artifact from that child is accepted as a completed result.
"""
import os
import selectors
import subprocess
import time

from validation.ordinary_pilot_contract import CASES


def supervise(command, *, output, environment):
    status_read, status_write = os.pipe()
    ack_read, ack_write = os.pipe()
    child = None
    selector = selectors.DefaultSelector()
    active = None
    case_started = None
    aborted = False
    position = 0
    deadline = None
    reason = None
    started = time.monotonic()
    buffer = b''
    try:
        child = subprocess.Popen([*command, str(ack_read), str(status_write)], cwd=output,
                                 env=environment, pass_fds=(ack_read, status_write),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        os.close(ack_read); ack_read = None
        os.close(status_write); status_write = None
        selector.register(status_read, selectors.EVENT_READ)
        eof = False
        while True:
            now = time.monotonic()
            if now >= started + 480:
                reason = 'whole_deadline'
                break
            if deadline is not None and now >= deadline:
                reason = 'case_deadline'
                break
            # Short bounded reads let the parent enforce time even if the child
            # is stuck in a C extension, SQLite, or an undrained executor task.
            events = selector.select(min(0.05, max(0, min(started + 480, deadline or started + 480) - now)))
            now = time.monotonic()
            if now >= started + 480 or (deadline is not None and now >= deadline):
                reason = 'whole_deadline' if now >= started + 480 else 'case_deadline'
                break
            if events:
                chunk = os.read(status_read, 4096)
                if not chunk:
                    eof = True
                    selector.unregister(status_read)
                else:
                    buffer += chunk
                    if len(buffer) > 4096:
                        reason = 'case_protocol'
                        break
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if active is None and position < len(CASES) and line == ('begin ' + CASES[position]).encode():
                            active = CASES[position]
                            case_started = time.monotonic()
                            deadline = min(started + 480, case_started + (30 if active.endswith(':core_thesis') else 20))
                            os.write(ack_write, b'1')
                        elif active is not None and line == ('end ' + active).encode():
                            if aborted:
                                reason = 'case_protocol'
                                break
                            active = deadline = None
                            case_started = None
                            position += 1
                        elif active is not None and not aborted and line == ('abort ' + active).encode():
                            # Keep the case deadline armed through cleanup/exit.
                            aborted = True
                        else:
                            reason = 'case_protocol'
                            break
            if reason:
                break
            if child.poll() is not None and eof:
                if (active is not None and not aborted) or buffer:
                    reason = 'case_protocol'
                break
        if reason and child.poll() is None:
            child.kill()
        returncode = child.wait(timeout=5)
        return {'returncode': returncode, 'stop_reason': reason,
                'interrupted_case': active, 'finished_case_scopes': position,
                'case_elapsed_seconds': time.monotonic() - case_started if case_started is not None else None,
                'elapsed_seconds': time.monotonic() - started}
    finally:
        # Also terminate on parent-side I/O/protocol exceptions, not just expiry.
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        selector.close()
        for fd in (status_read, status_write, ack_read, ack_write):
            if fd is not None:
                os.close(fd)
