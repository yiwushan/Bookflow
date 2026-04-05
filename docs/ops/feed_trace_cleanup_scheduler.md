# Feed Trace 定时清理（NOW-059）

目标：让 `logs/feed_trace/*.json` 自动清理，避免调试文件长期堆积。

## 前置条件
1. 项目目录可访问（示例：`/home/wushanyi/playground/bookflow`）。
2. Python3 可用。
3. 已有 trace 文件落盘（`GET /v1/feed?...&trace_file=1`）。

## 方案 A：cron（简单直接）

### 1) 新建执行脚本
```bash
mkdir -p /opt/bookflow
cat >/opt/bookflow/cleanup_feed_trace.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

cd /home/wushanyi/playground/bookflow

/usr/bin/flock -n /tmp/bookflow-cleanup-feed-trace.lock \
  /usr/bin/python3 scripts/cleanup_feed_trace_files.py \
    --older-than-days 7 \
    --cron-exit-codes \
    --summary-only \
    --markdown-output logs/feed_trace_cleanup.md \
    --csv-output logs/feed_trace_cleanup.csv \
  >> /var/log/bookflow-cleanup-feed-trace.log 2>&1
SH
chmod +x /opt/bookflow/cleanup_feed_trace.sh
```

### 2) 写入 crontab（每日凌晨 3 点）
```bash
crontab -e
```
加入：
```cron
0 3 * * * /opt/bookflow/cleanup_feed_trace.sh
```

说明：
1. 使用 `flock` 防止重复并发清理。
2. 默认是“归档模式”，归档目录为 `logs/feed_trace_archive/`。
3. `--cron-exit-codes`：`0` 正常、`2` 失败、`3` dry-run 发现候选、`4` 部分未处理。

## 方案 B：systemd timer（推荐生产）

### 1) service 文件
新建 `/etc/systemd/system/bookflow-cleanup-feed-trace.service`：
```ini
[Unit]
Description=BookFlow Cleanup Feed Trace Files
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/wushanyi/playground/bookflow
ExecStart=/usr/bin/python3 scripts/cleanup_feed_trace_files.py --older-than-days 7 --summary-only --markdown-output logs/feed_trace_cleanup.md --csv-output logs/feed_trace_cleanup.csv
```

### 2) timer 文件
新建 `/etc/systemd/system/bookflow-cleanup-feed-trace.timer`：
```ini
[Unit]
Description=Run BookFlow feed trace cleanup daily

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 3) 启用
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bookflow-cleanup-feed-trace.timer
sudo systemctl status bookflow-cleanup-feed-trace.timer
```

## 验证命令
```bash
python3 scripts/cleanup_feed_trace_files.py --older-than-days 7 --dry-run --summary-only --csv-output logs/feed_trace_cleanup.csv
```

期望输出：
1. `status=ok`
2. `candidates` 为待清理文件数
3. dry-run 模式下不实际删除/归档

## 故障排查
1. `Permission denied`：日志目录或归档目录权限不足。
2. `candidates` 长期增长：确认定时任务用户与应用写入用户一致。
3. 清理过度：调大 `--older-than-days` 或改为先 `--dry-run` 观察。
