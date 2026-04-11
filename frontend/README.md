# Frontend V0.1.1（简洁重构）

## 启动
1. `python3 server/app.py --host 127.0.0.1 --port 8000`
2. 打开 `http://127.0.0.1:8000/app`
3. 首次会自动跳转登录页 `http://127.0.0.1:8000/app/login`

## 页面
1. `/app`：双列 Feed（上封面下标题）。
说明：顶部支持“导入图书（路径）”“导出用户数据”“查看书库数量”。
2. `/app/reader?book_id=<id>&chunk_id=<id>`：章节阅读页（支持 `pdf_section` 原文 PDF，上一节/下一节跳转）。
3. `/app/book?book_id=<id>&user_id=<id>`：书籍拼图页（已读点亮）。
4. `/app/toc`：人工目录标注台（批量粘贴、预览、保存并物化）。

说明：已移除调试预设、缓存统计面板等开发态信息，界面只保留阅读主路径。

## 交互上报
前端会向 `/v1/interactions` 上报：
- `impression`
- `enter_context`
- `like`
- `unlike`
- `comment`
- `section_complete`
- `backtrack`
- `confusion`

## 鉴权
- 当前为单用户登录模式：
  - 默认用户名：`admin`
  - 默认密码：`bookflow`
- 登录成功后前端会保存会话 token，并自动用于 API 请求。
- 会话按设备绑定（`device_id`），不同设备需要分别登录。
- 默认有效期 7 天（可通过 `BOOKFLOW_AUTH_SESSION_TTL_SEC` 调整）。
- 若需改默认账号密码，可在启动前设置环境变量：
  - `BOOKFLOW_AUTH_USERNAME`
  - `BOOKFLOW_AUTH_PASSWORD`
  - `BOOKFLOW_AUTH_SECRET`（会话签名密钥）
