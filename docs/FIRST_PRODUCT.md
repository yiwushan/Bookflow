# BookFlow First Product（v0.1.0）

目标：本地快速得到可用成品（导入 -> Feed -> 章节 PDF 阅读 -> TOC 标注生效）。

## 1. 依赖
```bash
python3 -m pip install --upgrade pip
python3 -m pip install "psycopg[binary]" pypdf beautifulsoup4
docker --version
```

## 2. 一键启动
```bash
./scripts/first_product.sh
```

默认行为：
1. 启动本地 Postgres（migration + seed）。
2. 导入 `data/books/inbox`。
3. 启动 API + 前端。

## 3. 目录与章节物化策略
导入 PDF 时按以下优先级决定切分来源：
1. `PDF Outline/Bookmarks`
2. `manual_toc`（已保存人工目录）
3. `pending_manual_toc`（无目录，进入待处理队列）

章节 PDF 预切目录：
- `data/books/derived/<book_id>/<chunk_id>.pdf`

## 4. 人工目录流程（无 Outline 书籍）
1. 打开 `/app/toc`。
2. 在待处理列表选择书籍。
3. 批量粘贴目录并点击“预览目录定位”。
4. 点击“保存目录标注”。
5. 系统立即执行物化，返回 `materialized_chunks/generated_pdf_count/failed_entries`。

## 5. 最小验收
```bash
./scripts/smoke_first_product.sh --base-url http://127.0.0.1:8000 --token local-dev-token
python3 -m unittest tests.test_pdf_sectioning tests.test_api_contract
```

## 6. 常见问题
1. `toc/save` 返回 `materialized_chunks=0`：检查 `books.source_path` 指向的 PDF 是否存在。
2. Reader 打不开章节 PDF：检查 `data/books/derived/<book_id>/<chunk_id>.pdf` 是否已生成。
3. 无目录书籍未出现在 Feed：这是预期行为，需先在 TOC 台完成人工标注。
