#!/usr/bin/env bash
# Scans frontend/public/fonts/ and writes fonts/index.json, a manifest the
# frontend fetches at runtime to populate the text-overlay font picker.
# There's no backend in MQTT static mode to list the directory server-side
# (fetchFonts() in mqtt-api.ts used to just return []), so the manifest is
# the only way the browser learns which fonts exist.
#
# Re-run after adding/removing files in frontend/public/fonts/ (e.g. after
# get_fonts.sh, which calls this automatically). Also wired up as a
# predev/prebuild step in frontend/package.json so `npm run dev` / `npm run
# build` always regenerate it first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONTS_DIR="$SCRIPT_DIR/../frontend/public/fonts"
INDEX_FILE="$FONTS_DIR/index.json"

if [[ ! -d "$FONTS_DIR" ]]; then
  echo "error: missing $FONTS_DIR" >&2
  exit 1
fi

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '%s' "$s"
}

names_file="$(mktemp)"
trap 'rm -f "$names_file"' EXIT

# One "<lowercase key>\t<display name>\t<filename>" per line, sorted so that
# when two files share a display name (e.g. Foo.otf and Foo.ttf) the first
# one wins the dedup pass below.
find "$FONTS_DIR" -maxdepth 1 -type f \
  \( -iname '*.ttf' -o -iname '*.otf' -o -iname '*.woff' -o -iname '*.woff2' \) \
  -printf '%f\n' \
| while IFS= read -r base; do
  name="${base%.*}"
  key="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
  printf '%s\t%s\t%s\n' "$key" "$name" "$base"
done | sort -t $'\t' -k1,1 -k3,3 > "$names_file"

count=0
body=""
last_key=""
while IFS=$'\t' read -r key name file; do
  if [[ "$key" == "$last_key" ]]; then
    continue
  fi
  last_key="$key"
  comma=','
  [[ -n "$body" ]] && body+=$'\n'
  body+="    { \"name\": \"$(json_escape "$name")\", \"path\": \"$(json_escape "$file")\" }$comma"
  count=$((count + 1))
done < "$names_file"

# Strip the trailing comma off the last entry.
body="${body%,}"

{
  echo '{'
  echo '  "generatedAt": "'"$(date -u +"%Y-%m-%dT%H:%M:%SZ")"'",'
  echo '  "source": "stikka-fonts",'
  echo '  "fonts": ['
  echo "$body"
  echo '  ]'
  echo '}'
} > "$INDEX_FILE"

echo "Wrote $count font entries to $INDEX_FILE"
