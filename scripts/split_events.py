"""Split a Movebank event CSV into parts small enough to commit to GitHub.

GitHub rejects files over 100 MB and warns above 50 MB. Each part keeps
the original header and rows byte for byte, in their original order; a
tag and animal's rows are never split across parts. Parts are filled in
reference-data order until adding the next animal would exceed the limit.

Usage:
    python scripts/split_events.py EVENTS REFERENCE OUTPUT_PREFIX [--max-mb 50]

writes OUTPUT_PREFIX-1.csv, OUTPUT_PREFIX-2.csv, and so on.
"""

import argparse
import csv
from collections import Counter
from pathlib import Path


def row_key(line: str, header: list, columns: list) -> tuple:
    """The (tag, animal) key of one physical CSV line.

    Args:
        line (str): A single line from the CSV file.
        header (list): The header row of the CSV file as a list of strings.
        columns (list): The indices of the tag and animal columns in the header.

    Returns:
        tuple: A tuple containing the tag and animal identifiers for the given line.
    """
    fields = next(csv.reader([line]))
    if len(fields) != len(header):
        raise ValueError(f"line does not hold one whole record: {line[:80]!r}")
    return tuple(fields[index] for index in columns)


def plan_parts(sizes: Counter, order: list, max_bytes: int) -> dict:
    """Assign each key to a part number, filling parts in ``order``.

    Args:
        sizes (Counter): A Counter mapping each (tag, animal) key to its byte size.
        order (list): A list of (tag, animal) keys in the desired order for filling parts.
        max_bytes (int): The maximum byte size for each part.

    Returns:
        dict: A dictionary mapping each (tag, animal) key to its assigned part number.
    """
    parts, part, used = {}, 1, 0
    for key in order:
        if sizes[key] > max_bytes:
            raise ValueError(f"{key} alone is {sizes[key]} bytes, over the limit")
        if used and used + sizes[key] > max_bytes:
            part, used = part + 1, 0
        parts[key] = part
        used += sizes[key]
    return parts


def main():
    """Split the event file and check nothing was lost."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("events", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("prefix", type=Path)
    parser.add_argument("--max-mb", type=float, default=50)
    args = parser.parse_args()

    with open(args.reference, newline="", encoding="utf-8") as handle:
        order = list(
            dict.fromkeys(
                (row["tag-id"].strip(), row["animal-id"].strip())
                for row in csv.DictReader(handle)
            )
        )

    with open(args.events, newline="", encoding="utf-8") as handle:
        header_line = handle.readline()
        header = next(csv.reader([header_line]))
        columns = [
            header.index("tag-local-identifier"),
            header.index("individual-local-identifier"),
        ]
        sizes = Counter()
        for line in handle:
            sizes[row_key(line, header, columns)] += len(line.encode("utf-8"))

    unknown = set(sizes) - set(order)
    if unknown:
        raise ValueError(f"event rows for animals not in the reference data: {unknown}")
    max_bytes = int(args.max_mb * 1e6) - len(header_line.encode("utf-8"))
    parts = plan_parts(sizes, [key for key in order if key in sizes], max_bytes)

    paths = {
        part: args.prefix.with_name(f"{args.prefix.name}-{part}.csv")
        for part in set(parts.values())
    }
    outputs = {
        part: open(path, "w", newline="", encoding="utf-8")
        for part, path in paths.items()
    }
    written = Counter()
    try:
        for output in outputs.values():
            output.write(header_line)
        with open(args.events, newline="", encoding="utf-8") as handle:
            handle.readline()
            for line in handle:
                part = parts[row_key(line, header, columns)]
                outputs[part].write(line)
                written[part] += len(line.encode("utf-8"))
    finally:
        for output in outputs.values():
            output.close()

    if sum(written.values()) != sum(sizes.values()):
        raise RuntimeError("bytes written do not match the input")
    for part, path in sorted(paths.items()):
        animals = sum(value == part for value in parts.values())
        print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB, {animals} animals")


if __name__ == "__main__":
    main()
