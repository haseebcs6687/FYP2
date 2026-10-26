"""Write all 44 concept notes into rag/corpus/notes/ and report coverage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.concepts import CONCEPTS  # noqa: E402
import write_notes_1, write_notes_2  # noqa: E402


def main():
    write_notes_1.write()
    write_notes_2.write()

    notes_dir = Path(__file__).resolve().parent.parent / "rag" / "corpus" / "notes"
    written = {p.stem for p in notes_dir.glob("*.md")}
    missing = sorted(set(CONCEPTS) - written)

    print("\n{} notes on disk, {} canonical concepts".format(len(written), len(CONCEPTS)))
    if missing:
        print("MISSING: " + ", ".join(missing))
    else:
        print("Every concept has a note.")


if __name__ == "__main__":
    main()
