"""Private map-rendering entry point; never called with untrusted pickle data."""

import json
import sys
from pathlib import Path

import numpy as np

from .maps import render_arrays


def main():
    field, options, output = sys.argv[1:]
    with np.load(field, allow_pickle=False) as arrays:
        render_arrays(
            arrays["values"],
            arrays["latitude_edges"],
            arrays["longitude_edges"],
            output,
            **json.loads(Path(options).read_text()),
        )


if __name__ == "__main__":
    main()
