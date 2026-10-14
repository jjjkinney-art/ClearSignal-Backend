"""Separate source-monitoring validation; synthetic I/O only, no live authority."""
from validation.pilot_rehearsal import main as launch


def main(argv=None):
    return launch(argv, mode="source_monitoring")


if __name__ == "__main__":
    raise SystemExit(main())
