"""Separately approved SEC-only monitoring pilot; never creates approval."""
from validation.pilot_approved import main as launch


def main(argv=None):
    return launch(argv, monitoring=True)


if __name__ == '__main__':
    raise SystemExit(main())
