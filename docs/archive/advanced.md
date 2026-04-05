# Advanced / 历史实验入口

说明：以下内容保留以便排障或回溯，不作为 V0 默认开发路径。

## 1) 高级 API 与调试参数
1. 服务端高级参数与完整 API 示例：`server/README.md`
2. 前端调试开关与实验 UI：`frontend/README.md`

## 2) 扩展验收脚本（非默认门禁）
1. 端到端验收：`python3 scripts/accept_end_to_end_flow.py ...`
2. 回忆帖验收：`python3 scripts/accept_memory_feed.py ...`
3. 回放与实验导出：
   - `python3 scripts/replay_memory_feed.py ...`
   - `python3 scripts/export_memory_position_ab_samples.py ...`
   - `python3 scripts/export_chunk_granularity_ab_samples.py ...`

## 3) 数据清理与运维脚本
1. `python3 scripts/cleanup_import_error_reports.py ...`
2. `python3 scripts/cleanup_feed_trace_files.py ...`
3. 调度文档：`docs/ops/*.md`

## 4) 全量测试
仅在里程碑或高风险变更时执行：
```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
