#!/bin/bash
# Tenbagger watchdog (audit 2026-08-26 P1): detect dead OR hung monitor and
# alert via Telegram. The multifactor system has one; tenbagger previously
# relied on systemd Restart=on-failure alone, which does NOT cover a hung
# (non-crashing) process - stops would silently stop firing.
#
# Detection:
#   1) systemctl is-active fails          -> service dead, systemd gave up
#   2) monitor.out mtime older than 180s  -> process hung (run_cycle prints
#      a cycle marker + report every 60s, 24/7, so mtime is a heartbeat)
# Rate limit: at most one alert per 30 min (state file).
#
# cron: */5 * * * * /data/tenbagger/tenbagger_watchdog.sh >> /data/tenbagger/logs/watchdog.log 2>&1
set -u

ENV_FILE=/root/.tenbagger-env
LOG=/data/tenbagger/logs/monitor.out
STATE=/data/tenbagger/logs/.watchdog_last_alert
NOW=$(date +%s)
LAST=$(cat "$STATE" 2>/dev/null || echo 0)

alert() {
    # $1 = message
    if [ $((NOW - LAST)) -lt 1800 ]; then
        echo "$(date -Is) alert suppressed (rate limit): $1"
        exit 0
    fi
    # shellcheck disable=SC1090
    [ -f "$ENV_FILE" ] && . "$ENV_FILE"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -m 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            --data-urlencode chat_id="$TELEGRAM_CHAT_ID" \
            --data-urlencode text="[AL 2] 🚨 watchdog: $1" >/dev/null \
            && echo "$NOW" > "$STATE"
    fi
    echo "$(date -Is) ALERT: $1"
}

# --- 1) service dead? ---
if ! systemctl is-active --quiet tenbagger-monitor; then
    STATUS=$(systemctl is-active tenbagger-monitor 2>&1)
    alert "tenbagger-monitor 服务状态=$STATUS（systemd 自动重启已放弃）。止损/风控停火，请立即人工检查：systemctl status tenbagger-monitor"
    exit 0
fi

# --- 2) hung? (heartbeat = monitor.out mtime, written every 60s cycle) ---
if [ -f "$LOG" ]; then
    MTIME=$(stat -c %Y "$LOG")
    AGE=$((NOW - MTIME))
    if [ "$AGE" -gt 180 ]; then
        alert "tenbagger-monitor 疑似 hang：monitor.out 已 ${AGE}s 无输出（正常 60s/周期）。进程在但循环卡死，止损停火。建议：systemctl restart tenbagger-monitor"
        exit 0
    fi
else
    alert "monitor.out 不存在（$LOG）- 日志路径异常，请检查部署"
    exit 0
fi

exit 0
