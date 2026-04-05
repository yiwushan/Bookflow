# Server Skeleton

## Run
```bash
python3 server/app.py --host 127.0.0.1 --port 8000
```

默认 token（可改环境变量）：
```bash
export BOOKFLOW_TOKEN=local-dev-token
```

可选：启用 Postgres（推荐）
```bash
export DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/bookflow
psql "$DATABASE_URL" -f migrations/0001_init.sql
python3 server/app.py --host 127.0.0.1 --port 8000
```

一键本地开发库（Docker + 迁移 + seed）：
```bash
./scripts/dev_postgres.sh
```

说明：
1. 有 `DATABASE_URL` 且安装 `psycopg` 时，服务自动走 Postgres。
2. 否则自动回退内存模式（仅用于本地演示）。

## Health Check
```bash
curl -s http://127.0.0.1:8000/health
```

## Frontend MVP（同源静态页）
```bash
open http://127.0.0.1:8000/app
```
说明：
1. `/app`：Feed（双列瀑布流，卡片上封面下标题）
2. `/app/reader?book_id=<id>&chunk_id=<id>`：上下文轴阅读页
3. `/app/book?book_id=<id>&user_id=<id>`：书籍拼图页
4. `/app/toc`：人工目录标注台（批量粘贴目录 + 预览 + 保存）
4. 前端请求默认使用 `Authorization: Bearer local-dev-token`，可在页面顶部输入框覆盖。
5. Reader 页会在加载当前切片后，调用 `/v1/chunk_context_batch` 预取相邻切片上下文，降低切片切换 RTT，并展示全量/最近 N 次滑动窗口命中率，支持复制预取指标快照（JSON/Markdown，含最近 `ctx_source`、`window_hit_delta`、`hit/miss sparkline` 与命中率等级标签；`prefetch_window`、`level_low_threshold`、`level_high_threshold`、`level_label_template`、`level_label_low/medium/high` 与 `level_label_pattern` 可经 query/localStorage 配置并回显模板来源，快照 schema 含 `template_source_note/template_source_enum/template_source_enum_note/template_source_enum_version`，Markdown 附带 `snapshot_schema_fields_json/snapshot_schema_fields_json_lines/snapshot_schema_fields_json_first_line/snapshot_schema_fields_json_chars/snapshot_schema_fields_json_summary/snapshot_schema_fields_json_summary_source/snapshot_schema_fields_json_summary_length/snapshot_schema_fields_json_summary_version/snapshot_schema_fields_json_summary_template/snapshot_schema_fields_json_summary_template_source/snapshot_schema_fields_json_summary_template_source_version/snapshot_schema_fields_json_summary_template_source_note/snapshot_schema_fields_json_summary_template_source_note_version/snapshot_schema_fields_json_summary_template_source_note_template/snapshot_schema_fields_json_summary_template_source_note_template_version/snapshot_schema_fields_json_summary_template_source_note_template_source/snapshot_schema_fields_json_summary_template_source_note_template_source_version/snapshot_schema_fields_json_summary_template_source_note_template_source_note/snapshot_schema_fields_json_summary_template_source_note_template_source_note_version/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_version/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_version/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note/snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note_version/snapshot_schema_fields_json_summary_template_version/snapshot_schema_fields_json_hash/snapshot_schema_fields_json_hash_algorithm/snapshot_schema_fields_json_hash_length`，非法值自动纠正）。
6. Feed 页提供 memory/trace 调试预设，可一键回填 query 参数并同步 URL（便于复现调试场景），并支持保存/删除/导出/导入 localStorage 命名自定义预设（同名覆盖二次确认，支持 preview-only 预览导入 + 预览 Markdown + 仅冲突过滤，可附带冲突 old/new JSON 片段、仅变化字段模式、字段名过滤（可选正则 + flags + 大小写敏感开关 + 前缀匹配开关 + flags 非法字符即时提示 + flags 去重/生效预览 + compiled_pattern/compiled_pattern_source/compiled_pattern_note/compiled_pattern_length/compiled_pattern_flags_effective/compiled_pattern_flags_effective_source/compiled_pattern_flags_effective_note/compiled_pattern_flags_effective_version/compiled_pattern_flags_effective_template/compiled_pattern_flags_effective_template_source/compiled_pattern_flags_effective_template_source_version/compiled_pattern_flags_effective_template_source_note/compiled_pattern_flags_effective_template_source_note_version/compiled_pattern_flags_effective_template_source_note_template/compiled_pattern_flags_effective_template_source_note_template_version/compiled_pattern_flags_effective_template_source_note_template_source/compiled_pattern_flags_effective_template_source_note_template_source_version/compiled_pattern_flags_effective_template_source_note_template_source_note/compiled_pattern_flags_effective_template_source_note_template_source_note_version/compiled_pattern_flags_effective_template_source_note_template_source_note_template/compiled_pattern_flags_effective_template_source_note_template_source_note_template_version/compiled_pattern_flags_effective_template_source_note_template_source_note_template_source/compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_version/compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note/compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note_version/compiled_pattern_flags_effective_template_version 回显）、截断计数与折叠展示）。
7. Feed 调试面板会展示最近 5 次 trace 文件路径历史（含采集时间，本地持久化）并支持一键清空。

