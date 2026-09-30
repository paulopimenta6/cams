"""Convenience entry point; install the project first."""

import sys

from cams_air_quality.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["download-monthly", *sys.argv[1:]]))
