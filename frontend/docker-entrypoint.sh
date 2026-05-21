#!/bin/sh
set -eu

if [ -z "${ACCESS_API_BASE:-}" ]; then
  cat > /usr/share/nginx/html/config.js <<'EOF'
window.ACCESS_API_BASE = window.location.origin;
EOF
else
  escaped_api_base="$(printf '%s' "$ACCESS_API_BASE" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf 'window.ACCESS_API_BASE = "%s";\n' "$escaped_api_base" > /usr/share/nginx/html/config.js
fi

exec "$@"
