#!/bin/sh
# Point the pages at the API this deployment uses.
set -e
cat > /usr/share/nginx/html/config.js <<JS
window.API_BASE = "${API_BASE}";
JS
