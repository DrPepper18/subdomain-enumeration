"""CLI: разбор аргументов и запуск use case. Единственный слой, знающий про argparse."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from services import (
    EnumerateSubdomainsUseCase,
    JsonResultWriter,
    SocketDnsResolver,
    TextResultWriter,
    build_sources,
    save_to_file,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subdomain-enum",
        description="Searching subdomains and their IP.",
    )
    parser.add_argument("domain", help="Target domain, like example.com")
    parser.add_argument("--json", action="store_true", help="Output in JSON-format")
    parser.add_argument("-o", "--output", metavar="FILE", help="Сохранить результат в файл")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=sorted(AVAILABLE_SOURCES),
        help="Limit sources to the given names (default: all sources)",
    )
    parser.add_argument(
        "--dns-timeout",
        type=float,
        default=5.0,
        metavar="SEC",
        help="DNS resolution timeout for each hostname, seconds (default: 5)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=20,
        metavar="N",
        help="Number of parallel threads for resolution (default: 20)",
    )
    return parser


# Re-export for tests that patch it
AVAILABLE_SOURCES = {
    "crtsh": "CrtShSource",
    "hackertarget": "HackerTargetSource",
    "anubisdb": "AnubisDbSource",
}


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        sources = build_sources(args.sources)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    use_case = EnumerateSubdomainsUseCase(
        sources=sources,
        resolver=SocketDnsResolver(timeout=args.dns_timeout),
        max_workers=args.workers,
    )

    print(f"[*] Searching subdomains for {args.domain}. It will take some time...", file=sys.stderr)
    subdomains = use_case.execute(args.domain)

    writer = JsonResultWriter() if args.json else TextResultWriter()
    rendered = writer.render(subdomains)

    if args.output:
        saved_path = save_to_file(rendered, args.output)
        print(f"[+] Saved results at {saved_path}", file=sys.stderr)
    else:
        print(rendered)

    return 0
