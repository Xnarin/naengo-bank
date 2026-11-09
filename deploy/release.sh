#!/usr/bin/env bash
set -euo pipefail
umask 027

release_id=${1:-}
[[ $release_id =~ ^[a-f0-9]{40}-[0-9]{1,20}-[0-9]{1,6}$ ]] || exit 2
exec 9>/run/lock/naengo-deploy.lock
flock 9

app=/opt/bank
web=/var/www/bank
previous=$(readlink -f "$app/current")
bucket=$(cat /etc/bank/deploy-bucket)
[[ -d "$previous/backend" && -f "$web/index.html" ]] || exit 2
release=$(mktemp -d "$app/releases/release-$release_id.XXXXXX")
switched=false
published=false

switch_backend() {
    ln -s "$1" "$app/current.next"
    mv -Tf "$app/current.next" "$app/current"
}

finish() {
    status=$?
    rm -f "$app/current.next" "$web/.index-$release_id"
    if (( status != 0 )); then
        if $published; then
            install -m 644 "$release/previous-index.html" "$web/.index-$release_id"
            mv -Tf "$web/.index-$release_id" "$web/index.html"
        fi
        if $switched; then
            switch_backend "$previous"
            systemctl restart bank-api
        fi
        echo 'Deployment failed. The previous release is selected.' >&2
        rm -rf -- "$release"
    fi
}
trap finish EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

aws s3api get-object --region ap-northeast-2 --bucket "$bucket" --key "releases/$release_id.tar.gz" "$release/archive.tar.gz" >/dev/null
/usr/bin/python3.12 - "$release" <<'PY'
import sys
import tarfile
from pathlib import Path

release = Path(sys.argv[1])
with tarfile.open(release / "archive.tar.gz", "r:gz") as archive:
    if any(not (entry.isfile() or entry.isdir()) for entry in archive.getmembers()):
        raise ValueError("Release archives must contain only regular files and directories")
    archive.extractall(release, filter="data")
PY
rm "$release/archive.tar.gz"
test -f "$release/data/products.json"
test -f "$release/dist/index.html"
if ! diff -qr --strip-trailing-cr -x __pycache__ "$previous/backend/alembic/versions" "$release/backend/alembic/versions"; then
    echo 'Migration files changed. Apply and verify the schema in a separate deployment.' >&2
    exit 1
fi

ln -s "$app/.env" "$release/.env"
mkdir -p "$release/data/rag"
ln -s "$app/data/rag/index" "$release/data/rag/index"
chgrp -hR bank "$release"
chmod -R g+rX,o-rwx "$release"
chown bank:bank "$release/backend"
runuser -u bank -- env UV_CACHE_DIR=/var/cache/naengo-deploy-uv UV_LINK_MODE=copy \
    /opt/certbot/bin/uv sync --project "$release/backend" --frozen --no-dev --python /usr/bin/python3.12
chown -hR root:bank "$release"
chmod -R g+rX,o-rwx "$release"

cp "$web/index.html" "$release/previous-index.html"
# Keep earlier hashed assets available to pages that are already open.
umask 022
cp -Rn --no-preserve=mode "$release/dist/assets/." "$web/assets/"
umask 027
nginx -t
switch_backend "$release"
switched=true
systemctl restart bank-api
curl --fail --silent --show-error --retry 8 --retry-connrefused --retry-delay 2 --max-time 5 \
    --resolve naengo.com:443:127.0.0.1 https://naengo.com/api/health

install -m 644 "$release/dist/index.html" "$web/.index-$release_id"
mv -Tf "$web/.index-$release_id" "$web/index.html"
published=true
curl --fail --silent --show-error --max-time 5 --resolve naengo.com:443:127.0.0.1 https://naengo.com/ \
    | cmp - "$release/dist/index.html"

trap - EXIT
for old_release in "$app"/releases/release-*; do
    if [[ -d "$old_release" && ! -L "$old_release" && "$old_release" != "$release" && "$old_release" != "$previous" ]]; then
        rm -rf -- "$old_release" || echo "Could not prune $old_release" >&2
    fi
done
echo "Deployed $release_id"
