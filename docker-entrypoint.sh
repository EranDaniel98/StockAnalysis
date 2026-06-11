#!/bin/sh
# Seed + symlink the mutable trees onto the Railway volume, then run the
# daily cron orchestrator.
#
# Railway allows ONE volume per service (mounted at $PERSIST_DIR,
# default /persist). The repo addresses data/, reports/, logs/ as
# relative paths from the workdir, so we move those trees onto the
# volume and symlink them back.
#
# Seeding matters: data/ has files checked into git (notably
# data/universe/sp500_*.csv -- the PIT membership oracle). `cp -rn`
# copies them into the volume WITHOUT overwriting anything a previous
# run (or the one-time migration in docs/railway_deploy.md) already
# put there.
set -eu

PERSIST_DIR="${PERSIST_DIR:-/persist}"

for tree in data reports logs; do
    mkdir -p "$PERSIST_DIR/$tree"
    if [ -d "$tree" ] && [ ! -L "$tree" ]; then
        cp -rn "$tree/." "$PERSIST_DIR/$tree/" 2>/dev/null || true
        rm -rf "$tree"
    fi
    ln -sfn "$PERSIST_DIR/$tree" "$tree"
done

exec python -m scripts.daily_cron "$@"
