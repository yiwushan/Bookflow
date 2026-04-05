# API Spec v1（Feed + Interactions）

Base URL: `/v1`

认证方式（MVP）：
1. 本地单用户可先用固定 token。
2. Header: `Authorization: Bearer <token>`

## 1. GET /v1/feed

## 1.1 说明
获取信息流卡片，支持游标翻页。返回的是“小节入口卡”，不是整本全文。

## 1.2 Query 参数
1. `cursor` string，可选。
2. `limit` int，可选，默认 `20`，最大 `50`。
3. `mode` string，可选：`default|deep_read`，默认 `default`。
4. `book_type` string，可选：`general|fiction|technical`。
5. `user_id` uuid string，可选：当 `mode=default` 时用于“未完成优先”排序判定（`section_complete` 口径）。
6. `trace` bool-like，可选：`1|true` 时返回排序调试字段 `ranking_trace`。
7. `with_memory` bool-like，可选：`1|true` 时启用首屏回忆帖插流（需 `user_id`）。
8. `memory_position` string，可选：`top|interval|random`（仅 `with_memory=1` 时生效）。
9. `memory_every` int，可选：仅在 `with_memory=1` 时生效，表示“每 N 条普通内容插 1 条回忆帖”（范围 `1..50`）。
10. `memory_random_never_first` bool-like，可选：仅 `memory_position=random` 时生效，默认 `1`（首条不插回忆帖）。
11. `memory_seed` int，可选：仅 `memory_position=random` 调试时使用，控制随机插位复现。
12. `memory_diversity` string，可选：`on|off`，控制回忆候选是否启用多样化轮转（未传时走服务端默认策略）。
13. `trace_file` bool-like，可选：`1|true` 时按 `trace_id` 落盘调试文件到 `logs/feed_trace/`。

## 1.3 示例请求
```http
GET /v1/feed?limit=20&mode=default
Authorization: Bearer local-dev-token
```

## 1.4 成功响应
```json
{
  "items": [
    {
      "feed_item_id": "fi_001",
      "book_id": "b_1984",
      "book_title": "深度学习导论",
      "chunk_id": "ck_0012",
      "section_id": "sec_02_03",
      "title": "为什么会出现梯度消失？",
      "teaser_text": "反向传播链条越长，梯度会被反复缩放...",
      "render_mode": "crop",
      "source_anchor": {
        "page_start": 52,
        "page_end": 53,
        "bbox_union": [0.05, 0.12, 0.95, 0.90]
      },
      "has_formula": true,
      "has_code": false,
      "estimated_read_sec": 260,
      "ranking_trace": {
        "score": 0.91,
        "source": "simple_mix",
        "rank": 1
      }
    }
  ],
  "next_cursor": "eyJvZmZzZXQiOjIwfQ==",
  "memory_inserted": 1,
  "trace_id": "tr_abc123",
  "trace_file_path": "/abs/path/to/logs/feed_trace/tr_abc123.json"
}
```

