# BookFlow 接管入口（精简版）

目标：让任何人或 AI 在 5 分钟内接手，不依赖长对话历史。

## 1. 必读顺序（精简）
1. [README.md](../README.md)
2. [docs/TASK_BOARD.md](./TASK_BOARD.md)
3. [docs/STATE.json](./STATE.json)
4. [docs/specs/v0_scope.md](./specs/v0_scope.md)
5. [docs/FIRST_PRODUCT.md](./FIRST_PRODUCT.md)

## 2. 默认执行流程（加速）
1. 只选 `TASK_BOARD` 中一个 `NOW` 任务。
2. 完成功能后执行快速门禁：
   - `./scripts/smoke_first_product.sh`
   - 改动模块相关测试（按文件命中）。
3. 更新最小记录：
   - `docs/TASK_BOARD.md`
   - `docs/STATE.json`

## 3. 记录与决策写入频率
1. `SESSION_LOG.md`：仅在里程碑结束或发生阻塞时写短条目。
2. `DECISIONS.md`：仅记录高风险/不可逆取舍（接口、数据模型、产品方向）。
3. 普通实现细节不强制写会话日志和决策日志。

## 4. 全量测试触发条件
1. 里程碑交付前。
2. 数据模型或 API 发生变更后。
3. 出现回归信号时。

## 5. 已废弃的旧要求
1. 每轮必须全量 `python3 -m unittest discover`。
2. 每轮必须同步 `STATE + TASK_BOARD + SESSION_LOG + DECISIONS` 四件套。
3. 主文档维护超长低价值调试字段清单。

## 6. 历史资料与高级内容
1. [docs/archive/task_board_full_history_2026-03-30.md](./archive/task_board_full_history_2026-03-30.md)
2. [docs/archive/advanced.md](./archive/advanced.md)
