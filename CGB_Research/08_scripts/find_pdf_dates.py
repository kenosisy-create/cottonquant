"""Read-only helper to locate date-like text by physical PDF page."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from pypdf import PdfReader


PATTERNS = (
    re.compile(r"20\d{2}[年./-]\s*\d{1,2}[月./-]\s*\d{1,2}日?"),
    re.compile(r"(?:截至|截止|数据截至|数据截止)[^\n。；]{0,45}"),
    re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}(?!\d)"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_dir", type=Path)
    args = parser.parse_args()
    records: list[dict[str, object]] = []
    for path in sorted(args.pdf_dir.glob("*.pdf"), key=lambda item: item.name):
        reader = PdfReader(str(path))
        pages: list[dict[str, object]] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            matches: list[str] = []
            for pattern in PATTERNS:
                matches.extend(match.group(0).strip() for match in pattern.finditer(text))
            unique = list(dict.fromkeys(matches))
            if unique:
                pages.append({"page": number, "matches": unique[:80]})
        records.append({"filename": path.name, "pages": pages})
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
