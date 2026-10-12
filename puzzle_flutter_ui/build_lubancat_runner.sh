#!/bin/bash
set -e
cd "$(dirname "$0")"
bundle="$PWD/build/linux/arm64/release/bundle"
test -f "$bundle/lib/libapp.so"
test -f "$bundle/lib/libflutter_linux_gtk.so"
g++ -O2 -std=c++17 \
    -Ilinux -Ilinux/flutter/ephemeral \
    $(pkg-config --cflags gtk+-3.0) \
    linux/runner/main.cc linux/runner/my_application.cc \
    linux/flutter/generated_plugin_registrant.cc \
    -L"$bundle/lib" -lflutter_linux_gtk \
    $(pkg-config --libs gtk+-3.0) \
    -Wl,-rpath,'$ORIGIN/lib' \
    -o "$bundle/puzzle_flutter_ui"
echo "Built Flutter Linux runner against $(getconf GNU_LIBC_VERSION)"
