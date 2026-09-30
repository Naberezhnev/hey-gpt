"""Copy locally supplied runtime/dependency license texts into the release."""
from importlib.metadata import distributions
from pathlib import Path
import sys

def main():
    parts = ["Hey GPT Windows distribution: original dependency license texts\n"]
    for distribution in sorted(distributions(), key=lambda d: d.metadata.get("Name", "")):
        name = distribution.metadata.get("Name", "")
        for item in distribution.files or []:
            path = str(item).lower()
            if any(token in Path(path).name for token in ("license", "copying", "notice", "copyright")):
                source = Path(distribution.locate_file(item))
                if source.is_file() and source.stat().st_size < 200000:
                    parts.append(f"\n{'=' * 70}\n{name} {distribution.version} — {item}\n\n" + source.read_text(encoding="utf-8", errors="replace"))
    for relative in ("LICENSE.txt", "tcl/tcl8.6/license.terms", "tcl/tk8.6/license.terms"):
        source = Path(sys.base_prefix) / relative
        if source.is_file():
            parts.append(f"\n{'=' * 70}\nPython runtime — {relative}\n\n" + source.read_text(encoding="utf-8", errors="replace"))
    target = Path(__file__).resolve().parent.parent / "docs" / "DEPENDENCY_LICENSES.txt"
    target.write_text("\n".join(parts), encoding="utf-8")
    print("Collected", len(parts) - 1, "license files")

if __name__ == "__main__":
    main()
