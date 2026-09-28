#!/bin/sh
set -eu

: "${POSTGRES_REPLICATION_USER:=replicator}"
: "${POSTGRES_REPLICATION_PASSWORD:=$POSTGRES_PASSWORD}"

export PGPASSWORD="$POSTGRES_REPLICATION_PASSWORD"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  rm -rf "$PGDATA"/*
  until pg_isready -h db -U "$POSTGRES_REPLICATION_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    sleep 2
  done

  pg_basebackup \
    -h db \
    -D "$PGDATA" \
    -U "$POSTGRES_REPLICATION_USER" \
    -v \
    -P \
    -R \
    -X stream

  chmod 0700 "$PGDATA"
fi

if [ "$(id -u)" = "0" ]; then
  chown -R postgres:postgres "$PGDATA"
  exec gosu postgres postgres -c hot_standby=on
fi

exec postgres -c hot_standby=on
