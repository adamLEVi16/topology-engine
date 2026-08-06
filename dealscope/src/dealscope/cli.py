"""Command-line interface for dealscope."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyzer import analyze
from .config import Config, __version__
from .models import CompanyBrief, to_jsonable
from .render import to_html, to_markdown, to_text

EXTENSIONS = {"text": "txt", "md": "md", "json": "json", "html": "html"}


def _render(brief: CompanyBrief, fmt: str) -> str:
    if fmt == "md":
        return to_markdown(brief)
    if fmt == "json":
        return json.dumps(to_jsonable(brief), indent=2, ensure_ascii=False)
    if fmt == "html":
        return to_html(brief)
    return to_text(brief)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dealscope",
        description=(
            "Build a short, buyer-oriented brief on a business from its public website. "
            "A research accelerator, not a substitute for due diligence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  dealscope analyze acme.com\n"
            "  dealscope analyze acme.com --format md --output brief.md\n"
            "  dealscope analyze a.com b.com c.com --format json --output ./briefs/\n"
            "  dealscope analyze acme.com --llm      # polish the prose with Claude\n"
            "  dealscope serve                       # local web UI on :8765\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"dealscope {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("analyze", help="analyze one or more domains")
    run.add_argument("domains", nargs="+", help="domains or URLs, e.g. acme.com")
    run.add_argument(
        "-f", "--format", choices=sorted(EXTENSIONS), default="text",
        help="output format (default: text)",
    )
    run.add_argument(
        "-o", "--output", type=Path,
        help="write to this file, or this directory when analyzing several domains",
    )
    run.add_argument("--max-pages", type=int, default=Config.max_pages,
                     help=f"page budget per site (default: {Config.max_pages})")
    run.add_argument("--delay", type=float, default=Config.delay,
                     help=f"seconds between requests to a host (default: {Config.delay})")
    run.add_argument("--timeout", type=float, default=Config.timeout,
                     help=f"per-request timeout in seconds (default: {Config.timeout})")
    run.add_argument("--no-cache", action="store_true", help="ignore and bypass the on-disk cache")
    run.add_argument("--llm", action="store_true",
                     help="rewrite the summary with Claude (needs ANTHROPIC_API_KEY)")
    run.add_argument("--llm-model", default=Config.llm_model,
                     help=f"model for --llm (default: {Config.llm_model})")
    run.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")

    serve = subparsers.add_parser("serve", help="run the local web UI")
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    serve.add_argument("--max-pages", type=int, default=Config.max_pages)
    serve.add_argument("--delay", type=float, default=Config.delay)
    serve.add_argument("--llm", action="store_true",
                       help="use Claude for the summary prose (needs ANTHROPIC_API_KEY)")

    return parser


def _config_from(args: argparse.Namespace) -> Config:
    config = Config(
        max_pages=args.max_pages,
        delay=args.delay,
        use_llm=getattr(args, "llm", False),
    )
    if hasattr(args, "timeout"):
        config.timeout = args.timeout
    if getattr(args, "no_cache", False):
        config.use_cache = False
    if hasattr(args, "llm_model"):
        config.llm_model = args.llm_model
    return config


def _run_analyze(args: argparse.Namespace) -> int:
    config = _config_from(args)

    if config.use_llm and not config.llm_available():
        print(
            "warning: --llm was passed but ANTHROPIC_API_KEY is not set; "
            "falling back to the built-in summary writer.",
            file=sys.stderr,
        )

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"  {message}", file=sys.stderr)

    many = len(args.domains) > 1
    destination: Path | None = args.output
    if many and destination is not None:
        destination.mkdir(parents=True, exist_ok=True)

    failures = 0
    rendered: list[str] = []

    for domain in args.domains:
        if not args.quiet:
            print(f"\n{domain}", file=sys.stderr)
        try:
            brief = analyze(domain, config, progress=progress)
        except ValueError as exc:
            print(f"error: {domain}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if any(flag.key == "unreachable" for flag in brief.risk_flags):
            failures += 1

        text = _render(brief, args.format)
        if destination is None:
            rendered.append(text)
        elif many:
            path = destination / f"{brief.domain}.{EXTENSIONS[args.format]}"
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}", file=sys.stderr)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
            print(f"wrote {destination}", file=sys.stderr)

    if rendered:
        separator = "\n\n" if args.format == "json" else "\n\n\n"
        print(separator.join(rendered))

    return 1 if failures else 0


def _run_serve(args: argparse.Namespace) -> int:
    from .web import serve

    config = _config_from(args)
    serve(host=args.host, port=args.port, config=config)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return _run_analyze(args)
        if args.command == "serve":
            return _run_serve(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
