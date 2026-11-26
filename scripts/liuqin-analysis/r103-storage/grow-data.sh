#!/bin/sh
# Grow the seed APFS container to the UFS block device's actual capacity.
set -eu
marker=/private/var/db/.liuqin-data-grown
[ ! -f "$marker" ] || exit 0
work=$(/usr/bin/mktemp -d /private/var/tmp/liuqin-grow.XXXXXX)
trap '/bin/rm -rf "$work"' EXIT HUP INT TERM
/usr/sbin/diskutil info -plist /System/Volumes/Data > "$work/info.plist"
container=$(/usr/libexec/PlistBuddy -c 'Print :APFSContainerReference' "$work/info.plist")
case "$container" in disk*) ;; *) exit 1 ;; esac
number=${container#disk}
case "$number" in ''|*[!0-9]*) exit 1 ;; esac
/usr/sbin/diskutil apfs resizeContainer "$container" 0
/usr/bin/touch "$marker"
