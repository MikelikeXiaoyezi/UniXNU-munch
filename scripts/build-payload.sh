#!/usr/bin/env bash
# Assemble the ESP payload for iOS 16.7.16 and write a FAT32 image.
#
# Inputs are produced outside this repository:
#   kernel.macho        built from xnu-8796.141.3 (see docs/BUILD.md)
#   kernel.macho.adt    scripts/make-munch-adt.py
#   trustcache bundle   from the iPhone X 16.7.16 IPSW (StaticTrustCache +
#                       Cryptex1,SystemTrustCache)
#   data seed           APFS OwnerData container (optional)
#
# UniXNU.efi is taken from the edk2-msm build output; it is also embedded in
# the firmware volume. The copy on the ESP is \EFI\BOOT\BOOTAA64.EFI, which the
# edk2-msm BDS boots as a removable-media application.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${OUT:-"$ROOT/build/payload"}
ESP=${ESP:-"$ROOT/build/munch-esp.img"}
SIZE_MIB=${SIZE_MIB:-176}
TITLE=${TITLE:-"iOS 16.7.16 (munch)"}
KERNEL=${KERNEL:-}
ADT=${ADT:-}
TRUST=${TRUST:-"$ROOT/../build/ios16.7.16/kernel.macho.trustcache"}
DATA=${DATA:-}
EFI=${EFI:-}
ARGS=${ARGS:-}

usage() {
  cat >&2 <<EOF
usage: KERNEL=path ADT=path TRUST=path [DATA=path] [EFI=path] $0

  KERNEL  kernel.macho from the iOS 16 XNU build
  ADT     kernel.macho.adt from scripts/make-munch-adt.py
  TRUST   trust cache bundle (optional but required by AMFI for userland)
  DATA    Data seed (optional)
  EFI     UniXNU.efi; default: uefi/edk2-msm-munch/Build/munch/RELEASE_CLANG38/AARCH64/UniXNU.efi
  ARGS    kernel command line (default: board.toml [payload] kernel_args)
EOF
}

[ -n "$KERNEL" ] && [ -f "$KERNEL" ] || { usage; exit 2; }
[ -n "$ADT" ] && [ -f "$ADT" ] || { usage; exit 2; }
if [ -z "$EFI" ]; then
  EFI=$(find "$ROOT/../uefi/edk2-msm-munch/workspace/Build" -path "*/AARCH64/UniXNU.efi" -print -quit 2>/dev/null || true)
fi
[ -n "$EFI" ] && [ -f "$EFI" ] || { echo "error: UniXNU.efi not found; run scripts/build-uefi.sh or set EFI=..." >&2; exit 1; }

PAYLOAD="$OUT/volume"
mkdir -p "$PAYLOAD/EFI/BOOT" "$PAYLOAD/EFI/UniXNU/Payloads"
cp "$EFI" "$PAYLOAD/EFI/BOOT/BOOTAA64.EFI"
cp "$KERNEL" "$PAYLOAD/EFI/UniXNU/Payloads/kernel.macho"
cp "$ADT" "$PAYLOAD/EFI/UniXNU/Payloads/kernel.macho.adt"
if [ -n "$TRUST" ]; then
  [ -f "$TRUST" ] || { echo "error: trust cache not found: $TRUST" >&2; exit 1; }
  cp "$TRUST" "$PAYLOAD/EFI/UniXNU/Payloads/kernel.macho.trustcache"
fi
if [ -n "$DATA" ]; then
  [ -f "$DATA" ] || { echo "error: data seed not found: $DATA" >&2; exit 1; }
  cp "$DATA" "$PAYLOAD/EFI/UniXNU/Payloads/scratch-data.img"
fi

python3 - "$PAYLOAD/EFI/UniXNU/unixnu.toml" "$TITLE" "$DATA" "$ARGS" "$ROOT/board.toml" <<'PY'
import sys, tomllib
from pathlib import Path
out, title, data, args, board_path = sys.argv[1:]
board = tomllib.loads(Path(board_path).read_text())
if not args:
    args = " ".join(board.get("payload", {}).get("kernel_args", []))
lines = [
    "version = 1",
    "",
    "[boot]",
    "timeout = 3",
    'default = "xnu"',
    "",
    "[kits]",
    "autoload = false",
    "",
    "[[entry]]",
    'id = "xnu"',
    f'title = "{title}"',
    'type = "xnu"',
    'path = "Payloads/kernel.macho"',
    f'args = "{args}"',
]
if data:
    lines.append('initrd = "Payloads/scratch-data.img"')
Path(out).write_text("\n".join(lines) + "\n")
print(out)
PY

python3 "$ROOT/scripts/make_fat32.py" --source "$PAYLOAD" --output "$ESP" \
  --size-mib "$SIZE_MIB" --label MUNCHESP

cat <<EOF
payload volume: $PAYLOAD
ESP image:      $ESP ($(stat -c%s "$ESP") bytes)
next: write the ESP image to the phone's payload partition, then flash the UEFI boot image
EOF
