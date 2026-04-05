# Specs 目录说明

本目录用于存放可直接开发的技术规格文档。

当前已产出：
1. `chunking.md`（小节优先切片器）
2. `render_mode.md`（reflow/crop 判定）
3. `events.md`（事件字典与聚合口径）
4. `schema.sql`（数据库 DDL）
5. `api.md`（Feed 与 Interactions API）
6. `metrics.sql`（核心看板指标 SQL）
7. `v0_scope.md`（当前版本范围冻结 + Deferred 清单）

下一步建议：
1. 将 `metrics.sql` 的统计口径与 `migrations/0003_metrics_materialized.sql` 持续对齐。
2. 为 `scripts/refresh_metrics.py` 补充定时调度说明（cron/systemd）。
3. 扩展 API 合约测试到 Postgres 模式。
