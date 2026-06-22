#!/system/bin/sh
# Polls BYD mediacenter media_session state -> /data/local/tmp/music-state.json
# Consumed by the app's 1Hz music card progress push (AGenUIFragment.pushMusicProgress).
#
# Available from dumpsys media_session:
#   state (PAUSED/PLAYING/etc)        ✓
#   position (PlaybackState.position) ✓  but =0 when paused; may not tick if mediacenter doesn't re-publish
#   title / artist (MediaDescription) ✓
# NOT available from dumpsys (only MediaMetadata, which dumpsys doesn't print):
#   duration   ✗  -> Slider max unknown, app shows "—" for dur_time
#   coverUrl   ✗  -> card uses Icon placeholder
# To get duration/cover the app must register a MediaController (MediaSessionManager) — TODO.
#
# Single-instance guard: subshell holds fd 9 lock for script lifetime.
# Android sh `exec N>file` is broken, so we use the ( ... ) 9>lock pattern.
(
  flock -n 9 || { echo "[music-monitor] already running, exit"; exit 0; }

  while true; do
    block=$(dumpsys media_session | grep -A 12 "package=com.byd.mediacenter" | head -12)
    pos_line=$(echo "$block" | grep "state=PlaybackState" | head -1)
    state=$(echo "$pos_line" | sed 's/.*state=\([A-Z]*\)(.*/\1/' | tr '[:upper:]' '[:lower:]')
    # position: first "position=N" on the PlaybackState line (avoid matching "buffered position=")
    position=$(echo "$pos_line" | grep -o 'position=[0-9]*' | head -1 | cut -d= -f2)
    [ -z "$position" ] && position=0
    desc=$(echo "$block" | grep "metadata:" | sed 's/.*description=//' | head -1)
    title=$(echo "$desc" | cut -d',' -f1 | sed 's/^[[:space:]]*//')
    artist=$(echo "$desc" | cut -d',' -f2 | sed 's/^[[:space:]]*//')
    if [ -n "$title" ]; then
      # write to tmp then mv — atomic rename avoids the app reading a half-written
      # (empty/truncated) file mid-write, which surfaces as
      # "pushMusicProgress failed: End of input at character 0".
      printf '{"ok":true,"state":"%s","position":%s,"title":"%s","artist":"%s"}\n' \
        "$state" "$position" "$title" "$artist" > /data/local/tmp/music-state.json.tmp
      mv /data/local/tmp/music-state.json.tmp /data/local/tmp/music-state.json
    fi
    sleep 3
  done

) 9>/data/local/tmp/music-monitor.lock
