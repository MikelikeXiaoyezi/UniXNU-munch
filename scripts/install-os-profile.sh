#!/bin/sh
# Link this repository's OS profile into a UniXNU checkout.
#
# UniXNU resolves profiles only under profiles/os/. The iOS 16 profile ships
# with the device repository because it is not upstream yet.
#
# Usage: scripts/install-os-profile.sh /path/to/UniXNU
set -eu
UNIXNU=${1:?usage: $0 /path/to/UniXNU}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROFILE=ios-16.7.16-20H392
TARGET="$UNIXNU/profiles/os/$PROFILE"

if [ ! -d "$UNIXNU/profiles/os" ]; then
  echo "error: $UNIXNU does not look like a UniXNU checkout" >&2
  exit 1
fi
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
  echo "error: $TARGET exists and is not a symlink" >&2
  exit 1
fi
ln -sfn "$HERE/os-profiles/$PROFILE" "$TARGET"
echo "linked $TARGET -> $HERE/os-profiles/$PROFILE"
echo "now run: ./unixnu defconfig munch_defconfig -D $HERE"
