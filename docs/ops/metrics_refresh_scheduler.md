# 指标物化视图定时刷新（NOW-028）

目标：让 `scripts/refresh_metrics.py` 在本地或服务器上稳定定时执行，避免手工刷新。

## 前置条件
1. 已可连接 Postgres，且已执行：
   - `migrations/0001_init.sql`
   - `migrations/0003_metrics_materialized.sql`
2. 已安装 `psycopg`。
3. `DATABASE_URL` 可用。

## 方案 A：cron（简单直接）

### 1) 新建执行脚本
```bash
mkdir -p /opt/bookflow
cat >/opt/bookflow/refresh_metrics.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

cd /home/wushanyi/playground/bookflow
export DATABASE_URL='postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow'

/usr/bin/flock -n /tmp/bookflow-refresh-metrics.lock \
  /usr/bin/python3 scripts/refresh_metrics.py \
  >> /var/log/bookflow-refresh-metrics.log 2>&1
SH
chmod +x /opt/bookflow/refresh_metrics.sh
```

### 2) 写入 crontab（每 15 分钟）
```bash
crontab -e
```
加入：
```cron
*/15 * * * * /opt/bookflow/refresh_metrics.sh
```

说明：
1. 使用 `flock` 防止上一次刷新未结束时并发执行。
2. 日志落盘到 `/var/log/bookflow-refresh-metrics.log` 便于排障。

## 方案 B：systemd timer（推荐生产）

### 1) service 文件
新建 `/etc/systemd/system/bookflow-refresh-metrics.service`：
```ini
[Unit]
Description=BookFlow Refresh Materialized Metrics
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/wushanyi/playground/bookflow
Environment=DATABASE_URL=postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow
ExecStart=/usr/bin/python3 scripts/refresh_metrics.py
```

### 2) timer 文件
新建 `/etc/systemd/system/bookflow-refresh-metrics.timer`：
```ini
[Unit]
Description=Run BookFlow metrics refresh every 15 minutes

[Timer]
OnBootSec=2m
OnUnitActiveSec=15m
Persistent=true

[Install]
WantedBy=timers.target
```

### 3) 启用
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bookflow-refresh-metrics.timer
sudo systemctl status bookflow-refresh-metrics.timer
```

## 验证命令
```bash
export DATABASE_URL=postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow
python3 scripts/refresh_metrics.py
```

期望输出包含多行 `ok: REFRESH MATERIALIZED VIEW ...`。

## 故障排查
1. `DATABASE_URL is required`：环境变量未注入（cron/systemd 环境与当前 shell 不同）。
2. `relation "...mv_..." does not exist`：未执行 `0003_metrics_materialized.sql`。
3. 刷新太慢：先改为 `30m` 周期，后续再评估分视图刷新策略。
