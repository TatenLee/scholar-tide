"""Command-line entry point.

    python -m engine build            # fetch + render (no AI)
    python -m engine build --use-embed  # + personalised re-ranking
    python -m engine serve            # local preview of the frontend
    python -m engine spiders          # list registered spiders
"""
from __future__ import annotations

import argparse
from pathlib import Path

from engine.core.config import load_config

DEFAULT_SOURCES = Path("config/source.yaml")
DEFAULT_PREFS = Path("config/preference.yaml")


def build_cmd(args: argparse.Namespace) -> None:
    from engine.build import build

    config = load_config(
        Path(args.sources),
        Path(args.preferences),
        use_embed=args.use_embed,
        expired_after=args.expired_after,
    )
    build(config)


def serve_cmd(args: argparse.Namespace) -> None:
    import functools
    import http.server

    root = Path(args.dir).resolve()
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(root)
    )
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving {root} at http://127.0.0.1:{args.port}")
    httpd.serve_forever()


def spiders_cmd(_args: argparse.Namespace) -> None:
    import engine.spider  # noqa: F401  (side-effect: registers)
    from engine.core.registry import list_spiders

    for name in list_spiders():
        print(name)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scholar-tide", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="fetch and render the daily newspaper")
    p.add_argument("--sources", default=str(DEFAULT_SOURCES))
    p.add_argument("--preferences", default=str(DEFAULT_PREFS))
    p.add_argument("--use-embed", action="store_true",
                   help="enable personalised re-ranking via embeddings")
    p.add_argument("--expired-after", default=None,
                   help='filter cutoff "YYYY/MM/DD HH:MM" (UTC)')
    p.set_defaults(func=build_cmd)

    p = sub.add_parser("serve", help="preview the frontend locally")
    p.add_argument("--dir", default="frontend")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=serve_cmd)

    p = sub.add_parser("spiders", help="list registered spiders")
    p.set_defaults(func=spiders_cmd)

    return parser


def main(argv: list[str] | None = None) -> None:
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    args = make_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()