## Feed
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default" \
  -H "Authorization: Bearer local-dev-token"
```

带偏好混排（Postgres）：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111" \
  -H "Authorization: Bearer local-dev-token"
```

带排序调试 trace：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&trace=1" \
  -H "Authorization: Bearer local-dev-token"
```

带 trace 文件落盘：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&trace=1&trace_file=1" \
  -H "Authorization: Bearer local-dev-token"
```
响应会回显 `trace_file_path`（绝对路径），便于前端调试面板直接展示最近 trace 文件位置。

清理历史 trace 文件（建议定时任务）：
```bash
python3 scripts/cleanup_feed_trace_files.py --older-than-days 7 --dry-run --summary-only --markdown-output logs/feed_trace_cleanup.md --csv-output logs/feed_trace_cleanup.csv
```

带回忆帖占位（首屏）：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&with_memory=1" \
  -H "Authorization: Bearer local-dev-token"
```

带回忆帖频控（每 3 条普通内容插 1 条）：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&with_memory=1&memory_every=3" \
  -H "Authorization: Bearer local-dev-token"
```

带随机插位（可复现）：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&with_memory=1&memory_position=random&memory_every=3&memory_seed=7&memory_random_never_first=1" \
  -H "Authorization: Bearer local-dev-token"
```
关闭回忆候选多样化（调试）：
```bash
curl -s "http://127.0.0.1:8000/v1/feed?limit=10&mode=default&user_id=11111111-1111-1111-1111-111111111111&with_memory=1&memory_every=3&memory_diversity=off" \
  -H "Authorization: Bearer local-dev-token"
```
说明：memory 候选默认按 `source_chunk + memory_type` 轮转优先，降低连续同源回忆帖重复。
默认策略环境变量：`BOOKFLOW_MEMORY_DIVERSITY_DEFAULT=on|off`（默认 `on`）。
灰度环境变量：`BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT=0..100`（按 `user_id` 稳定分桶决定默认开关；设置后覆盖默认策略）。
灰度盐值：`BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT`（可选，用于变更分桶映射）。
trace 落盘来源标记：`query.memory_diversity_source`（`query/default/gray`）。
trace 落盘灰度参数：`query.memory_diversity_gray_percent`（环境变量灰度百分比，未配置时为 `null`）。
trace 灰度开关：`query.memory_diversity_rollout_enabled`（是否启用灰度分流）。
trace 灰度模式：`query.memory_diversity_rollout_mode`（`off|partial|full`）。
trace 灰度分桶：`query.memory_diversity_bucket`（`0..99`，稳定分桶调试值）。
trace 分桶百分位：`query.memory_diversity_rollout_bucket_percentile`（`bucket/100`，范围 `0.0..0.99`）。
trace 分桶百分位来源：`query.memory_diversity_rollout_bucket_percentile_source`（当前固定 `derived_from_bucket`）。
trace 分桶百分位标签：`query.memory_diversity_rollout_bucket_percentile_label`（`Pxx`，例如 `P07`）。
trace 灰度命中：`query.memory_diversity_rollout_bucket_hit`（是否满足 `bucket < gray_percent`）。
trace 灰度阈值：`query.memory_diversity_rollout_threshold_percent`（当前灰度阈值，未开启灰度时为 `null`）。
trace 分桶差值：`query.memory_diversity_rollout_bucket_distance`（`bucket - gray_percent`，未开启灰度时为 `null`）。
trace 默认值说明：`query.memory_diversity_default_note`（默认 on/off 及来源说明字符串）。

## Chunk Context（上一/下一切片）
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_context?book_id=22222222-2222-2222-2222-222222222222&chunk_id=33333333-3333-3333-3333-333333333331" \
  -H "Authorization: Bearer local-dev-token"
```

