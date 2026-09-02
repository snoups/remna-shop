#!/bin/sh
set -eu

exec alembic -c src/infrastructure/database/alembic.ini upgrade head
