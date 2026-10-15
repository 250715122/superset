#!/bin/bash
# Build the frontend carrying the per-tab access control UI and pack the assets.
# Run detached:
#   nohup bash _build_frontend_tabroles.sh > /tmp/build_tabroles.log 2>&1 < /dev/null &
set -e
cd /opt/superset-build
echo "COMMIT|$(git log -1 --format='%h %s')|dirty=$(git status --porcelain | wc -l)"
cd superset-frontend
START=$(date +%s)
npm run build
echo "BUILD_SECONDS|$(( $(date +%s) - START ))"
cd ../superset/static

# the markers the existing deploys rely on, so a regression is obvious
grep -l 'Limit selectable time range' assets/*.js >/dev/null && echo "MARKER|time_filter_limit|OK"
grep -l 'echarts_geo_choropleth' assets/*.js >/dev/null && echo "MARKER|geo_choropleth|OK"
grep -l 'custom_echarts' assets/*.js >/dev/null && echo "MARKER|custom_echarts|OK"
# and the new one
grep -l 'Visible to everyone' assets/*.js >/dev/null && echo "MARKER|tab_access_ui|OK"

git -C /opt/superset-build rev-parse HEAD > assets/BUILD_COMMIT.txt
tar czf /tmp/assets_tabroles.tar.gz assets
sha256sum /tmp/assets_tabroles.tar.gz
echo BUILD_PACK_DONE