## Chunk Detail（阅读正文）
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_detail?book_id=22222222-2222-2222-2222-222222222222&chunk_id=33333333-3333-3333-3333-333333333331" \
  -H "Authorization: Bearer local-dev-token"
```

## Book Mosaic（书籍拼图 JSON）
```bash
curl -s "http://127.0.0.1:8000/v1/book_mosaic?book_id=22222222-2222-2222-2222-222222222222&user_id=11111111-1111-1111-1111-111111111111&min_read_events=1" \
  -H "Authorization: Bearer local-dev-token"
```
说明：该接口返回与 `render_book_homepage_mosaic.py --tiles-json-output` 对齐的核心结构（`summary + tiles + schema_version`），供前端拼图页直接消费。

## Chunk Context Batch（批量预取）
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_context_batch?book_id=22222222-2222-2222-2222-222222222222&chunk_ids=33333333-3333-3333-3333-333333333331,33333333-3333-3333-3333-333333333332" \
  -H "Authorization: Bearer local-dev-token"
```

带缓存指标（命中/回源/过期）：
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_context_batch?book_id=22222222-2222-2222-2222-222222222222&chunk_ids=33333333-3333-3333-3333-333333333331,33333333-3333-3333-3333-333333333332&cache_stats=1" \
  -H "Authorization: Bearer local-dev-token"
```
说明：
1. `cache_stats.request_trace_id` 与响应顶层 `trace_id` 一致，用于请求级关联。
2. `request_cache_hit_delta/request_cache_source_fetch_delta/request_cache_expired_delta` 表示本次请求的缓存计数增量。
3. `cache_entries_delta` 表示本次请求前后缓存项数量变化。
4. `cache_key_cardinality` 表示当前进程缓存键规模估算。
5. `cache_key_samples` 返回最多 3 个缓存 key 样本（调试用途，含 `expire_in_sec/expire_estimate_ts`）。
6. `sample_count` 返回当前样本条数（与 `cache_key_samples` 长度一致）。
7. `sample_book_ids` 返回样本中的 `book_id` 去重列表。
8. `sample_book_ids_count` 返回 `sample_book_ids` 的去重计数。
9. `sample_book_ids_sorted_by_seen` 返回 `book_id` 按样本首次出现顺序去重后的列表。
10. `sample_chunk_ids_count` 返回样本 `chunk_ids` 去重计数。
11. `sample_chunk_ids_sorted_by_seen` 返回 `chunk_ids` 按样本首次出现顺序去重后的列表。
12. `sample_chunk_ids_first_seen_source` 返回 `chunk_id -> {book_id,sample_index}` 的首次出现来源映射。
13. `sample_chunk_ids_first_seen_source_count` 返回 `sample_chunk_ids_first_seen_source` 条目数。
14. `sample_chunk_ids_first_seen_source_sorted_chunk_ids` 返回来源映射键（`chunk_id`）的升序列表。
15. `last_reset_trace_id` 记录最近一次 `cache_reset=1` 的请求 trace。
16. `reset_ts` 记录最近一次 `cache_reset=1` 的 UTC 时间戳。
17. `instance_id` 标识当前 API 进程实例（默认 `pid:<pid>`，可用 `BOOKFLOW_INSTANCE_ID` 覆盖）。
18. `instance_started_ts` 标识当前 API 进程启动时间（UTC ISO8601）。

重置缓存统计窗口并重新采样：
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_context_batch?book_id=22222222-2222-2222-2222-222222222222&chunk_ids=33333333-3333-3333-3333-333333333331,33333333-3333-3333-3333-333333333332&cache_stats=1&cache_reset=1" \
  -H "Authorization: Bearer local-dev-token"
```

POST JSON 版本：
```bash
curl -s "http://127.0.0.1:8000/v1/chunk_context_batch" \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"book_id":"22222222-2222-2222-2222-222222222222","chunk_ids":["33333333-3333-3333-3333-333333333331","33333333-3333-3333-3333-333333333332"]}'
```

## TOC 标注 API（V0）
```bash
curl -s "http://127.0.0.1:8000/v1/toc/pending?limit=20" \
  -H "Authorization: Bearer local-dev-token"
```

