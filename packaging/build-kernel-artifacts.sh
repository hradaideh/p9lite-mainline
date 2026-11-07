#!/bin/sh
# Runs INSIDE p9build after the kernel (/work/out7prod) and Hi1102 modules (/work/hi1102) are built.
# Produces /work/packaging/linux-huawei-venus-mainline/kernel-artifacts-<ver>.tgz for the APKBUILD.
set -e
cd /work
O=/work/out7prod; V=$(cat $O/include/config/kernel.release); S=/tmp/kstage
rm -rf $S; mkdir -p $S
python3 mkstub.py $O/arch/arm64/boot/Image $S/vmlinuz
make -s -C linux-7.3.1 O=$O ARCH=arm64 INSTALL_MOD_PATH=$S/mod INSTALL_MOD_STRIP=1 modules_install
mkdir -p $S/mod/lib/modules/$V/extra
cp hi1102/hisi/platform/plat.ko hi1102/hisi/wifi/wifi.ko $S/mod/lib/modules/$V/extra/
rm -f $S/mod/lib/modules/$V/build $S/mod/lib/modules/$V/source
depmod -b $S/mod $V
cp $O/.config $S/config; echo $V > $S/kernel.release
mkdir -p /work/packaging/linux-huawei-venus-mainline
tar -C $S -czf /work/packaging/linux-huawei-venus-mainline/kernel-artifacts-$V.tgz vmlinuz config kernel.release mod
echo "artifacts for $V: $(sha256sum $S/vmlinuz | cut -c1-16)"
