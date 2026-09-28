#!/bin/sh
set -eu

: "${POSTGRES_REPLICATION_USER:=replicator}"
: "${POSTGRES_REPLICATION_PASSWORD:=$POSTGRES_PASSWORD}"

until pg_isready -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 2
done

psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v repl_user="$POSTGRES_REPLICATION_USER" \
  -v repl_password="$POSTGRES_REPLICATION_PASSWORD" <<'SQL'
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'repl_user')
    THEN format('ALTER ROLE %I WITH REPLICATION LOGIN PASSWORD %L', :'repl_user', :'repl_password')
  ELSE format('CREATE ROLE %I WITH REPLICATION LOGIN PASSWORD %L', :'repl_user', :'repl_password')
END
\gexec
SQL