## 1.5 业务规则
1. `mode=deep_read` 时优先返回同书相邻 chunk。
2. 技术书模式允许同书连续出现上限 5 条。
3. 每条 item 必须带 `render_mode` 与 `source_anchor`。
4. `mode=default` 且 `user_id` 有效时，按“未完成优先 + 跨书交错 + 轻随机”混排。
5. 仅在 `trace=1` 时返回 `ranking_trace`，默认不返回。
6. `with_memory=1` 仅在首屏（无 cursor）尝试插入回忆帖。
7. `memory_position=top` 时最多 1 条回忆帖置顶（默认行为）。
8. `memory_position=interval` 时按间隔插入（`memory_every` 不传时默认按 3）。
9. `memory_position=random` 时按随机位插入（可配 `memory_seed` 复现）。
10. `memory_random_never_first=1` 时 random 模式不允许首条回忆帖（有普通内容可用时）。
11. `memory_every` 仅在 interval/random 场景生效。
12. `memory_diversity=on` 时回忆帖候选按 `source_chunk + memory_type` 轮转优先，降低同源内容连续重复概率。
13. `memory_diversity=off` 时回忆帖候选回退为纯时间倒序（`source_date DESC, created_at DESC`）。
14. 未显式传 `memory_diversity` 时，默认策略由环境变量控制：
15. `BOOKFLOW_MEMORY_DIVERSITY_DEFAULT=on|off`（默认 `on`）。
16. `BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT=0..100` 时，按 `user_id` 稳定分桶灰度决定默认开关（覆盖上条默认策略）。
17. `BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT` 可选，用于调整分桶映射盐值。
18. `trace_file=1` 为调试用途，生产默认关闭；历史文件建议用 `scripts/cleanup_feed_trace_files.py` 定期清理。
19. feed trace 文件中的 `query.memory_diversity_source` 用于标记默认策略来源：`query|default|gray`。
20. feed trace 文件中的 `query.memory_diversity_gray_percent` 回显环境变量灰度百分比（未配置时为 `null`）。
21. feed trace 文件中的 `query.memory_diversity_default_note` 回显默认 on/off 及来源说明字符串。
22. feed trace 文件中的 `query.memory_diversity_bucket` 回显稳定分桶值（`0..99`）。
23. feed trace 文件中的 `query.memory_diversity_rollout_bucket_percentile` 回显分桶百分位（`bucket / 100`，范围 `0.0..0.99`）。
24. feed trace 文件中的 `query.memory_diversity_rollout_bucket_percentile_source` 回显分桶百分位来源（当前固定 `derived_from_bucket`）。
25. feed trace 文件中的 `query.memory_diversity_rollout_bucket_percentile_label` 回显分桶百分位标签（`Pxx`，例如 `P07`）。
26. feed trace 文件中的 `query.memory_diversity_rollout_enabled` 回显灰度开关是否启用（bool）。
27. feed trace 文件中的 `query.memory_diversity_rollout_mode` 回显灰度模式（`off|partial|full`）。
28. feed trace 文件中的 `query.memory_diversity_rollout_bucket_hit` 回显是否命中灰度分桶（`bucket < gray_percent`）。
29. feed trace 文件中的 `query.memory_diversity_rollout_bucket_distance` 回显分桶差值（`bucket - gray_percent`；未开启灰度时为 `null`）。
30. feed trace 文件中的 `query.memory_diversity_rollout_threshold_percent` 回显当前灰度阈值（未开启灰度时为 `null`）。
31. 当 `trace_file=1` 且落盘成功时，响应会返回 `trace_file_path`（绝对路径）；否则该字段为 `null`。

## 1.6 GET /v1/chunk_context

说明：给定当前 `chunk_id`（可选 `book_id`），返回同书上一/下一切片，用于深读模式无缝跳转。

Query 参数：
1. `chunk_id` string，必填。
2. `book_id` string，可选。

成功响应示例：
```json
{
  "book_id": "22222222-2222-2222-2222-222222222222",
  "chunk_id": "33333333-3333-3333-3333-333333333331",
  "title": "2.1 梯度下降的核心直觉",
  "prev_chunk_id": null,
  "prev_title": null,
  "next_chunk_id": "33333333-3333-3333-3333-333333333332",
  "next_title": "2.2 一个最小实现",
  "trace_id": "tr_ctx_xxx"
}
```

## 1.7 GET /v1/chunk_context_batch

说明：批量返回多个 chunk 的上下文导航，用于前端预取减少 RTT。

Query 参数：
1. `chunk_ids` string，必填，逗号分隔，最大 20 个。
2. `book_id` string，可选。
3. `cache_stats` bool-like，可选：`1|true` 时在响应中附带缓存命中指标。
4. `cache_reset` bool-like，可选：`1|true` 时请求前重置进程内缓存计数并清空缓存项。

