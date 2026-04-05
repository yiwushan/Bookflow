# Chunking Spec v1（小节优先切片器）

## 1. 目标
将清洗后的书籍文本切为“可连续阅读且不破坏上下文”的卡片，遵循：
1. 小节完整性优先。
2. 目标阅读时长 3-8 分钟。
3. 技术内容不截断关键推导链。

## 2. 输入与输出

## 2.1 输入
```json
{
  "book_id": "string",
  "book_type": "general|fiction|technical",
  "language": "zh|en|mixed",
  "source": {
    "format": "pdf|epub|txt",
    "pages": 320
  },
  "clean_text": "string",
  "toc": [
    {"level": 1, "title": "string", "start_hint": "optional"}
  ],
  "blocks": [
    {
      "block_id": "b_001",
      "kind": "heading|paragraph|formula|code|table|list|figure_caption",
      "text": "string",
      "page": 12,
      "bbox": [0.12, 0.23, 0.88, 0.36]
    }
  ]
}
```

## 2.2 输出
```json
{
  "book_id": "string",
  "chunking_version": "chunking_v1",
  "chunks": [
    {
      "chunk_id": "ck_xxx",
      "section_id": "sec_02_03",
      "chunk_index_in_section": 1,
      "title": "string",
      "text": "string",
      "source_anchor_start": {"page": 12, "block_id": "b_001"},
      "source_anchor_end": {"page": 15, "block_id": "b_039"},
      "read_time_sec_est": 280,
      "has_formula": true,
      "has_code": false,
      "has_table": false,
      "prerequisite_chunk_ids": ["ck_prev_1"],
      "quality_score": 0.92,
      "quality_flags": []
    }
  ]
}
```

## 3. 参数与阈值（默认）
1. `target_read_sec_min=180`
2. `target_read_sec_max=480`
3. `soft_char_min=700`
4. `soft_char_max=2600`
5. `hard_char_max=3600`（超过必须拆）
6. `max_formula_break=0`（公式块不可跨块截断）
7. `max_code_break=0`（代码块不可跨块截断）
8. `quality_pass=0.80`

注：阅读时长估算先按字数模型，中文默认 `4.5 chars/sec`，英文默认 `17 words/min`。

## 4. 处理流程
1. 结构识别：从 `toc + heading blocks` 构建 section tree。
2. 小节定位：将 block 映射到最细粒度小节（优先 `h3/h4`）。
3. 小节成块：每个小节先生成一个候选 chunk。
4. 过长拆分：若超过 `target_read_sec_max` 或 `hard_char_max`，按语义边界拆分。
5. 技术保护：`formula/code/table` 边界强保护，不在中间切断。
6. 过短合并：若低于 `target_read_sec_min`，尝试与相邻同小节块合并。
7. 质量评分：评分不足触发回退策略。
8. 幂等 ID：`chunk_id = hash(book_id + anchor_start + anchor_end + chunking_version)`。

## 5. 拆分优先级（从高到低）
1. 标题边界（小节内部子标题）
2. 段落边界
3. 列表边界
4. 普通句号边界
5. 强制截断（仅在无有效边界时）

技术书附加规则：
1. `定义 -> 命题/定理 -> 证明 -> 例题` 视为一条“连续链”。
2. 若链超长，可在“证明结束”后拆，不在证明中部拆。
3. 带编号公式段落优先和其解释段同块。

## 6. 回退策略
1. 无 TOC 且标题噪声高：退化为“段落聚类 + 语义相似度分段”。
2. OCR 质量差：优先保守大块，等待渲染层 `crop` 兜底。
3. 质量分低于阈值：重新运行一次“低碎片参数集”。
4. 连续两次失败：标记 `needs_manual_review=true`，但仍输出可读块。

## 7. 质量评分
`quality_score = 0.30*boundary_integrity + 0.25*length_fit + 0.20*semantic_cohesion + 0.15*structure_preserve + 0.10*anchor_confidence`

硬失败条件：
1. 截断代码块或公式块。
2. chunk 为空或仅噪声字符。
3. source anchor 缺失。

## 8. 伪代码
```text
function build_chunks(book):
  sections = detect_sections(book.toc, book.blocks)
  candidates = []
  for sec in sections:
    raw = collect_blocks(sec)
    parts = split_if_oversize(raw, policy="section_first")
    parts = protect_technical_boundaries(parts)
    parts = merge_if_too_short(parts)
    for p in parts:
      c = materialize_chunk(p)
      c.quality_score = score_chunk(c)
      if c.quality_score < quality_pass:
        c = retry_with_low_fragmentation(p)
      candidates.append(c)
  return assign_deterministic_ids(candidates)
```

## 9. 边界案例
1. 一个小节 25 分钟阅读量：
   - 预期：拆为 3-5 个连续 chunk，并通过 `prerequisite_chunk_ids` 串联。
2. 公式与解释跨页：
   - 预期：同一 chunk 保持连续，必要时放宽长度阈值。
3. 代码块超过 200 行：
   - 预期：按函数/类边界拆，不在代码 token 流中间拆。
4. OCR 严重错行：
   - 预期：切片器保守输出，渲染层改为 `crop`。
5. 无目录小说：
   - 预期：按场景段落聚类为“自然段串”，单块 3-8 分钟。

## 10. 验收测试（最小集）
1. 输入 10 本技术书，`80%` 以上 chunk 与小节边界对齐。
2. 公式/代码截断率为 `0`。
3. `quality_score < 0.8` 的 chunk 占比低于 `15%`。
4. 重跑同输入，`chunk_id` 稳定率 `100%`。

## 11. 落地接口建议
1. CLI：`bookflow chunk --book-id <id> --input <clean.json> --out <chunks.json>`
2. 返回码：
   - `0` 成功
   - `10` 输入不合法
   - `20` 结构识别失败（已尽力输出）
   - `30` 写入失败

