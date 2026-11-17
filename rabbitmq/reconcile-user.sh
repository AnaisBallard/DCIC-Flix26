#!/bin/sh
set -eu

: "${RABBITMQ_DEFAULT_USER:?RABBITMQ_DEFAULT_USER is required}"
: "${RABBITMQ_DEFAULT_PASS:?RABBITMQ_DEFAULT_PASS is required}"
: "${RABBITMQ_NODENAME:=rabbit@rabbitmq}"

users="$(rabbitmqctl -n "$RABBITMQ_NODENAME" list_users --silent)"
if printf '%s\n' "$users" | awk '{print $1}' | grep -Fqx "$RABBITMQ_DEFAULT_USER"; then
  rabbitmqctl -n "$RABBITMQ_NODENAME" change_password \
    "$RABBITMQ_DEFAULT_USER" "$RABBITMQ_DEFAULT_PASS"
else
  rabbitmqctl -n "$RABBITMQ_NODENAME" add_user \
    "$RABBITMQ_DEFAULT_USER" "$RABBITMQ_DEFAULT_PASS"
fi

rabbitmqctl -n "$RABBITMQ_NODENAME" set_permissions \
  -p / "$RABBITMQ_DEFAULT_USER" '.*' '.*' '.*'