```bash
curl -s "http://127.0.0.1:8000/v1/toc/preview" \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"book_id":"<uuid>","toc_text":"第一章 绪论 ...... 1\n1.1 定义 ...... 3","total_pages":120}'
```

```bash
curl -s "http://127.0.0.1:8000/v1/toc/save" \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{"book_id":"<uuid>","entries":[{"title":"第一章 绪论","level":1,"start_page":1,"end_page":2}]}'
```

## Interactions
```bash
curl -s http://127.0.0.1:8000/v1/interactions \
  -H "Authorization: Bearer local-dev-token" \
  -H "Content-Type: application/json" \
  -d '{
    "events":[
      {
        "event_id":"2b8d2d25-0aaa-4f7f-b7e5-82f9cb872111",
        "event_type":"section_complete",
        "event_ts":"2026-03-28T18:10:00+08:00",
        "user_id":"u_001",
        "session_id":"s_001",
        "book_id":"b_sample_001",
        "chunk_id":"ck_001",
        "position_in_chunk":1.0,
        "idempotency_key":"u001_section_complete_ck001_202603281810",
        "client":{"platform":"web","app_version":"0.1.0","device_id":"d_001"},
        "payload":{"section_id":"sec_01","read_time_sec":180}
      }
    ]
  }'
```

Postgres 模式注意：
1. `user_id/book_id/chunk_id/event_id` 需为 UUID 格式。
2. `book_id/chunk_id` 需已存在于数据库，否则会被拒绝。
3. 被拒绝事件会写入 `interaction_rejections`（用于质量分析）。
4. `chunk_context_batch` 默认启用短 TTL 缓存（`BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_TTL_SEC` 默认 `5` 秒，`BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_MAX_ENTRIES` 默认 `256`）。

## API 合约测试
```bash
python3 -m unittest tests/test_api_contract.py
```

## Postgres 集成测试（interactions 批量写入）
```bash
./scripts/dev_postgres.sh
python3 -m unittest tests/test_postgres_integration.py
```

## 端到端验收（导入 -> Feed -> 上下文 -> 事件上报）
```bash
python3 scripts/accept_end_to_end_flow.py \
  --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow \
  --input examples/sample_import.txt \
  --title "E2E验收样例书" \
  --book-type technical \
  --user-id 11111111-1111-1111-1111-111111111111 \
  --markdown-output logs/accept/e2e_acceptance.md \
  --jsonl-output logs/accept/e2e_acceptance.jsonl
```
脚本会校验 `/v1/chunk_context_batch`（含缓存命中增量），并在输出中回显 `chunk_context_batch_*` 字段。

## 回忆帖插流回放（多场景）
```bash
python3 scripts/replay_memory_feed.py \
  --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow \
  --user-id 11111111-1111-1111-1111-111111111111 \
  --limit 8 \
  --scenarios top,1,3 \
  --jsonl-output logs/replay/memory_feed.jsonl \
  --csv-output logs/replay/memory_feed.csv \
  --markdown-output logs/replay/memory_feed.md
```
`memory_feed.csv` 列顺序：`scenario,memory_every,memory_inserted,memory_positions,first_item_type,items_count,trace_id,user_id,limit,memory_type_distribution,jsonl_schema_version,markdown_schema_version,markdown_schema_version_source,schema_version`。
其中 `first_item_type` 用于记录每个场景首条内容类型。
其中 `memory_type_distribution` 用于记录该场景 memory_type 分布（如 `month_ago:2, year_ago:1`）。
`memory_feed.jsonl` 字段包含：`schema_version,markdown_schema_version,scenario,memory_every,memory_inserted,memory_positions,first_item_type,items_count,trace_id,timeline,user_id,limit`。
`memory_feed.md` 每个场景会包含 `memory_type_distribution`（如 `month_ago:2, year_ago:1`），并在报告头回显 `csv_schema_version/jsonl_schema_version/markdown_schema_version/schema_version_consistency_note`。
脚本 JSON 输出会包含 `schema_version_consistency_note`（导出版本一致性说明）和 `markdown_schema_version`（传 `--markdown-output` 时）。

## memory_position A/B 样本导出
```bash
python3 scripts/export_memory_position_ab_samples.py \
  --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow \
  --user-id 11111111-1111-1111-1111-111111111111 \
  --limit 8 \
  --interval-every 3 \
  --random-seed 7 \
  --jsonl-output logs/replay/memory_position_ab.jsonl \
  --csv-output logs/replay/memory_position_ab.csv \
  --markdown-output logs/replay/memory_position_ab.md
```
可选：`--scenario-config config/memory_position_arms.sample.json`（也支持 YAML：`config/memory_position_arms.sample.yaml`）。