服务端行为：
1. 接口结果带短 TTL 内存缓存（默认 5 秒，可通过 `BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_TTL_SEC` 调整）。
2. 缓存键为 `book_id + chunk_ids`，GET 与 POST 共用同一缓存。
3. 缓存项上限默认 256（`BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_MAX_ENTRIES`）。
4. `cache_reset=1` 可用于“从零开始”观测命中率窗口。
5. 当 `cache_stats=1` 时，响应里的 `cache_stats.request_trace_id` 与顶层 `trace_id` 一致，用于请求级关联。
6. 当 `cache_stats=1` 时，响应里追加 `request_cache_*_delta`，表示本次请求对命中/回源/过期计数的增量。
7. 当 `cache_stats=1` 时，响应里追加 `cache_entries_delta`，表示本次请求前后缓存项数量变化。
8. 当 `cache_stats=1` 时，响应里追加 `cache_key_cardinality`，表示当前进程缓存键规模估算。
9. 当 `cache_stats=1` 时，响应里追加 `cache_key_samples`（最多 3 个 key 样本，字段含 `book_id/chunk_ids/expire_in_sec/expire_estimate_ts`）。
10. 当 `cache_stats=1` 时，响应里追加 `sample_count`，表示当前返回样本条数。
11. 当 `cache_stats=1` 时，响应里追加 `sample_book_ids`，表示样本内 `book_id` 去重列表。
12. 当 `cache_stats=1` 时，响应里追加 `sample_book_ids_count`，表示 `sample_book_ids` 去重计数。
13. 当 `cache_stats=1` 时，响应里追加 `sample_book_ids_sorted_by_seen`，表示 `book_id` 按样本首次出现顺序去重列表。
14. 当 `cache_stats=1` 时，响应里追加 `sample_chunk_ids_count`，表示样本 `chunk_ids` 去重计数。
15. 当 `cache_stats=1` 时，响应里追加 `sample_chunk_ids_sorted_by_seen`，表示 `chunk_ids` 按样本首次出现顺序去重列表。
16. 当 `cache_stats=1` 时，响应里追加 `sample_chunk_ids_first_seen_source`，表示 `chunk_id -> {book_id,sample_index}` 的首次出现来源映射。
17. 当 `cache_stats=1` 时，响应里追加 `sample_chunk_ids_first_seen_source_count`，表示 `sample_chunk_ids_first_seen_source` 条目数。
18. 当 `cache_stats=1` 时，响应里追加 `sample_chunk_ids_first_seen_source_sorted_chunk_ids`，表示来源映射 `chunk_id` 的升序列表。
19. 当执行 `cache_reset=1` 时，`cache_stats.last_reset_trace_id` 会记录触发重置的请求 trace_id。
20. 当执行 `cache_reset=1` 时，`cache_stats.reset_ts` 会记录最近一次重置时间（UTC ISO8601）。
21. `cache_stats.instance_id` 标识当前服务实例（用于多实例排障关联）。
22. `cache_stats.instance_started_ts` 标识当前服务实例启动时间（UTC ISO8601）。

成功响应示例：
```json
{
  "items": [
    {
      "book_id": "22222222-2222-2222-2222-222222222222",
      "chunk_id": "33333333-3333-3333-3333-333333333331",
      "title": "2.1 梯度下降的核心直觉",
      "prev_chunk_id": null,
      "prev_title": null,
      "next_chunk_id": "33333333-3333-3333-3333-333333333332",
      "next_title": "2.2 一个最小实现"
    }
  ],
  "requested_count": 2,
  "found_count": 1,
  "not_found_chunk_ids": ["missing_chunk_id"],
  "cache_stats": {
    "cache_enabled": true,
    "cache_hit_count": 12,
    "cache_expired_count": 1,
    "cache_source_fetch_count": 5,
    "cache_hit_rate": 0.7059,
    "last_reset_trace_id": "tr_ctxb_prev_reset",
    "reset_ts": "2026-03-29T04:12:35.123456+00:00",
    "instance_id": "pid:12345",
    "instance_started_ts": "2026-03-29T03:58:00.000000+00:00",
    "request_trace_id": "tr_ctxb_xxx",
    "request_cache_hit_delta": 1,
    "request_cache_source_fetch_delta": 0,
    "request_cache_expired_delta": 0,
    "cache_entries_delta": 0,
    "cache_key_cardinality": 17,
    "cache_key_samples": [
      {
        "book_id": "22222222-2222-2222-2222-222222222222",
        "chunk_ids": ["333...331", "333...332"],
        "expire_in_sec": 4.823,
        "expire_estimate_ts": "2026-03-29T04:12:40.000000+00:00"
      }
    ],
    "sample_count": 1,
    "sample_book_ids": ["22222222-2222-2222-2222-222222222222"],
    "sample_book_ids_count": 1,
    "sample_book_ids_sorted_by_seen": ["22222222-2222-2222-2222-222222222222"],
    "sample_chunk_ids_count": 2,
    "sample_chunk_ids_sorted_by_seen": ["333...331", "333...332"],
    "sample_chunk_ids_first_seen_source": {
      "333...331": {"book_id": "22222222-2222-2222-2222-222222222222", "sample_index": 1},
      "333...332": {"book_id": "22222222-2222-2222-2222-222222222222", "sample_index": 1}
    },
    "sample_chunk_ids_first_seen_source_count": 2,
    "sample_chunk_ids_first_seen_source_sorted_chunk_ids": ["333...331", "333...332"]
  },
  "trace_id": "tr_ctxb_xxx"
}
```

