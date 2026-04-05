# BookFlow V0 (Clean Rebuild)

这是一个为个人电子书库设计的“章节原文 PDF 信息流”应用（单用户、本地优先）。

## V0 已实现能力
1. PDF 目录驱动切分：按目录小节生成章节 PDF（不从小节中间切断）。
2. 手工目录标注台：批量粘贴目录 -> 预览定位 -> 保存并立即物化。
3. 目录审核门禁：所有书默认“待审核”，审核通过后才进入 Feed。
4. 首页双列 Feed：上封面下标题，点击进入章节阅读。
5. Reader：章节原文 PDF 阅读 + 上一节/下一节 + 完成/看不懂/点赞/评论。
6. 书籍拼图页：已读点亮、未读灰态，展示完成率。
7. 互动上报：`impression/enter_context/backtrack/section_complete/confusion/like/comment`。
8. 回忆帖框架：`with_memory=1` 时可混入 memory_post（若数据库中有数据）。

## Deferred（V0 不做）
1. OCR 自动目录识别。
2. AI 重写/压缩。
3. 复杂语义推荐（向量召回/重排）。

## 快速启动
```bash
python3 server/app.py --host 127.0.0.1 --port 8000
```

## 设备一键部署（Ubuntu ARM 推荐）
```bash
./scripts/deploy_device_oneplus6t.sh
```

可选：安装 systemd 常驻服务
```bash
./scripts/deploy_device_oneplus6t.sh --install-systemd
```

后端默认启用“启动自举”：
1. 服务启动后后台自动扫描 `data/books/inbox` 并导入新增书目（不依赖前端触发）。
2. 自动预热 Feed 查询与部分封面缓存，前端打开即可用。
3. 周期巡检目录，发现新增文件会自动导入。

可选环境变量（按需覆盖）：
1. `BOOKFLOW_STARTUP_BOOTSTRAP_ENABLED=1|0`
2. `BOOKFLOW_STARTUP_BOOTSTRAP_INPUT_DIR=data/books/inbox`
3. `BOOKFLOW_STARTUP_BOOTSTRAP_INTERVAL_SEC=300`
4. `BOOKFLOW_STARTUP_BOOTSTRAP_SKIP_EXISTING=1`
5. `BOOKFLOW_STARTUP_BOOTSTRAP_WARM_COVER_LIMIT=24`
6. `BOOKFLOW_STARTUP_BOOTSTRAP_AUTO_APPROVE_IMPORTED=0`（设为 `1` 可导入后自动审核通过）

打开：
1. `http://127.0.0.1:8000/app`（Feed）
2. `http://127.0.0.1:8000/app/toc`（目录标注台）

首页已提供“导入图书”路径输入与一键导入按钮（调用 `/v1/books/import`）。

## 如何增加图书（批量导入）
将 PDF 放到 `data/books/inbox`（或你自己的目录），执行：
```bash
python3 scripts/import_library.py \
  --input-dir data/books/inbox \
  --recursive \
  --database-url "$DATABASE_URL" \
  --book-type-strategy auto \
  --pdf-section-storage on_demand
```

导入默认会跳过“已审核通过”的同源书（按 `source_path` 匹配），避免重复打回审核。  
如需强制重扫，可加：`--rescan-approved`。

`--pdf-section-storage` 两种模式：
1. `precut`：预切章节 PDF 到 `data/books/derived`（更快，占空间）。
2. `on_demand`：不落章节 PDF，每次阅读从原始 PDF 按页码实时生成（省空间）。

导入时目录处理策略：
1. 若 PDF 含可解析目录（Outline/Bookmarks），会自动标准化并保存目录文件。
2. 若无可用目录，才进入待处理队列（`/app/toc` 人工标注）。
3. 目录记录会绑定书籍 `SHA-256` 校验码与源路径，降低 `book_id` 变化导致的丢失风险。

## 鉴权
- 默认 token：`local-dev-token`
- API 请求头：`Authorization: Bearer <token>`

## 关键 API
1. `GET /health`（包含 `startup_bootstrap` 状态）
2. `GET /v1/feed`
3. `GET /v1/books`
4. `POST /v1/books/import_start`（异步导入，返回 `job_id`）
5. `GET /v1/books/import_job?job_id=<id>`（查询导入进度与结果）
6. `GET /v1/chunk_detail`
7. `GET /v1/chunk_context`
8. `GET /v1/chunk_pdf?book_id=<uuid>&chunk_id=<uuid>`
9. `GET /v1/book_mosaic?book_id=<uuid>&user_id=<uuid>`
10. `POST /v1/interactions`
11. `GET /v1/user/export?user_id=<uuid>&export_dir=<path>`
12. `GET /v1/toc/pending`
13. `POST /v1/toc/preview`
14. `POST /v1/toc/save`
15. `POST /v1/toc/review`（审核状态：`pending_review|approved|rejected`）
16. `POST /v1/toc/write_back`（把当前目录写回原 PDF Outline，并更新校验码）
17. `POST /v1/toc/llm_extract`（目录截图 + 提示词 -> 大模型识别目录文本）
18. `POST /v1/toc/llm_extract_pages`（按目录页段批量调用 LLM 识别）
19. `POST /v1/toc/llm_extract_pages_start`（启动异步批量 LLM 任务，返回 `job_id`）
20. `GET /v1/toc/llm_extract_pages_job?job_id=<id>`（查询批量 LLM 进度/失败页/结果）
21. `GET /v1/toc/llm_config`（读取已保存 LLM 配置）
22. `POST /v1/toc/llm_config`（保存 LLM 配置）
23. `POST /v1/toc/llm_validate`（检测 LLM 配置有效性：鉴权/模型/图像探测）

`GET /v1/feed` 返回 `feed_source`：`postgres` 或 `memory_fallback`。  
当启动导入导致数据库暂时繁忙时，会自动回退 `memory_fallback` 保证前端可用。

`/v1/toc/llm_extract` 支持 OpenAI 兼容接口，参数可在请求体传入：
`llm.base_url`、`llm.model`、`llm.api_key`、`prompt`。  
也支持环境变量默认值：`BOOKFLOW_LLM_TOC_BASE_URL`、`BOOKFLOW_LLM_TOC_MODEL`、`BOOKFLOW_LLM_TOC_API_KEY`。  
LLM 识别结果会落盘到：`data/toc/llm_runs/*.json`（接口返回 `saved_result_file`）。  
批量 LLM 支持重试参数：`max_retries_per_page`、`retry_backoff_ms`，并支持指定 `pages` 仅重试失败页。

## 章节 PDF 产物目录
- `data/books/derived/<book_id>/<chunk_id>.pdf`

## 缓存与用户导出目录
1. 封面缓存（独立于用户数据）：`data/cache/covers`
2. PDF 页面缓存（目录标注台预览）：`data/cache/pages`
3. 用户导出（自动/手动）：`data/users/export`
4. 标准化目录文件：`data/toc/normalized/<book_fingerprint>.json`
5. LLM 配置：`data/toc/llm_config.json`
6. LLM 识别结果归档：`data/toc/llm_runs/*.json`

可预热封面缓存：
```bash
python3 scripts/warm_cover_cache.py --database-url "$DATABASE_URL"
```

## 最小验收
```bash
./scripts/smoke_first_product.sh --base-url http://127.0.0.1:8000 --token local-dev-token
```
