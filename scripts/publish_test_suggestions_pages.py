#!/usr/bin/env python3
"""CLI entry for GitHub Pages generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from flex_testing_agent.site.publish import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUGGESTIONS_DIR,
    publish_test_suggestion_pages,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suggestions-dir",
        type=Path,
        default=DEFAULT_SUGGESTIONS_DIR,
        help="Directory of suggestion YAML files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write HTML pages",
    )
    args = parser.parse_args()
    written = publish_test_suggestion_pages(
        suggestions_dir=args.suggestions_dir,
        output_dir=args.output_dir,
    )
    for path in written:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
