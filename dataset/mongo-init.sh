#!/usr/bin/env bash
set -eu

encode_base64() {
  printf '%s' "$1" | base64 | tr -d '\n'
}

database_name="$(encode_base64 "${MONGODB_DATABASE:?MONGODB_DATABASE is required}")"
catalog_user="$(encode_base64 "${MONGODB_CATALOG_USER:?MONGODB_CATALOG_USER is required}")"
catalog_password="$(encode_base64 "${MONGODB_CATALOG_PASSWORD:?MONGODB_CATALOG_PASSWORD is required}")"
recommendation_user="$(encode_base64 "${MONGODB_RECOMMENDATION_USER:?MONGODB_RECOMMENDATION_USER is required}")"
recommendation_password="$(encode_base64 "${MONGODB_RECOMMENDATION_PASSWORD:?MONGODB_RECOMMENDATION_PASSWORD is required}")"
consumer_user="$(encode_base64 "${MONGODB_CONSUMER_USER:?MONGODB_CONSUMER_USER is required}")"
consumer_password="$(encode_base64 "${MONGODB_CONSUMER_PASSWORD:?MONGODB_CONSUMER_PASSWORD is required}")"
cleaner_user="$(encode_base64 "${MONGODB_CLEANER_USER:?MONGODB_CLEANER_USER is required}")"
cleaner_password="$(encode_base64 "${MONGODB_CLEANER_PASSWORD:?MONGODB_CLEANER_PASSWORD is required}")"

init_script=/tmp/dcic-flix-mongo-init.js
cat > "$init_script" <<EOF
const decode = (value) => Buffer.from(value, "base64").toString("utf8");
const databaseName = decode("$database_name");
const target = db.getSiblingDB(databaseName);

target.createUser({
  user: decode("$catalog_user"),
  pwd: decode("$catalog_password"),
  roles: [{ role: "read", db: databaseName }]
});
target.createUser({
  user: decode("$recommendation_user"),
  pwd: decode("$recommendation_password"),
  roles: [{ role: "read", db: databaseName }]
});
target.createUser({
  user: decode("$consumer_user"),
  pwd: decode("$consumer_password"),
  roles: [{ role: "readWrite", db: databaseName }]
});
target.createRole({
  role: "catalogCleaner",
  privileges: [
    { resource: { db: databaseName, collection: "movies" }, actions: ["find", "insert", "update", "remove"] },
    { resource: { db: databaseName, collection: "reviews" }, actions: ["find", "insert", "update", "remove"] },
    { resource: { db: databaseName, collection: "_catalog_pipeline" }, actions: ["find", "insert", "update", "remove"] },
    { resource: { db: databaseName, collection: "_cleaning_audit_details" }, actions: ["find", "insert", "update", "remove"] },
    { resource: { db: databaseName, collection: "_cleaning_audit_runs" }, actions: ["find", "insert", "update", "remove"] }
  ],
  roles: []
});
target.createUser({
  user: decode("$cleaner_user"),
  pwd: decode("$cleaner_password"),
  roles: [{ role: "catalogCleaner", db: databaseName }]
});

target.movies.createIndex({ title: 1 });
target.movies.createIndex({ year: 1 });
target.reviews.createIndex({ movie_id: 1 });
target.reviews.createIndex({ user_id: 1 });
target.reviews.createIndex({ movie_id: 1, user_id: 1 });
EOF

mongosh --quiet \
  --host 127.0.0.1 \
  --username "$MONGO_INITDB_ROOT_USERNAME" \
  --password "$MONGO_INITDB_ROOT_PASSWORD" \
  --authenticationDatabase admin \
  --file "$init_script"
rm -f "$init_script"
