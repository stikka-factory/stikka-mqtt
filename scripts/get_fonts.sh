#!/bin/bash
# Downloads every font family from The League of Moveable Type
# (https://www.theleagueofmoveabletype.com/) into frontend/public/fonts/.
#
# Each font is a separate GitHub repo under github.com/theleagueof/<repo>.
# Some repos commit the built .ttf/.otf files straight into the source tree,
# so we try the repo's default-branch archive first (avoids pinning a
# release version/URL per font, which would go stale). Others (e.g. Raleway,
# League Gothic/Mono) only ship design sources (.ufo/.glyphs) in the repo and
# publish built fonts as a GitHub Release asset instead - for those we fall
# back to that release's .zip asset.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$SCRIPT_DIR/../frontend/public/fonts"
mkdir -p "$DEST_DIR"

repos=(
    the-neue-black
    blackout
    chunk
    fanwood
    goudy-bookletter-1911
    junction
    knewave
    league-gothic
    league-mono
    league-script-number-one
    league-spartan
    linden-hill
    orbitron
    ostrich-sans
    prociono
    raleway
    sniglet
    sorts-mill-goudy
)

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

copy_fonts_from() {
    local dir="$1"
    local found=0
    while IFS= read -r -d '' font_file; do
        echo "  -> $(basename "$font_file")"
        cp "$font_file" "$DEST_DIR/"
        found=1
    done < <(find "$dir" -type f \( -iname '*.ttf' -o -iname '*.otf' \) -print0)
    [ "$found" -eq 1 ]
}

for repo in "${repos[@]}"; do
    echo "== $repo =="
    zip_path="$tmp_root/$repo.zip"
    extract_dir="$tmp_root/$repo"
    got_fonts=0

    for branch in master main; do
        url="https://github.com/theleagueof/$repo/archive/refs/heads/$branch.zip"
        if curl -fsSL -o "$zip_path" "$url"; then
            mkdir -p "$extract_dir"
            unzip -q "$zip_path" -d "$extract_dir"
            if copy_fonts_from "$extract_dir"; then
                got_fonts=1
            fi
            break
        fi
    done

    if [ "$got_fonts" -eq 0 ]; then
        # No built fonts in the source tree (repo ships design sources only,
        # e.g. .ufo/.glyphs) - fall back to the latest GitHub release's zip asset.
        asset_url=$(curl -fsSL "https://api.github.com/repos/theleagueof/$repo/releases/latest" \
            | grep -o '"browser_download_url": *"[^"]*\.zip"' \
            | head -1 \
            | sed -E 's/.*"(https:[^"]+)"/\1/')

        if [ -z "$asset_url" ]; then
            echo "  no fonts found in source and no release zip asset, skipping"
            continue
        fi

        release_zip="$tmp_root/$repo-release.zip"
        release_dir="$tmp_root/$repo-release"
        curl -fsSL -o "$release_zip" "$asset_url"
        mkdir -p "$release_dir"
        unzip -q "$release_zip" -d "$release_dir"
        if ! copy_fonts_from "$release_dir"; then
            echo "  release zip contained no .ttf/.otf files, skipping"
        fi
    fi
done

echo "Done. Fonts saved to $DEST_DIR"

"$SCRIPT_DIR/generate-fonts-index.sh"
