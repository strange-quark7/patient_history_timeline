"""Command line entry point for the phase 0 spike.

    medtimeline build <folder> --out history.json [--extractor claude]
    medtimeline extractors
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from medtimeline.extract import ExtractionError, available_extractors, get_extractor
from medtimeline.ingest import load_folder
from medtimeline.schema import ExtractionRecord
from medtimeline.timeline import build_history


def cmd_build(args: argparse.Namespace) -> int:
    kwargs = {}
    if args.extractor == "fixture" and args.fixtures:
        kwargs["folder"] = args.fixtures
    if args.extractor == "claude" and args.model:
        kwargs["model"] = args.model
    extractor = get_extractor(args.extractor, **kwargs)

    pages = load_folder(args.folder)
    if not pages:
        print(f"No supported files in {args.folder}", file=sys.stderr)
        return 1

    records, failures = [], []
    cache_dir = Path(args.cache) if args.cache else None
    for page in pages:
        cached = cache_dir / f"{page.page_id}.json" if cache_dir else None
        if cached and cached.exists():
            records.append(ExtractionRecord.model_validate_json(cached.read_text()))
            continue
        print(f"Extracting {Path(page.source_file).name} page {page.page_number}...", file=sys.stderr)
        try:
            extraction = extractor.extract(page)
        except ExtractionError as e:
            failures.append(str(e))
            continue
        rec = ExtractionRecord(
            page_id=page.page_id,
            source_file=page.source_file,
            page_number=page.page_number,
            extractor=extractor.name,
            extraction=extraction,
        )
        records.append(rec)
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(rec.model_dump_json(indent=2))

    history = build_history(records)
    Path(args.out).write_text(history.model_dump_json(indent=2))
    print(
        f"{len(records)} pages -> {len(history.encounters)} encounters, "
        f"{len(history.pages_needing_review)} pages need review, {len(failures)} failed. Wrote {args.out}",
        file=sys.stderr,
    )
    for f in failures:
        print(f"  failed: {f}", file=sys.stderr)
    return 0 if not failures else 2


def cmd_eval(args: argparse.Namespace) -> int:
    from medtimeline.evaluate import run_eval

    kwargs = {}
    if args.extractor == "fixture" and args.fixtures:
        kwargs["folder"] = args.fixtures
    if args.extractor == "claude" and args.model:
        kwargs["model"] = args.model
    scores = run_eval(get_extractor(args.extractor, **kwargs), args.docs, args.gold)
    print(scores.report())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="medtimeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build a patient history from a folder of documents")
    b.add_argument("folder")
    b.add_argument("--out", default="history.json")
    b.add_argument("--extractor", default="claude")
    b.add_argument("--model", help="Model id for the claude extractor")
    b.add_argument("--fixtures", help="Folder of pre-made extractions for the fixture extractor")
    b.add_argument("--cache", help="Folder to cache per-page extractions in (avoids paying twice)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("eval", help="Score an extractor against gold labels")
    v.add_argument("docs")
    v.add_argument("gold")
    v.add_argument("--extractor", default="claude")
    v.add_argument("--model")
    v.add_argument("--fixtures")
    v.set_defaults(func=cmd_eval)

    e = sub.add_parser("extractors", help="List available extractors")
    e.set_defaults(func=lambda a: print("\n".join(available_extractors())) or 0)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
