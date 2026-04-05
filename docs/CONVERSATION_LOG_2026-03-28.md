# Conversation Log (2026-03-28)

用途：给下一位 AI/协作者快速接管，避免上下文丢失。

## 1) 用户核心目标（原始意图）
1. 做一个“书流 BookFlow”，把电子书变成可滑动的信息流。
2. 核心不是“停留时长”，而是“看不懂会回看上文，从而愿意继续读”。
3. 技术书在此更多作为兴趣入口，不强求课堂级掌握。
4. 切片希望尽量是完整小节，避免过度碎片化。
5. 项目当前是个人自用，先不考虑公开分发与版权运营问题。
6. 需要“可中断、可续作”的协作模式，防止 AI 限额中断。
7. 用户已明确选型：持久化使用 Postgres。

## 2) 关键产品取舍（已落文档）
1. 北极星改为“人均每日完整小节完成数”，非停留时长。
2. 切片策略：小节优先，过长再拆（保留上下文链）。
3. 渲染策略：reflow 优先 + crop 兜底（复杂公式/表格/代码时）。
4. 技术书模式：问题导向钩子 + 连续深读优先。
5. 事件核心：section_complete / backtrack / confusion。

参考：
1. `docs/PRD.zh-CN.md`
2. `docs/specs/chunking.md`
3. `docs/specs/render_mode.md`
4. `docs/specs/events.md`

## 3) 连续协作机制（已建立）
1. `docs/START_HERE.md`
2. `docs/STATE.json`
3. `docs/TASK_BOARD.md`
4. `docs/DECISIONS.md`
5. `docs/SESSION_LOG.md`

## 4) 当前技术落地状态
1. DDL：`docs/specs/schema.sql`
2. API 草案：`docs/specs/api.md`
3. 指标 SQL：`docs/specs/metrics.sql`
4. 最小 pipeline：`scripts/pipeline.py`
5. pipeline 配置：`config/pipeline.json`
6. pipeline 测试：`tests/test_pipeline.py`（当前 7 条通过）
7. server skeleton：`server/app.py`
8. DAO：`server/dao.py`（Memory + Postgres 双后端）
9. 迁移：`migrations/0001_init.sql`, `migrations/0001_rollback.sql`
10. 开发 seed：`migrations/0002_seed_dev.sql`
11. 一键本地库：`scripts/dev_postgres.sh`

## 5) 本轮重要修复
1. 修复迁移问题：`interactions.event_date` 生成列表达式改为
   - `((event_ts AT TIME ZONE 'UTC')::date)`（可在 Postgres 正常迁移）
2. 修复 Postgres feed 查询参数类型问题（`server/dao.py`）。
3. 修复 pipeline 超长单段不拆分问题（`scripts/pipeline.py`）。

## 6) 已完成的 Postgres 端到端验收
1. 本地容器：`ghcr.io/cloudnative-pg/postgresql:16.6`
2. `./scripts/dev_postgres.sh` 可完成：
   - 起容器
   - 跑 `0001_init`
   - 跑 `0002_seed_dev`
3. 服务连库后：
   - `/health` 返回 `backend=postgres`
   - `/v1/feed` 返回真实 DB chunk
   - `/v1/interactions` 可写库（DB 已查到记录）

## 7) 当前下一步（交接优先级）
1. `NOW-019`：metrics 物化视图 + 刷新脚本
2. `NOW-020`：pipeline 阈值模板化（按 book_type）
3. `NOW-021`：API 合约测试自动化

见：`docs/TASK_BOARD.md`

## 8) 给下一位 AI 的执行入口
1. 先读：`docs/START_HERE.md`
2. 再读：`docs/STATE.json`（看 now_task_ids）
3. 然后按：`docs/TASK_BOARD.md` 的 NOW 顺序执行
4. 结束时更新：
   - `docs/STATE.json`
   - `docs/SESSION_LOG.md`
   - 如有策略变更，补 `docs/DECISIONS.md`