POST 版本（推荐大批量）：
```http
POST /v1/chunk_context_batch
Authorization: Bearer local-dev-token
Content-Type: application/json

{
  "book_id": "22222222-2222-2222-2222-222222222222",
  "chunk_ids": [
    "33333333-3333-3333-3333-333333333331",
    "33333333-3333-3333-3333-333333333332"
  ]
}
```

## 1.8 GET /v1/chunk_detail

说明：返回单个切片的阅读详情，供前端上下文轴页渲染正文与元数据。

Query 参数：
1. `chunk_id` string，必填。
2. `book_id` string，可选。

成功响应示例：
```json
{
  "book_id": "22222222-2222-2222-2222-222222222222",
  "book_title": "深度学习导论",
  "book_type": "technical",
  "chunk_id": "33333333-3333-3333-3333-333333333331",
  "section_id": "sec_02_01",
 "title": "2.1 梯度下降的核心直觉",
  "text_content": "......",
  "teaser_text": "......",
  "content_type": "pdf_section",
  "section_pdf_url": "/v1/chunk_pdf?book_id=222...&chunk_id=333...",
  "page_start": 12,
  "page_end": 13,
  "render_mode": "crop",
  "source_anchor": {},
  "has_formula": true,
  "has_code": false,
  "has_table": false,
  "estimated_read_sec": 180,
  "trace_id": "tr_chunk_xxx"
}
```

## 1.9 GET /v1/chunk_pdf

说明：返回章节原文 PDF（二进制流），用于 Reader 内嵌预览。

Query 参数：
1. `book_id` uuid string，必填。
2. `chunk_id` uuid string，必填。
3. `token` string，可选（本地嵌入式预览兼容；优先仍推荐 Header 鉴权）。

成功响应：
1. HTTP `200`
2. `Content-Type: application/pdf`

## 1.10 GET /v1/book_mosaic

说明：返回书籍拼图页所需 JSON（`summary + tiles`），与离线导出的 tiles JSON 结构保持一致。

Query 参数：
1. `book_id` string，必填。
2. `user_id` uuid string，可选（为空时按 0 阅读事件返回全部未读态）。
3. `min_read_events` int，可选，默认 `1`，范围 `1..20`（V0 默认完成判定事件为 `section_complete`）。

成功响应示例：
```json
{
  "schema_version": "book_homepage_mosaic.tiles.v1",
  "tiles_json_schema_version": "book_homepage_mosaic.tiles.v1",
  "html_schema_version": "book_homepage_mosaic.html.v1",
  "html_meta_tiles_schema_echoed": true,
  "book_id": "22222222-2222-2222-2222-222222222222",
  "book_title": "深度学习导论",
  "user_id": "11111111-1111-1111-1111-111111111111",
  "min_read_events": 1,
  "summary": {
    "total_chunks": 120,
    "read_chunks": 18,
    "unread_chunks": 102,
    "completion_rate": 0.15
  },
  "tiles": [
    {
      "chunk_id": "33333333-3333-3333-3333-333333333331",
      "global_index": 1,
      "section_id": "sec_02_01",
      "chunk_title": "2.1 梯度下降的核心直觉",
      "read_events": 3,
      "state": "read"
    }
  ],
  "trace_id": "tr_mosaic_xxx"
}
```

