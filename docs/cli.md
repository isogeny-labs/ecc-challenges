# Manage an account from the terminal

The `ecc` command does the signed-in dashboard's work without a browser: it
shows your account, lists and creates API keys, lists runs and their checks,
closes a protocol 2 run and changes whether you are listed on the
[leaderboard](/leaderboard). It speaks the same HTTPS API as the worker and
authenticates with an API key, so it needs no GitHub session.

## Install and sign in

The command ships with the Python package. Install it from the repository with
`pipx` or `uv` so it gets its own environment:

```sh
pipx install "git+https://github.com/isogeny-labs/ecc-challenges"
# or: uv tool install "git+https://github.com/isogeny-labs/ecc-challenges"
ecc login
```

In a repository checkout, run `uv sync` and use `uv run ecc ...` instead.

`ecc login` reads the key without echoing it, saves it to
`~/.config/ecc-challenges/api-key` with mode `0600` and checks it against the
server. If you already saved a key there for a worker, skip the login. The
command reads `ECC_API_KEY_FILE` and `ECC_API_URL` when set, and
`--key-file` / `--api-url` override them.

A key is a credential for its whole account, so every command can list keys,
create or revoke keys, and change the leaderboard listing. The same rules apply
as on the dashboard: at most eight active runs per account, a one-minute pause
between new keys, and revoking a key suspends its runs. No command prints a
stored secret. `ecc keys create` prints the new secret once.

## Everyday commands

```sh
ecc whoami                       # login, leaderboard listing, key and run totals
ecc keys                         # key ID, label, state, last use, points
ecc keys create --label laptop   # print a new secret once
ecc keys revoke KEY_ID           # suspend the key and its runs
ecc runs                         # recent runs across both protocols
ecc runs --protocol v2           # only protocol 2 runs
ecc run v2 RUN_ID                # verification detail and recent batches
ecc close RUN_ID                 # permanently close a protocol 2 run
ecc leaderboard                  # list or not listed
ecc leaderboard show             # appear under your GitHub login
ecc leaderboard hide             # keep your work in the unlisted total
ecc status                       # public platform totals
```

Add `--json` before the command for the raw server response, which is useful in
scripts:

```sh
ecc --json runs | jq '.runs[] | {id, campaign, state, points}'
```

## Keys and state directories

The CLI manages account credentials and metadata, not worker checkpoints. A
worker keeps its state directory as the running-worker guide describes. Closing
a run does not delete that directory or its final checkpoint; resume a closed
run only with a new state directory. Protocol 1 (ECC2K-130 sigma) has no close
action, so `ecc close` accepts protocol 2 run IDs only.

If a command says the key was rejected, create a new key on the dashboard, save
it over the key file and sign in again. A `429` names the retry delay; do not
create extra keys or discard state to get around it.
