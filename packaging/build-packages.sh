#!/bin/sh
# Runs INSIDE p9build: build every package under /work/packaging into the signed repo /work/p9repo.
# Key: /work/abuild-keys (created once, never in git). Publish: tools/p9-publish-repo.sh on the Mac.
set -e
export PACKAGER="hradaideh <hradaideh@users.noreply.github.com>"
K=/work/abuild-keys
if [ ! -f $K/p9lite.rsa ]; then
  mkdir -p $K; openssl genrsa -out $K/p9lite.rsa 4096 2>/dev/null
  openssl rsa -in $K/p9lite.rsa -pubout -out $K/p9lite.rsa.pub 2>/dev/null
fi
export PACKAGER_PRIVKEY=$K/p9lite.rsa
mkdir -p /etc/apk/keys; cp $K/p9lite.rsa.pub /etc/apk/keys/
for d in linux-huawei-venus-mainline p9lite-mainline; do
  cd /work/packaging/$d
  abuild -F checksum
  abuild -F -P /work/p9repo -r
done
ls -la /work/p9repo/packaging/aarch64/
