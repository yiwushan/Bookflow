# Render Mode Spec v1（reflow / crop 判定）

## 1. 目标
为每个 chunk 自动选择渲染模式：
1. `reflow`：可重排文本，阅读流畅。
2. `crop`：直接展示 PDF 原页裁切，保证版式保真。

## 2. 输入与输出

## 2.1 输入
```json
{
  "chunk_id": "ck_xxx",
  "book_type": "general|fiction|technical",
  "text": "string",
  "blocks": [
    {"kind": "paragraph|formula|code|table|list", "page": 12, "bbox": [0.1,0.2,0.9,0.4]}
  ],
  "extract_confidence": 0.0,
  "ocr_noise_ratio": 0.0,
  "line_break_noise_ratio": 0.0,
  "layout_complexity": 0.0
}
```

## 2.2 输出
```json
{
  "chunk_id": "ck_xxx",
  "render_mode": "reflow|crop",
  "render_score": {
    "reflow_score": 0.72,
    "crop_score": 0.28
  },
  "render_reason": ["low_noise", "simple_layout"],
  "source_anchor": {
    "page_start": 12,
    "page_end": 14,
    "bbox_union": [0.08, 0.17, 0.92, 0.88]
  },
  "fallback_mode": "crop"
}
```

## 3. 强规则（优先于打分）
1. 命中任一条件直接 `crop`：
   - `table_count >= 1` 且表格跨行复杂。
   - `formula_block >= 3` 且包含矩阵或多行对齐。
   - `code_block >= 1` 且缩进完整性检测失败。
   - `extract_confidence < 0.55`。
2. 命中任一条件优先 `reflow`：
   - 纯段落叙述 + `ocr_noise_ratio < 0.02` + `layout_complexity < 0.30`。

## 4. 打分模型（规则版）

`reflow_score = 0.30*text_integrity + 0.20*(1-ocr_noise_ratio) + 0.20*(1-layout_complexity) + 0.15*extract_confidence + 0.15*paragraph_density`

`crop_score = 0.35*layout_complexity + 0.25*formula_density + 0.20*table_density + 0.10*code_sensitivity + 0.10*(1-extract_confidence)`

判定规则：
1. 强规则先执行。
2. 否则比较 `reflow_score` 与 `crop_score`。
3. 差值小于 `0.08` 时，技术书取 `crop`，非技术书取 `reflow`。

## 5. 关键特征定义
1. `text_integrity`：去噪后句法连贯度（0-1）。
2. `paragraph_density`：段落块占比（0-1）。
3. `formula_density`：公式字符与块占比（0-1）。
4. `table_density`：表格区域占比（0-1）。
5. `code_sensitivity`：代码缩进和换行是否语义敏感（0-1）。
6. `layout_complexity`：多栏、浮动图、嵌入对象复杂度（0-1）。

## 6. source anchor 生成
1. 对 chunk 对应 block 取 `page_start/page_end`。
2. 每页合并 bbox，取全局 `bbox_union`。
3. 若 anchor 置信低，退化为整页 bbox `[0,0,1,1]`。
4. 所有模式都记录 anchor，便于“查看原文”。

## 7. 失败与回退
1. reflow 渲染失败：自动切 `crop`。
2. crop 资源缺失：回退 `reflow` + 警告标记 `needs_source_refetch`。
3. 双失败：展示 plain text 降级页面，并写错误事件。

## 8. 伪代码
```text
function choose_render_mode(chunk):
  if hit_force_crop(chunk):
    return crop_with_reason(chunk, "force_crop_rule")
  if hit_force_reflow(chunk):
    return reflow_with_reason(chunk, "force_reflow_rule")

  r = calc_reflow_score(chunk)
  c = calc_crop_score(chunk)
  if abs(r - c) < 0.08:
    mode = (chunk.book_type == "technical") ? "crop" : "reflow"
  else:
    mode = (r >= c) ? "reflow" : "crop"

  return build_result(mode, r, c, build_anchor(chunk))
```

## 9. 验收口径
1. 技术书抽样 500 chunk，公式错位率 < 1%。
2. `reflow` 文本可读率（人工抽检）>= 90%。
3. 误判率：
   - 应 `crop` 却 `reflow` < 5%
   - 应 `reflow` 却 `crop` < 10%
4. `source_anchor` 缺失率 < 0.5%。

## 10. 调参建议
1. 初期保守：技术书更偏 `crop`。
2. 随抽取质量提升，逐步提升 `reflow` 占比。
3. 按书籍类型维护阈值模板：
   - `template_general`
   - `template_fiction`
   - `template_technical`

