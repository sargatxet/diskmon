"""CLI de diskmon."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict
from typing import Optional

from . import __version__
from .collect import scan
from .config import Config, load_config
from .doctor import (
    exit_code as doctor_exit_code,
    json_output as doctor_json,
    render as doctor_render,
    run_checks as doctor_run_checks,
)
from .history import History
from .models import DiskInfo
from .report import color_enabled, render_history, render_json, render_text
from .web import serve

SUBCOMMANDS = {"scan", "watch", "history", "serve", "selftest", "config", "doctor", "version"}


def _normalize_device(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip()
    if not value.startswith("/dev/"):
        value = f"/dev/{value}"
    return value


def _device_name(value: Optional[str]) -> Optional[str]:
    path = _normalize_device(value)
    return os.path.basename(path) if path else None


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", metavar="FICHERO", help="Ruta al config.toml")
    parser.add_argument("--no-color", action="store_true", help="Desactiva el color")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")


def _add_scan_options(parser: argparse.ArgumentParser) -> None:
    _add_common(parser)
    parser.add_argument("--device", metavar="DISC", help="Analiza solo un disco (sda o /dev/sda)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--save", dest="save", action="store_true", help="Guarda en el histórico")
    group.add_argument("--no-save", dest="save", action="store_false", help="No guarda en el histórico")
    parser.set_defaults(save=None)
    parser.add_argument(
        "--fail-on",
        choices=("none", "warning", "critical"),
        help="Nivel que provoca código de salida distinto de 0 (por defecto: config)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Muestra también avisos informativos")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskmon",
        description="Monitor de salud de discos basado en SMART (ATA/SATA/NVMe).",
    )
    parser.add_argument("--version", action="version", version=f"diskmon {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMANDO")

    p_scan = sub.add_parser("scan", help="Analiza los discos una vez")
    _add_scan_options(p_scan)

    p_watch = sub.add_parser("watch", help="Monitoriza periódicamente")
    _add_scan_options(p_watch)
    p_watch.add_argument("--interval", type=int, default=300, help="Segundos entre pasadas (300)")
    p_watch.add_argument("--count", type=int, default=0, help="Número de pasadas; 0 = infinito")
    p_watch.add_argument("--clear", action="store_true", help="Limpia la pantalla entre pasadas")

    p_hist = sub.add_parser("history", help="Consulta el histórico guardado")
    _add_common(p_hist)
    p_hist.add_argument("--device", metavar="DISC", help="Filtra por disco (sda o /dev/sda)")
    p_hist.add_argument("--serial", help="Filtra por número de serie")
    p_hist.add_argument("--limit", type=int, help="Máximo de registros (config: 100)")

    p_serve = sub.add_parser("serve", help="Arranca el dashboard web local")
    _add_common(p_serve)
    p_serve.add_argument("--host", help="Interfaz de escucha (config: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, help="Puerto (config: 8765)")

    p_test = sub.add_parser("selftest", help="Lanza un auto-test SMART")
    _add_common(p_test)
    p_test.add_argument("--device", required=True, metavar="DISC", help="Disco (sda o /dev/sda)")
    p_test.add_argument(
        "--kind", choices=("short", "long", "conveyance", "offline"), default="short"
    )

    p_cfg = sub.add_parser("config", help="Muestra la configuración efectiva")
    _add_common(p_cfg)

    p_doc = sub.add_parser("doctor", help="Comprueba el entorno y los requisitos")
    _add_common(p_doc)

    sub.add_parser("version", help="Muestra la versión")
    return parser


def _make_config(args: argparse.Namespace) -> Config:
    return load_config(getattr(args, "config", None))


def _print_result(result, args, config: Config) -> None:
    thresholds = config.thresholds
    if getattr(args, "json", False):
        if getattr(args, "command", None) == "watch":
            # Una línea JSON por pasada (NDJSON) para poder procesarla en streaming.
            print(json.dumps(result.to_dict(), ensure_ascii=False))
        else:
            print(render_json(result))
    else:
        use_color = color_enabled(getattr(args, "no_color", False))
        print(
            render_text(
                result,
                thresholds=thresholds,
                color=use_color,
                verbose=getattr(args, "verbose", False),
            )
        )


def _save(result, config: Config, args: argparse.Namespace) -> None:
    should_save = config.save_history if getattr(args, "save", None) is None else args.save
    if not should_save:
        return
    try:
        History(config.db_file).save_scan(result)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Aviso: no se pudo guardar el histórico: {exc}", file=sys.stderr)


def _exit_code(result, fail_on: str) -> int:
    if not result.reports and result.errors:
        return 2
    levels = {r.alert_level for r in result.reports}
    if fail_on == "none":
        return 0
    if "critical" in levels:
        return 2
    if fail_on == "warning" and ("warning" in levels or "unknown" in levels):
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    config = _make_config(args)
    result = scan(config, only=_device_name(args.device))
    _save(result, config, args)
    _print_result(result, args, config)
    fail_on = args.fail_on or config.fail_on
    return _exit_code(result, fail_on)


def cmd_watch(args: argparse.Namespace) -> int:
    config = _make_config(args)
    interval = max(5, args.interval)
    count = 0
    last_code = 0
    try:
        while True:
            count += 1
            if args.clear and not args.json and sys.stdout.isatty():
                print("\x1b[2J\x1b[H", end="")
            result = scan(config, only=_device_name(args.device))
            _save(result, config, args)
            _print_result(result, args, config)
            last_code = _exit_code(result, args.fail_on or config.fail_on)
            if args.count and count >= args.count:
                break
            if not args.json:
                print(f"\nPróxima pasada en {interval} s (Ctrl-C para salir)…\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitorización detenida.")
    return last_code


def cmd_history(args: argparse.Namespace) -> int:
    config = _make_config(args)
    history = History(config.db_file)
    rows = history.query(
        device=_device_name(args.device),
        serial=args.serial,
        limit=args.limit or config.history_limit,
    )
    if args.json:
        print(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(render_history(rows, color=color_enabled(args.no_color)))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = _make_config(args)
    serve(config, host=args.host, port=args.port)
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from .collect.smart import run_self_test

    config = _make_config(args)
    path = _normalize_device(args.device) or ""
    if not os.path.exists(path):
        print(f"Error: no existe el dispositivo {path}", file=sys.stderr)
        return 2
    name = os.path.basename(path)
    disk = DiskInfo(name=name, path=path)
    try:
        output = run_self_test(disk, kind=args.kind, config=config)
    except Exception as exc:  # SmartError y similares
        print(f"Error al lanzar el auto-test: {exc}", file=sys.stderr)
        return 2
    print(output)
    print(
        f"\nAuto-test '{args.kind}' lanzado en {path}."
        f"\nConsulta el progreso con: sudo smartctl -l selftest {path}"
        f"\nO vuelve a ejecutar 'diskmon scan --device {name}' cuando termine."
    )
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config = _make_config(args)
    data = asdict(config)
    data["db_file"] = str(config.db_file)
    data["config_file"] = os.path.expanduser(
        args.config or os.environ.get("DISKMON_CONFIG") or "~/.config/diskmon/config.toml"
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = _make_config(args)
    checks = doctor_run_checks(config)
    if args.json:
        print(doctor_json(checks))
    else:
        print(doctor_render(checks, color=color_enabled(args.no_color)))
    return doctor_exit_code(checks)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "scan")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    handlers = {
        "scan": cmd_scan,
        "watch": cmd_watch,
        "history": cmd_history,
        "serve": cmd_serve,
        "selftest": cmd_selftest,
        "config": cmd_config,
        "doctor": cmd_doctor,
        "version": lambda _args: print(f"diskmon {__version__}") or 0,
    }
    try:
        return int(handlers[args.command](args) or 0)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
