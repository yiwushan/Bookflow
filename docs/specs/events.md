# Events Spec v1（section_complete / backtrack / confusion）

## 1. 目标
建立统一事件字典与聚合口径，服务于：
1. 北极星指标：完整小节完成数。
2. 连续深读评估：回看与上下文进入行为。
3. 内容质量反馈：看不懂问题定位。

## 2. 事件上报总协议

## 2.1 公共字段（所有事件必填）
```json
{
  "event_id": "uuid",
  "event_type": "string",
  "event_ts": "2026-03-28T17:30:00+08:00",
  "user_id": "u_xxx",
  "session_id": "s_xxx",
  "book_id": "b_xxx",
  "chunk_id": "ck_xxx",
  "position_in_chunk": 0.0,
  "client": {
    "platform": "ios|android|web|desktop",
    "app_version": "0.1.0",
    "device_id": "d_xxx"
  },
  "idempotency_key": "hash(user_id+event_type+chunk_id+event_ts_bucket)"
}
```

## 2.2 事件类型
1. `impression`：切片卡片曝光。
2. `enter_context`：进入上下文轴。
3. `backtrack`：回看上文。
4. `section_complete`：完整小节完成。
5. `skip`：快速划走。
6. `confusion`：用户明确反馈“看不懂/有疑问”。
7. `like`：点赞。
8. `comment`：评论。

## 3. 核心事件定义

## 3.1 section_complete
触发条件（满足任一）：
1. 用户滚动到小节尾部且停留 >= 2 秒。
2. 用户点击“下一小节”按钮。

附加字段：
```json
{
  "section_id": "sec_02_03",
  "read_time_sec": 265,
  "backtrack_count_in_section": 1,
  "is_auto_complete": false
}
```

## 3.2 backtrack
触发条件：
1. 点击“回看上文”。
2. 在上下文轴向前跳转到前置 chunk。

附加字段：
```json
{
  "from_chunk_id": "ck_12",
  "to_chunk_id": "ck_11",
  "hop": 1,
  "reason": "manual_tap|auto_suggest"
}
```

## 3.3 confusion
触发条件：
1. 用户点“看不懂”按钮。
2. 提交疑问输入框。

附加字段：
```json
{
  "confusion_type": "term|formula|logic|code|other",
  "note": "这一段的梯度推导不太明白",
  "selected_text_range": [120, 240],
  "severity": 1
}
```

## 4. 幂等与去重
1. 同 `idempotency_key` 24 小时内仅入库一次。
2. `section_complete` 每 `user_id + section_id + day` 默认只计 1 次。
3. `impression` 使用 `5s` 时间桶去重，防止抖动重复上报。

## 5. 事件状态机（阅读路径）
`impression -> enter_context -> backtrack(0..n) -> section_complete`

旁路事件：
1. `skip` 可在任意阶段触发。
2. `confusion` 可与 `backtrack` 同时出现。
3. `like/comment` 不影响完成判定，但影响偏好建模。

## 6. 聚合指标口径

1. `daily_section_complete_per_user`
   - 定义：用户每日去重后 `section_complete` 数量。
2. `context_entry_rate`
   - 定义：`enter_context / impression`。
3. `backtrack_rate`
   - 定义：`backtrack / enter_context`。
4. `confusion_rate`
   - 定义：`confusion / enter_context`。
5. `deep_read_depth_p50`
   - 定义：单次会话中，同书连续阅读 chunk 数量的 P50。
6. `fragmentation_risk_rate`
   - 定义：`(enter_context 后 10 秒内 skip 且无 backtrack) / enter_context`。

## 7. 示例请求（POST /v1/interactions）

## 7.1 section_complete 示例
```json
{
  "event_id": "2b8d2d25-0aaa-4f7f-b7e5-82f9cb872111",
  "event_type": "section_complete",
  "event_ts": "2026-03-28T18:10:00+08:00",
  "user_id": "u_001",
  "session_id": "s_001",
  "book_id": "b_1984",
  "chunk_id": "ck_0012",
  "position_in_chunk": 1.0,
  "idempotency_key": "u001_section_complete_ck0012_202603281810",
  "section_id": "sec_02_03",
  "read_time_sec": 274,
  "backtrack_count_in_section": 1,
  "is_auto_complete": false
}
```

## 7.2 backtrack 示例
```json
{
  "event_id": "cc5da884-4d00-4f0f-b4e6-51f5e5e5aaaa",
  "event_type": "backtrack",
  "event_ts": "2026-03-28T18:05:00+08:00",
  "user_id": "u_001",
  "session_id": "s_001",
  "book_id": "b_1984",
  "chunk_id": "ck_0012",
  "position_in_chunk": 0.18,
  "idempotency_key": "u001_backtrack_ck0012_202603281805",
  "from_chunk_id": "ck_0012",
  "to_chunk_id": "ck_0011",
  "hop": 1,
  "reason": "manual_tap"
}
```

## 7.3 confusion 示例
```json
{
  "event_id": "772f9fdd-a42f-4309-b0dc-58822cf0bbbb",
  "event_type": "confusion",
  "event_ts": "2026-03-28T18:06:30+08:00",
  "user_id": "u_001",
  "session_id": "s_001",
  "book_id": "b_1984",
  "chunk_id": "ck_0012",
  "position_in_chunk": 0.33,
  "idempotency_key": "u001_confusion_ck0012_202603281806",
  "confusion_type": "logic",
  "note": "这段因果关系没懂",
  "selected_text_range": [311, 402],
  "severity": 2
}
```

## 8. 服务端校验
1. 丢弃未来时间超过 10 分钟的事件。
2. `position_in_chunk` 必须在 `[0,1]`。
3. `confusion.note` 长度上限 `500` 字符。
4. `backtrack.hop` 必须为正整数。
5. `section_complete.read_time_sec` 最小 `10` 秒。

## 9. 数据存储建议
1. 热表：`interactions_hot`（近 7 天）用于实时看板。
2. 冷表：`interactions_daily`（分区）用于离线分析。
3. 物化视图：
   - `mv_user_daily_reading`
   - `mv_chunk_confusion_summary`

## 10. 验收标准
1. 三个核心事件（`section_complete/backtrack/confusion`）上报成功率 >= 99%。
2. 幂等去重后重复率 < 0.5%。
3. 指标延迟：
   - 实时看板 < 60 秒
   - 日报口径 T+1 09:00 前完成

