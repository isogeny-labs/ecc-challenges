"""The `ecc` command: account, keys, runs and leaderboard from a terminal.

The CLI speaks the same HTTPS API as the worker. It authenticates with an
existing API key, so no browser session or separate token is needed. Commands
cover the signed-in dashboard: who you are, your keys, your runs, run
verification detail, closing a protocol 2 run and the leaderboard listing.

No command prints a stored key. ``ecc keys create`` prints the new secret once,
as the website does.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import stat
import sys
import urllib.error
import urllib.request

DEFAULT_API = "https://ecc-challenges.com"
DEFAULT_KEY_FILE = "~/.config/ecc-challenges/api-key"
VERSION = "0.1.0"
DASH = "—"


class CliError(Exception):
    """A user-facing failure; main prints it without a traceback."""


def key_path(args) -> Path:
    return Path(args.key_file).expanduser()


def load_key(args) -> str:
    path = key_path(args)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise CliError(f"no API key at {path}; run 'ecc login' or create one at "
                       f"{args.api_url}/dashboard") from None
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc.strerror or exc}") from None
    if not value:
        raise CliError(f"{path} is empty; run 'ecc login' or create a key on the dashboard")
    if not value.startswith("ecc1_"):
        raise CliError(f"{path} does not look like an API key (they start with ecc1_)")
    return value


def save_key(args, value: str) -> Path:
    path = key_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        os.write(descriptor, (value + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    return path


def _error_message(status: int, body: bytes, headers) -> str:
    message = ""
    try:
        value = json.loads(body or b"{}")
    except ValueError:
        value = {}
    if isinstance(value, dict):
        message = str(value.get("error") or value.get("detail") or "")
    message = message or f"HTTP {status}"
    if status == 401:
        return f"{message}; run 'ecc login' with a current key"
    if status == 429:
        retry = headers.get("Retry-After") if headers else None
        return f"{message}" + (f"; retry in {retry}s" if retry else "")
    return message


def request(args, method: str, path: str, payload=None, *, key: str | None = None):
    url = args.api_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json", "User-Agent": f"ecc-cli/{VERSION}"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request_object = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request_object, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise CliError(_error_message(exc.code, exc.read(), exc.headers)) from None
    except urllib.error.URLError as exc:
        raise CliError(f"cannot reach {args.api_url}: {exc.reason}") from None
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        raise CliError("the server returned a response that is not JSON") from None


def account_request(args, method: str, path: str, payload=None):
    return request(args, method, path, payload, key=load_key(args))


def emit(args, value, *, text: str | None = None) -> None:
    if args.json:
        print(json.dumps(value, indent=2, sort_keys=True))
    elif text is not None:
        print(text)


def points(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return DASH


def operations(value) -> str:
    try:
        return f"2^{float(value):.1f}"
    except (TypeError, ValueError):
        return DASH


def stamp(value) -> str:
    if not value:
        return DASH
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [len(head) for head in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    def line(cells):
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells)).rstrip()
    return "\n".join([line(headers), line(["-" * width for width in widths])] +
                     [line(row) for row in rows])


def run_state(run: dict) -> str:
    state = run.get("state") or run.get("health_state") or "unknown"
    return str(state).capitalize()


def command_login(args) -> int:
    if sys.stdin.isatty() and sys.stderr.isatty():
        value = getpass.getpass(f"API key from {args.api_url}/dashboard (input hidden): ")
    else:
        value = sys.stdin.read()
    value = "".join(value.split())
    if not value.startswith("ecc1_"):
        raise CliError("that does not look like an API key (they start with ecc1_)")
    path = save_key(args, value)
    try:
        account = request(args, "GET", "/v1/account", key=value)["account"]
    except CliError as exc:
        print(f"Saved the key to {path}, but the server rejected it: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"key_file": str(path), "account": account}, indent=2, sort_keys=True))
    else:
        print(f"Saved the key to {path}")
        print(f"Signed in as {account['login']}.")
    return 0


def command_whoami(args) -> int:
    data = account_request(args, "GET", "/v1/account")
    account, runs = data["account"], data.get("runs") or {}
    keys = data.get("keys") or []
    active_keys = sum(1 for key in keys if not key.get("revoked_at"))
    listed = ("listed" if account.get("leaderboard_visible")
              else "not listed" if account.get("leaderboard_visible") is not None
              else "unavailable")
    text = "\n".join([
        f"login: {account['login']}",
        f"leaderboard: {listed}",
        f"keys: {len(keys)} ({active_keys} not revoked)",
        f"runs: {runs.get('active_runs', 0)} active, {runs.get('total_runs', 0)} total; "
        f"{points(runs.get('points', 0))} points",
    ])
    emit(args, data, text=text)
    return 0


def command_keys(args) -> int:
    data = account_request(args, "GET", "/v1/account/keys")
    keys = data.get("keys") or []
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    if not keys:
        print("No keys yet. Create one with 'ecc keys create --label NAME'.")
        return 0
    rows = []
    for key in keys:
        state = ("revoked" if key.get("revoked_at") else
                 "active" if key.get("worker_active") else "idle")
        rows.append([str(key.get("id", "")), str(key.get("label", "")), state,
                     stamp(key.get("created_at")), stamp(key.get("last_used_at")),
                     points(key.get("points_received", 0))])
    print(table(rows, ["ID", "Label", "State", "Created", "Last used", "Points"]))
    return 0


def command_keys_create(args) -> int:
    data = account_request(args, "POST", "/v1/account/keys", {"label": args.label})
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print(data["key"])
    print("This secret is shown once. Save it as your ECC_API_KEY_FILE.", file=sys.stderr)
    return 0


def command_keys_revoke(args) -> int:
    data = account_request(args, "POST", f"/v1/account/keys/{args.key_id}/revoke")
    emit(args, data, text=f"Revoked key {data.get('revoked', args.key_id)}. Its runs are suspended.")
    return 0


def command_runs(args) -> int:
    query = []
    if args.protocol:
        query.append(f"protocol={args.protocol}")
    if args.run_id:
        query.append(f"run_id={args.run_id}")
    path = "/v1/account/runs" + ("?" + "&".join(query) if query else "")
    data = account_request(args, "GET", path)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    runs = data.get("runs") or []
    if not runs:
        print("No runs match.")
        return 0
    rows = []
    for run in runs:
        rows.append([str(run.get("protocol", "")), str(run.get("id", "")),
                     str(run.get("campaign", "")), run_state(run),
                     points(run.get("points", 0)),
                     points(run.get("points_per_hour", 0)),
                     stamp(run.get("last_seen_at")), str(run.get("key_label", ""))])
    print(table(rows, ["Proto", "Run", "Challenge", "State", "Points", "Points/hour",
                       "Last seen", "Key"]))
    return 0


def command_run(args) -> int:
    data = account_request(args, "GET", f"/v1/account/runs/{args.protocol}/{args.run_id}")
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    lines = [
        f"run: {data.get('id')} ({data.get('protocol')}, {data.get('campaign')})",
        f"state: {run_state(data)}; health: {data.get('health_state', DASH)}",
        f"points: {points(data.get('points'))}; per hour: {points(data.get('points_per_hour'))}",
        f"key: {data.get('key_label', DASH)}; last seen: {stamp(data.get('last_seen_at'))}",
        f"verification: {data.get('verification_state', DASH)} "
        f"({data.get('batches', 0)} batches, {data.get('checked', 0)} checked, "
        f"{data.get('pending', 0)} pending, {data.get('failed', 0)} failed, "
        f"{data.get('indexed', 0)} indexed)",
    ]
    batches = data.get("batches_recent") or []
    if batches:
        rows = [[stamp(batch.get("created_at")), points(batch.get("records")),
                 str(batch.get("state", "")),
                 stamp(batch.get("indexed_at"))] for batch in batches]
        lines += ["", table(rows, ["Created", "Records", "State", "Indexed"])]
    print("\n".join(lines))
    return 0


def command_close(args) -> int:
    data = account_request(args, "POST", f"/v2/runs/{args.run_id}/close")
    emit(args, data, text=f"Closed run {args.run_id} at {stamp(data.get('closed_at'))}. "
                          "Its state directory keeps the final checkpoint.")
    return 0


def command_leaderboard(args) -> int:
    if args.action == "show":
        data = account_request(args, "POST", "/v1/account/leaderboard", {"visible": True})
    elif args.action == "hide":
        data = account_request(args, "POST", "/v1/account/leaderboard", {"visible": False})
    else:
        data = account_request(args, "GET", "/v1/account/leaderboard")
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    if args.action == "show":
        print("You are now listed on the leaderboard under your GitHub login.")
    elif args.action == "hide":
        print("You are no longer listed; your work still counts in the unlisted total.")
    else:
        visible = data.get("leaderboard_visible")
        print("leaderboard: " + ("listed" if visible else "not listed"
                                 if visible is not None else "unavailable"))
    return 0


def command_status(args) -> int:
    data = request(args, "GET", "/v1/status")
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    campaigns = data.get("campaigns") or []
    open_rows = [row for row in campaigns if row.get("received_points")]
    lines = [
        f"archived points: {points(data.get('total_archived_points', 0))}",
        f"active runs (24 h): {points(sum(row.get('recent_runs_24h') or 0 for row in campaigns))}",
        f"points per hour: {points(data.get('total_points_per_hour', 0))}",
        f"campaigns with work: {len(open_rows)} of {len(campaigns)}",
    ]
    for row in open_rows:
        share = row.get("expected_work_percent")
        lines.append(f"  {row.get('id')}: {points(row.get('received_points', 0))} points, "
                     f"{operations(row.get('estimated_work_log2'))} estimated operations"
                     + (f" ({share:.2f}% of expected)" if isinstance(share, (int, float)) else ""))
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecc", description="Manage an ECC Challenges account from a terminal.")
    parser.add_argument("--api-url", default=os.environ.get("ECC_API_URL", DEFAULT_API),
                        help=f"gateway origin (default: {DEFAULT_API})")
    parser.add_argument("--key-file",
                        default=os.environ.get("ECC_API_KEY_FILE", DEFAULT_KEY_FILE),
                        help=f"API key file (default: {DEFAULT_KEY_FILE})")
    parser.add_argument("--json", action="store_true", help="print the server response as JSON")
    parser.add_argument("--version", action="version", version=f"ecc {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    commands.add_parser("login", help="save an API key and check it").set_defaults(func=command_login)
    commands.add_parser("whoami", help="account, keys and runs summary").set_defaults(func=command_whoami)
    commands.add_parser("status", help="public platform totals").set_defaults(func=command_status)

    keys = commands.add_parser("keys", help="list API keys")
    keys.set_defaults(func=command_keys)
    key_commands = keys.add_subparsers(dest="action", metavar="ACTION")
    create = key_commands.add_parser("create", help="create a key and print its secret once")
    create.add_argument("--label", required=True, help="a name for the key")
    create.set_defaults(func=command_keys_create)
    revoke = key_commands.add_parser("revoke", help="revoke a key by ID")
    revoke.add_argument("key_id")
    revoke.set_defaults(func=command_keys_revoke)

    runs = commands.add_parser("runs", help="list account runs")
    runs.add_argument("--protocol", choices=("v1", "v2"), help="only protocol 1 or 2")
    runs.add_argument("--run-id", help="only this run")
    runs.set_defaults(func=command_runs)

    run = commands.add_parser("run", help="run detail and recent batch checks")
    run.add_argument("protocol", choices=("v1", "v2"))
    run.add_argument("run_id")
    run.set_defaults(func=command_run)

    close = commands.add_parser("close", help="close a protocol 2 run permanently")
    close.add_argument("run_id")
    close.set_defaults(func=command_close)

    board = commands.add_parser("leaderboard", help="show or change your leaderboard listing")
    board.add_argument("action", nargs="?", choices=("show", "hide"), default="status")
    board.set_defaults(func=command_leaderboard)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        print(f"ecc: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
