#!/system/bin/sh
# Single-instance guard: subshell holds fd 9 lock for script lifetime
# Android sh exec N>file is broken, so we use ( ... ) 9>lock pattern
(
  flock -n 9 || { echo "[gps-monitor] already running, exit"; exit 0; }

  while true; do
      logcat -d -s SomeIPMatrixManager:E 2>/dev/null | grep sendGps | tail -1 > /data/local/tmp/gps-line.txt
      LD_LIBRARY_PATH=/data/local/tmp/node-lib OPENSSL_CONF=/data/local/tmp/node-lib/openssl.cnf /data/local/tmp/node-termux /data/local/tmp/parse-gps.js
      sleep 3
  done

) 9>/data/local/tmp/gps-monitor.lock
