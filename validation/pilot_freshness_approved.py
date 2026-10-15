"""Separate single-use approval entrypoint; never creates authority."""
from validation.pilot_approved import main as launch


def main(argv=None):
    return launch(argv, monitoring=True, freshness=True)


if __name__ == '__main__':
    raise SystemExit(main())
