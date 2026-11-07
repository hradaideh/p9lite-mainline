#!/bin/sh
# Copy the signed apk repo from the p9build container to the phone (/var/lib/p9repo) and trust its key.
# After this, `apk upgrade` on the phone picks up new linux-huawei-venus-mainline / p9lite-mainline builds.
set -e
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
podman cp p9build:/work/p9repo/packaging "$T/repo"
podman cp p9build:/work/abuild-keys/p9lite.rsa.pub "$T/p9lite.rsa.pub"
scp -q -r "$T/repo" "$T/p9lite.rsa.pub" user@192.168.2.50:/tmp/
ssh user@192.168.2.50 'set -e
sudo install -m644 /tmp/p9lite.rsa.pub /etc/apk/keys/p9lite.rsa.pub
sudo rm -rf /var/lib/p9repo && sudo mkdir -p /var/lib/p9repo && sudo cp -a /tmp/repo/. /var/lib/p9repo/ && rm -rf /tmp/repo /tmp/p9lite.rsa.pub
grep -qx /var/lib/p9repo /etc/apk/repositories || echo /var/lib/p9repo | sudo tee -a /etc/apk/repositories >/dev/null
sudo apk update -q 2>&1 | grep -v "^fetch" || true
apk search -v linux-huawei-venus-mainline p9lite-mainline'
