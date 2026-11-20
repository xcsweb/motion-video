#!/usr/bin/env bash
# Download the third-party BGM tracks used by audio/mix.py and the BGM A/B test.
# Both are free for commercial use under the Mixkit License; they are not
# redistributed with this repository.
set -euo pipefail
cd "$(dirname "$0")"

fetch() {
  local file="$1" id="$2" name="$3"
  if [ -s "$file" ]; then
    echo "exists: $file"
    return
  fi
  echo "downloading: $name"
  curl -L --fail --retry 3 -o "$file" "https://assets.mixkit.co/music/$id/$id.mp3"
}

fetch bgm.mp3 173 "Better Times are Coming"
fetch bgm_a_new_life.mp3 543 "A New Life"
