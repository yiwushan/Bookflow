# BookFlow V0 Scope（v0.1.0）

## 目标
1. 首页双列瀑布流（上封面下标题）。
2. 章节原文 PDF 阅读优先，不做 AI 改写。
3. 目录驱动切分，缺目录进入人工标注。
4. 保留互动、进度、回忆推荐基础框架。

## 已落地（v0.1.0）
1. 导入链路：`outline > manual_toc > pending_manual_toc`。
2. 章节物化：目录叶子小节预切 PDF，落盘到 `data/books/derived/<book_id>/<chunk_id>.pdf`。
3. TOC 保存生效：`POST /v1/toc/save` 执行“保存 + 物化”。
4. Reader 支持 `pdf_section`：通过 `section_pdf_url` 直接阅读章节原文。
5. Feed 轻量混排：未完成优先 + 跨书交错 + 轻随机。
6. 完成判定收敛：仅 `section_complete` 计入拼图完成。

## 数据策略（V0）
1. 手工目录标注持久化：`data/toc/manual_annotations.json`。
2. 目录与物化状态同步回写 `books.metadata`。
3. 无目录书籍进入 `pending_manual_toc` 队列。

## Deferred
1. OCR 自动目录识别。
2. AI 重写/压缩。
3. 复杂语义推荐。
4. 自动长章节二次拆分。

## 验收口径
1. 有目录 PDF 导入后，可直接在 Feed/Reader 读取章节原文 PDF。
2. 无目录 PDF 可在 TOC 台批量粘贴目录，保存后立即可读。
3. 点赞/评论/完成可记录，`section_complete` 会点亮 Book 拼图。