## chunk 粒度 A/B 样本导出
```bash
python3 scripts/export_chunk_granularity_ab_samples.py \
  --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow \
  --book-id 22222222-2222-2222-2222-222222222222 \
  --section-prefix sec_ \
  --chunk-title-keyword 梯度 \
  --limit 100 \
  --min-split-chars 120 \
  --jsonl-output logs/replay/chunk_granularity_ab.jsonl \
  --csv-output logs/replay/chunk_granularity_ab.csv \
  --markdown-output logs/replay/chunk_granularity_ab.md
```
可选：`--section-prefix` 仅导出 `section_id` 以前缀匹配的切片样本。
可选：`--chunk-title-keyword` 仅导出 `chunk_title` 包含关键词（`ILIKE`）的切片样本。
当传 `--chunk-title-keyword` 时，Markdown 报告会额外输出 `keyword_filter_total_candidates/matched_candidates/hit_rate`。
当传 `--chunk-title-keyword` 时，CSV 末尾会追加 `keyword_filter_summary` 汇总行（含 `keyword_filter_hit_rate`）。
Markdown 报告会包含 `CSV Notes` 区块，说明 `keyword_filter_summary` 汇总行语义。
`--jsonl-output` 每行会包含 `schema_version=chunk_granularity_ab_samples.jsonl.v1`，并镜像回显 `csv_schema_version=chunk_granularity_ab_samples.csv.v1`。
CSV 会包含 `markdown_schema_version=chunk_granularity_ab_samples.markdown.v1` 与 `schema_version=chunk_granularity_ab_samples.csv.v1`（包含 summary 行）。
Markdown 报告头部会回显 `jsonl_schema_version/csv_schema_version`。
Markdown 报告头部会回显 `markdown_schema_version`。
Markdown 报告头部会回显 `schema_version_consistency_note`。
脚本 JSON 输出会包含 `schema_version_consistency_note`（导出版本一致性说明）和 `markdown_schema_version`（传 `--markdown-output` 时）。

## 书籍主页拼图原型导出
```bash
python3 scripts/render_book_homepage_mosaic.py \
  --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow \
  --book-id 22222222-2222-2222-2222-222222222222 \
  --user-id 11111111-1111-1111-1111-111111111111 \
  --output logs/prototypes/book_homepage_mosaic.html \
  --tiles-json-output logs/prototypes/book_homepage_mosaic.tiles.json
```
输出说明：HTML 头部包含 tile 状态图例（已读/未读）与 `exported_at` 时间戳，`tiles.json` 也会包含 `exported_at` 字段。
图例会展示 `已读/未读` 的数量统计。
HTML 头部会回显 `min_read_events`。
HTML `<meta>` 会回显 `html_schema_version`（当前：`book_homepage_mosaic.html.v1`）。
HTML `<meta>` 会回显 `tiles_json_schema_version`（当前：`book_homepage_mosaic.tiles.v1`）。
`tiles.json` 还会包含 `schema_version`（当前：`book_homepage_mosaic.tiles.v1`）。
`tiles.json` 会镜像回显 `tiles_json_schema_version`（当前：`book_homepage_mosaic.tiles.v1`）。
`tiles.json` 会镜像回显 `html_schema_version`（当前：`book_homepage_mosaic.html.v1`）。
脚本 JSON 输出会包含 `html_schema_version`（当前：`book_homepage_mosaic.html.v1`）。
脚本 JSON 输出会包含 `html_meta_tiles_schema_echoed=true`（表示 HTML 已回显 tiles schema meta）。
`tiles.json` 会回显 `min_read_events`（与导出时参数一致）。
`tiles.json` 会回显 `html_title`（与 HTML 页面标题一致）。

## 拒绝原因聚合
```bash
export DATABASE_URL=postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow
python3 scripts/report_interaction_rejections.py --hours 24 --limit 20
```

## 回填阅读进度
```bash
export DATABASE_URL=postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow
python3 scripts/backfill_reading_progress.py
```

## 架构说明（当前）
1. `server/repository.py`：数据访问层（Memory/Postgres）。
2. `server/service.py`：业务编排层（供 `app.py` 调用）。
3. `server/app.py`：HTTP 协议层（参数校验/响应组装）。
