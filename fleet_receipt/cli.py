import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .cache import PositionCache
from .config import load_fleet, load_settings
from .formatting import format_receipt
from .printers.epson_usb import (
    PrinterError,
    print_receipt as print_usb_receipt,
    print_test as print_usb_test,
)
from .printers.file import FilePrinter
from .printers.text import TextPrinter
from .providers.aisstream import AISStreamError, AISStreamProvider
from .providers.fixtures import FixturePositionProvider
from .reporting import render_cached_report
from .unlocode import (
    UNLocodeSyncError,
    database_status,
    sync_unlocode,
    unlocode_available,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet-receipt", description="Fleet position receipts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview", help="Print the exact receipt text to the terminal")
    _add_receipt_arguments(preview)
    preview.add_argument(
        "--output",
        type=Path,
        help="Write the exact receipt to a UTF-8 text file instead of the terminal",
    )
    print_command = subparsers.add_parser(
        "print", help="Print the receipt on the Epson TM-L90 USB printer"
    )
    _add_receipt_arguments(print_command)
    subparsers.add_parser(
        "printer-test",
        help="Print a standalone Epson TM-L90 feed-and-cut diagnostic",
    )
    listener = subparsers.add_parser(
        "listen", help="Continuously update the live AIS position cache"
    )
    listener.add_argument(
        "--cache",
        type=Path,
        help="Override the OS application-data SQLite cache path",
    )
    unlocode = subparsers.add_parser(
        "unlocode", help="Manage the complete offline UNECE UN/LOCODE index"
    )
    unlocode_commands = unlocode.add_subparsers(dest="unlocode_command", required=True)
    unlocode_commands.add_parser("sync", help="Download and index the official release")
    unlocode_commands.add_parser("status", help="Show local index status")
    web = subparsers.add_parser("web", help="Serve the cached fleet report over HTTP")
    web.add_argument("--host", default="0.0.0.0", help="Listen address (default: 0.0.0.0)")
    web.add_argument("--port", type=int, default=8000, help="Listen port (default: 8000)")
    return parser


def _add_receipt_arguments(command: argparse.ArgumentParser) -> None:
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixtures", action="store_true", help="Use offline fixture AIS data")
    source.add_argument("--live", action="store_true", help="Collect live AISstream.io positions")
    source.add_argument("--cached", action="store_true", help="Use the on-disk live position cache")
    command.add_argument(
        "--wait",
        type=float,
        default=60,
        help="Seconds to collect live positions before printing (default: 60)",
    )
    command.add_argument("--at", help="Report instant as ISO 8601, for deterministic output")
    command.add_argument("--width", type=int, help="Override configured receipt width")
    command.add_argument(
        "--fleet",
        default="main",
        help=(
            "Fleet profile to display: main, celebrity, royal-caribbean, "
            "carnival, princess, cunard, p-and-o, costa, aida, "
            "msc, ncl, dcl, vv, oceania, regent, "
            "or all (default: main)"
        ),
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "web":
            import uvicorn

            from .web import create_app

            uvicorn.run(create_app(), host=args.host, port=args.port)
            return 0
        if args.command == "unlocode":
            if args.unlocode_command == "sync":
                count = sync_unlocode()
                print(f"UN/LOCODE {count} locations indexed")
                return 0
            status = database_status()
            print(f"Path: {status['path']}")
            print(f"Available: {'yes' if status['available'] else 'no'}")
            if status["available"]:
                print(f"Release: {status['release']}")
                print(f"Locations: {status['location_count']}")
            return 0
        if args.command == "listen":
            fleet = load_fleet(profile="all")
            cache = PositionCache(args.cache) if args.cache else PositionCache()
            if not unlocode_available():
                try:
                    count = sync_unlocode()
                    print(f"UN/LOCODE index ready: {count} locations")
                except UNLocodeSyncError as exc:
                    print(
                        f"UN/LOCODE sync unavailable; using built-in aliases: {exc}",
                        file=sys.stderr,
                    )
            print(f"Listening for {len(fleet.vessels)} vessels; cache: {cache.path}")
            AISStreamProvider().listen_forever(
                fleet.vessels,
                cache.update,
                cache.update_health,
                initial_positions=cache.load(),
            )
            return 0
        if args.command == "printer-test":
            warning = print_usb_test()
            if warning:
                print(f"fleet-receipt: {warning}", file=sys.stderr)
            return 0
        if args.command in {"preview", "print"}:
            receipt = _generate_receipt(args)
            if args.command == "print":
                warning = print_usb_receipt(receipt)
                if warning:
                    print(f"fleet-receipt: {warning}", file=sys.stderr)
                return 0
            printer = FilePrinter(args.output) if args.output else TextPrinter()
            printer.print_receipt(receipt)
            if args.output:
                print(f"Receipt written to {args.output}")
            return 0
    except KeyboardInterrupt:
        print("Listener stopped.", file=sys.stderr)
        return 130
    except (PrinterError, AISStreamError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"fleet-receipt: {exc}", file=sys.stderr)
        return 2
    return 1


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--at must include a timezone, such as Z or -07:00")
    return parsed


def _generate_receipt(args: argparse.Namespace) -> str:
    """Build the canonical receipt used unchanged by preview and physical printing."""
    generated_at = _datetime(args.at) if args.at else datetime.now(timezone.utc)
    if args.cached:
        return render_cached_report(
            PositionCache(),
            generated_at=generated_at,
            width=args.width,
            fleet_profile=args.fleet,
        )

    fleet = load_fleet(profile=args.fleet)
    settings = load_settings()
    provider = (
        AISStreamProvider(timeout_seconds=args.wait)
        if args.live
        else FixturePositionProvider()
    )
    positions = provider.fetch_positions(fleet.vessels)
    return format_receipt(
        fleet,
        positions,
        generated_at,
        width=args.width or int(settings["receipt_width"]),
        stale_after_hours=float(settings["stale_after_hours"]),
        feed_health={
            "source": "Terrestrial" if args.live else "Fixture",
            "status": "connected",
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
