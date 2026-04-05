# BookFlow 任务看板（V0）

## NOW
- `NOW-502` 修复真实链路里发现的前后端问题（优先影响主流程的问题）。
- `NOW-503` 输出 `v0.1.0` 验收说明（可做/不可做/已知限制）。
- `NOW-504` 技术书目录标注质量提升（从 3 大段细化到可读小节级）。

## NEXT
- `NEXT-504` `chunk_pdf` 增加 Range 支持，优化长章节加载体验。
- `NEXT-505` TOC 标注台增加重叠区间可视化提示。
- `NEXT-506` 进度成就条加入“累计阅读分钟数”。

## LATER（Deferred）
- `LATER-001` OCR 自动目录识别。
- `LATER-002` AI 重写/压缩。
- `LATER-003` 复杂语义推荐。

## DONE（最近）
- `DONE-503` 跑通 `NOW-501`：两本真实 PDF 全链路验收完成（导入->标注->阅读->完成事件->进度增长）。
- `DONE-502` 修复导入阻塞：`scripts/import_book.py` 补回 `_safe_int`，恢复 PDF 导入流程。
- `DONE-501` 修复 Feed 500：`server/app.py` 中 PostgreSQL SQL `%` 占位冲突改为 `%%`。
- `DONE-500` 后端 `server/app.py` 按 V0 主链路重建，移除历史 trace/debug 噪音。
- `DONE-499` 前端四页重建：`/app`、`/app/reader`、`/app/book`、`/app/toc`。
- `DONE-498` 交互与进度口径收敛到 V0 核心事件。
- `DONE-497` TOC 预览/保存/物化流程与章节 PDF 阅读链路打通。
