#!/system/bin/sh
# Output real GNSS coords from gps-monitor as "lng,lat" with 6 decimal places.
# Use this to inject coords into amap URLs (regeo, weather, direction) WITHOUT
# risking LLM-side string truncation (deepseek sometimes drops decimals and
# produces "114,22" which makes AMap silently fall back to IP location).
#
# Usage:
#   COORDS=$(sh /data/local/tmp/gps-coords.sh)
#   sh /data/local/tmp/amap.sh "https://restapi.amap.com/v3/geocode/regeo?location=${COORDS}&output=JSON"
#
# Output on success: "114.364147,22.677997\n" (single line)
# Output on failure: "ERR:reason\n", exit 1

LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux -e '
const fs = require("fs");
try {
  const d = JSON.parse(fs.readFileSync("/data/local/tmp/gps.json", "utf8"));
  if (!d.ok || !d.lat || !d.lng) {
    console.log("ERR:invalid_gps " + JSON.stringify(d));
    process.exit(1);
  }
  console.log(Number(d.lng).toFixed(6) + "," + Number(d.lat).toFixed(6));
} catch (e) {
  console.log("ERR:no_gps_file " + e.message);
  process.exit(1);
}
'
