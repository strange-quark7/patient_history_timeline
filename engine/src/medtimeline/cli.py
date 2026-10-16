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
from medtimeline.timeline import PatientHistory, build_history
from medtimeline.verify import verify_page
from medtimeline.views import Lens, SortBy, build_view


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
        issues, grounding = verify_page(extraction, page.text_layer)
        rec = ExtractionRecord(
            page_id=page.page_id,
            source_file=page.source_file,
            page_number=page.page_number,
            extractor=extractor.name,
            extraction=extraction,
            issues=[i.model_dump() for i in issues],
            grounding=grounding,
        )
        records.append(rec)
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(rec.model_dump_json(indent=2))

    history = build_history(records)
    Path(args.out).write_text(history.model_dump_json(indent=2))
    print(
        f"{len(records)} pages -> {len(history.encounters)} encounters, "
        f"{len(history.pages_needing_review)} pages need review, {len(history.review_items)} items held back "
        f"as unverified, {len(failures)} failed. Wrote {args.out}",
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


def cmd_view(args: argparse.Namespace) -> int:
    history = PatientHistory.model_validate_json(Path(args.history).read_text())
    view = build_view(history, args.lens, args.sort, args.query, args.start, args.end)
    if args.json:
        print(view.model_dump_json(indent=2))
        return 0
    print(f"{'':<2}{'item':<34}{'first':<12}{'last':<12}{'visits':>7}{'episodes':>9}  related")
    for r in view.rows:
        print(f"{r.kind[0].upper():<2}{r.label[:33]:<34}{r.first_seen or '-':<12}{r.last_seen or '-':<12}"
              f"{r.visit_count:>7}{r.episode_count:>9}  {', '.join(r.related)}")
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

    w = sub.add_parser("view", help="Show a history through one lens, sorted")
    w.add_argument("history", help="JSON written by `build`")
    w.add_argument("--lens", default="visits", choices=[x.value for x in Lens])
    w.add_argument("--sort", default="chronological", choices=[x.value for x in SortBy])
    w.add_argument("--query", help="Only rows whose name (or related items) contain this text")
    w.add_argument("--from", dest="start", help="YYYY-MM-DD")
    w.add_argument("--to", dest="end", help="YYYY-MM-DD")
    w.add_argument("--json", action="store_true", help="Print the full view as JSON")
    w.set_defaults(func=cmd_view)

    e = sub.add_parser("extractors", help="List available extractors")
    e.set_defaults(func=lambda a: print("\n".join(available_extractors())) or 0)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
