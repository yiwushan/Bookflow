# Migrations

## Files
1. `0001_init.sql`: 初始表结构（来自 `docs/specs/schema.sql`）。
2. `0001_rollback.sql`: 回滚脚本（会删除全部 BookFlow 表和类型）。
3. `0002_seed_dev.sql`: 本地开发种子数据（用户/样例书/样例切片）。
4. `0003_metrics_materialized.sql`: 指标物化视图定义（dashboard 加速）。
5. `0004_interaction_rejections.sql`: interaction 拒绝事件落库（质量诊断）。
6. `0005_seed_tags.sql`: 标签种子与冷启动偏好映射（dev）。
7. `0006_reading_progress_trigger.sql`: section_complete 增量更新 reading_progress 触发器。
8. `0007_seed_memory_posts.sql`: 回忆帖开发种子（feed with_memory 验收）。
9. `0008_seed_memory_posts_realistic.sql`: 回忆帖真实样例种子（插流回放演示）。

## Apply
```bash
psql "$DATABASE_URL" -f migrations/0001_init.sql
psql "$DATABASE_URL" -f migrations/0003_metrics_materialized.sql
psql "$DATABASE_URL" -f migrations/0004_interaction_rejections.sql
psql "$DATABASE_URL" -f migrations/0006_reading_progress_trigger.sql
psql "$DATABASE_URL" -f migrations/0002_seed_dev.sql
psql "$DATABASE_URL" -f migrations/0005_seed_tags.sql
psql "$DATABASE_URL" -f migrations/0007_seed_memory_posts.sql
psql "$DATABASE_URL" -f migrations/0008_seed_memory_posts_realistic.sql
```

## Rollback
```bash
psql "$DATABASE_URL" -f migrations/0001_rollback.sql
```

## Seed (Dev)
```bash
psql "$DATABASE_URL" -f migrations/0002_seed_dev.sql
```

## Metrics MVs
```bash
psql "$DATABASE_URL" -f migrations/0003_metrics_materialized.sql
python3 scripts/refresh_metrics.py
```

## Progress Backfill
```bash
python3 scripts/backfill_reading_progress.py
```

若本机没有 `psql`，可用容器执行：
```bash
docker exec -i bookflow-pg psql -U bookflow -d bookflow < migrations/0003_metrics_materialized.sql
```

## Notes
1. 回滚是破坏性操作，仅用于开发环境。
2. 生产环境建议改成“前向修复”迁移，不直接回滚历史版本。
