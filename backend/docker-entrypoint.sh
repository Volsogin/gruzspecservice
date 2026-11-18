#!/bin/sh
# Apply migrations and load missing seed rows, then start the server.
set -eu
alembic upgrade head
python -m scripts.seed
exec "$@"