## 1.11 TOC 接口（V0）

### GET /v1/toc/pending
返回 PDF 书籍目录处理队列。每个条目包含：
1. `needs_manual_toc`
2. `toc_source`
3. `materialization_status`
4. `materialized_chunk_count`

### POST /v1/toc/preview
输入批量目录文本，返回规范化预览（标题/层级/起止页 + warnings）。

### POST /v1/toc/save
保存目录并立即触发章节物化，回包包含：
1. `materialized_chunks`
2. `generated_pdf_count`
3. `failed_entries`
4. `warnings`

## 2. POST /v1/interactions

## 2.1 说明
统一上报事件，支持批量发送。服务端执行幂等去重。

## 2.2 请求体
```json
{
  "events": [
    {
      "event_id": "2b8d2d25-0aaa-4f7f-b7e5-82f9cb872111",
      "event_type": "section_complete",
      "event_ts": "2026-03-28T18:10:00+08:00",
      "user_id": "u_001",
      "session_id": "s_001",
      "book_id": "b_1984",
      "chunk_id": "ck_0012",
      "position_in_chunk": 1.0,
      "client": {
        "platform": "ios",
        "app_version": "0.1.0",
        "device_id": "d_001"
      },
      "idempotency_key": "u001_section_complete_ck0012_202603281810",
      "payload": {
        "section_id": "sec_02_03",
        "read_time_sec": 274,
        "backtrack_count_in_section": 1,
        "is_auto_complete": false
      }
    }
  ]
}
```

## 2.3 成功响应
```json
{
  "accepted": 1,
  "deduplicated": 0,
  "rejected": 0,
  "results": [
    {
      "event_id": "2b8d2d25-0aaa-4f7f-b7e5-82f9cb872111",
      "status": "accepted"
    }
  ],
  "trace_id": "tr_evt_456"
}
```

## 2.4 部分成功响应（示例）
```json
{
  "accepted": 1,
  "deduplicated": 1,
  "rejected": 1,
  "results": [
    {"event_id": "e1", "status": "accepted"},
    {"event_id": "e2", "status": "deduplicated"},
    {"event_id": "e3", "status": "rejected", "error_code": "INVALID_POSITION"}
  ],
  "trace_id": "tr_evt_789"
}
```

## 2.5 校验规则
1. `event_type` 只允许：
   - `impression`
   - `enter_context`
   - `backtrack`
   - `section_complete`
   - `skip`
   - `confusion`
   - `like`
   - `comment`
2. `position_in_chunk` 必须在 `[0,1]`。
3. `section_complete.payload.section_id` 必填。
4. `confusion.payload.confusion_type` 必填。
5. `backtrack.payload.from_chunk_id/to_chunk_id` 必填。

## 2.6 幂等规则
1. 以 `(user_id, idempotency_key)` 去重。
2. `section_complete` 额外执行 `(user_id, section_id, event_date)` 日级去重。
3. 重复请求返回 `deduplicated`，不报错。

## 3. 错误码
1. `INVALID_AUTH` 401：认证失败。
2. `INVALID_QUERY` 400：查询参数非法。
3. `INVALID_PAYLOAD` 400：请求体结构错误。
4. `INVALID_EVENT_TYPE` 400：未知事件。
5. `INVALID_POSITION` 400：`position_in_chunk` 越界。
6. `TOO_MANY_EVENTS` 413：单次事件数超过上限（默认 200）。
7. `INTERNAL_ERROR` 500：服务端异常。

## 4. 性能目标（MVP）
1. `GET /v1/feed`：缓存命中 `P95 < 300ms`。
2. `POST /v1/interactions`：单批 50 条事件 `P95 < 200ms`。
3. 事件处理可异步入库，但必须先返回 accepted/deduplicated/rejected 状态。

## 5. 向后兼容策略
1. 新字段只追加，不删除旧字段。
2. 新事件类型先灰度，客户端通过 `capabilities` 声明支持。
3. 错误码保持稳定，不重用语义。
