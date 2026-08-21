"""Read-only compact page-text inspector for metadata evidence review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("--chars", type=int, default=1800)
    args = parser.parse_args()
    records = []
    for path in sorted(args.pdf_dir.glob("*.pdf"), key=lambda item: item.name):
        reader = PdfReader(str(path))
        pages = {1, len(reader.pages)}
        if "华泰期货-国债周报" in path.name:
            pages.add(12)
        if "光期宏观" in path.name:
            pages.add(29)
        records.append({
            "filename": path.name,
            "pages": [
                {"page": page, "text": (reader.pages[page - 1].extract_text() or "")[: args.chars]}
                for page in sorted(pages)
            ],
        })
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
