# Development

## Setup

```sh
python/setup.sh      # uv venv outside the exFAT mount (symlinks), with the viewer's Qt
```

Checks, from `python/` with `UV_PROJECT_ENVIRONMENT` as `setup.sh` sets it:
`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`. All
at once: `pre-commit run --all-files` from the root, then pytest.

## Rules

1. **Receive only.** Nothing writes to the board's port; readers hold DTR and
   RTS low on it. The firmware is used as it is.
2. **The device, nothing else.** No calibration, no robot, no navigation
   types; those are `mipe`'s. A fact about the board goes into
   `docs/wire-protocol.md` with its evidence.
3. **Recordings are contracts.** The format changes only by a decision, with
   the reader keeping every layout ever written.
4. **Tests from bytes.** The decoder is tested from byte strings and the
   small captures in `tests/data`; a bug found on the bench becomes a
   fixture.
5. **Design choices get a decision record** (`docs/decisions/`), accepted by
   the user; conventional choices go ahead, named in the commit.
6. Tests with every behavioural change; no commented-out code; comments
   state contracts, units and reasons; plain words.
7. Git: feature branches once there is a remote; Conventional Commit titles;
   local commits, no pushes without being asked; no attribution trailers.
