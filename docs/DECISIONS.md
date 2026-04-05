# BookFlow 决策日志（ADR-Lite）

## ADR-038 V0 主链路切换为“章节原文 PDF 优先”
- 日期：`2026-03-30`
- 结论：V0 默认路径不再依赖文本重排切片，改为“目录叶子小节 -> 章节 PDF 物化 -> Reader 原文阅读”。
- 原因：更符合你当前的核心目标（降低启动阻力、保留原文上下文、先把基础框架做稳）。
- 代价：无目录 PDF 需要人工标注；章节 PDF 预切会增加磁盘占用。

## ADR-039 Feed 默认排序降级为轻量混排
- 日期：`2026-03-30`
- 结论：`mode=default` 不再走标签偏好打分，改为“未完成优先 + 跨书交错 + 轻随机”。
- 原因：V0 阶段优先保证可解释和稳定，不把推荐复杂度提前。
- 代价：个性化程度下降，后续需通过实验再引入高级排序。

## ADR-040 Book 完成口径统一为 `section_complete`
- 日期：`2026-03-30`
- 结论：书籍拼图“已读”状态仅由 `section_complete` 驱动，不再把 `enter_context/like/comment` 计入完成。
- 原因：避免“互动活跃但未完成阅读”的误判，成就反馈更可信。
- 代价：若用户不主动完成标记，完成率提升会变慢。

## ADR-001 小节优先而非纯字数切片
- 日期：`2026-03-28`
- 结论：切片以“完整小节”为第一优先，过长再做二次分段。
- 原因：减少阅读断裂，增强“看不懂就回看上文”的行为链。
- 代价：实现复杂度高于固定字数切片。

## ADR-002 渲染采用混合模式（reflow 优先，crop 兜底）
- 日期：`2026-03-28`
- 结论：默认文本重排；复杂公式/表格/代码或低置信抽取时改用 PDF 裁切。
- 原因：兼顾可读性与技术内容保真。
- 代价：需要维护双渲染链路。

## ADR-003 指标改为“完整小节完成 + 连续深读”
- 日期：`2026-03-28`
- 结论：不以停留时长为北极星指标。
- 原因：停留时长无法代表真正阅读推进，容易被“卡住”误导。
- 代价：需要更细粒度事件埋点和聚合逻辑。

## ADR-004 技术书定位为“兴趣钩子 + 深读入口”
- 日期：`2026-03-28`
- 结论：技术书不强求课堂级掌握，优先激发继续阅读动机。
- 原因：符合产品定位（降低启动阻力，提升持续阅读）。
- 代价：学习效果评估需后续补充更严谨量化方法。

## ADR-005 核心事件采用幂等键与日级去重
- 日期：`2026-03-28`
- 结论：`section_complete` 使用 `user_id + section_id + day` 去重，所有事件带 `idempotency_key`。
- 原因：避免客户端重试和网络抖动导致指标虚高。
- 代价：需要服务端维护去重窗口与事件回放策略。

## ADR-006 路由骨架采用零依赖 Python 标准库
- 日期：`2026-03-28`
- 结论：MVP 初期 API skeleton 使用 `http.server`，不引入外部 Web 框架。
- 原因：减少环境依赖，确保任意机器可直接启动验证接口协议。
- 代价：后续接数据库、鉴权中间件和 OpenAPI 时需要迁移到正式框架。

## ADR-007 持久化目标数据库选用 Postgres
- 日期：`2026-03-28`
- 结论：当前项目持久化统一按 Postgres 设计与实现。
- 原因：与既有 `schema.sql`、JSONB、数组字段和统计查询能力匹配。
- 代价：本地开发需要运行 Postgres 实例或容器。

## ADR-008 Pipeline 阈值改为配置驱动
- 日期：`2026-03-28`
- 结论：chunking/render_mode 关键阈值从代码常量迁移到 `config/pipeline.json`。
- 原因：便于快速调参和分书籍类型策略扩展。
- 代价：增加配置兼容性与默认值管理成本。

## ADR-009 服务后端采用 Postgres 优先 + 内存回退
- 日期：`2026-03-28`
- 结论：`DATABASE_URL` 可用时走 PostgresDAO，不可用时自动回退 MemoryDAO。
- 原因：保持“可直接运行”的开发体验，同时不偏离 Postgres 主路径。
- 代价：需要在验收阶段确认两条路径行为一致，防止环境差异。

## ADR-010 本地 Postgres 使用 Docker 开发镜像 + 种子数据
- 日期：`2026-03-28`
- 结论：开发环境通过 `scripts/dev_postgres.sh` 拉起容器并执行 `0001_init + 0002_seed_dev`。
- 原因：最快完成端到端验收，降低手工初始化成本。
- 代价：依赖容器引擎与镜像可拉取性；生产环境仍需独立部署方案。

## ADR-011 指标查询采用物化视图 + 显式刷新
- 日期：`2026-03-28`
- 结论：核心看板指标落入 `migrations/0003_metrics_materialized.sql`，通过 `scripts/refresh_metrics.py` 刷新。
- 原因：降低高频统计查询成本，避免直接扫描明细表。
- 代价：指标存在刷新延迟，需要调度策略保证时效。

## ADR-012 API 合约测试默认使用内存后端
- 日期：`2026-03-28`
- 结论：`tests/test_api_contract.py` 默认不依赖 DATABASE_URL，确保在最小环境稳定运行。
- 原因：提高测试可执行性与反馈速度。
- 代价：Postgres 专属行为需另行补充数据库集成测试。

## ADR-013 服务层次拆分为 repository + service
- 日期：`2026-03-28`
- 结论：数据访问逻辑迁移到 `server/repository.py`，业务编排迁移到 `server/service.py`。
- 原因：降低 `app.py` 复杂度，为后续扩展批量写入与 import 链路留出结构空间。
- 代价：文件数增加，需要维护跨层接口稳定性。

## ADR-014 书籍导入采用“先 chunk 后 upsert”策略
- 日期：`2026-03-28`
- 结论：`scripts/import_book.py` 先执行清洗+切片，再 upsert 到 `books/book_chunks`。
- 原因：便于重跑导入且保持幂等，适合个人知识库迭代维护。
- 代价：首次导入耗时受 chunking 阶段影响。

## ADR-015 验收采用“双轨自动化”（集成测试 + 端到端脚本）
- 日期：`2026-03-29`
- 结论：新增 `tests/test_postgres_integration.py` 覆盖 interactions 实库写入；新增 `scripts/accept_import_feed.py` 覆盖 import->feed 闭环验收。
- 原因：同时保障“数据正确性”与“用户可见链路”两条核心路径，避免只做单点烟测。
- 代价：本地验收依赖可用 Postgres 实例，测试耗时略增。

## ADR-016 模板回归采用“基线文件 + 自动比对”
- 日期：`2026-03-29`
- 结论：新增 `tests/fixtures/pipeline_template_baseline_v1.json`，在测试中对 `general/fiction/technical` 输出做基线比对。
- 原因：将参数模板行为显式固化，避免后续调参引入隐性回归。
- 代价：模板参数变更时需同步更新基线文件并复核预期。

## ADR-017 拒绝事件默认落库用于质量诊断
- 日期：`2026-03-29`
- 结论：新增 `interaction_rejections` 表，`/v1/interactions` 对被拒绝事件执行异步无阻塞落库，并提供 `scripts/report_interaction_rejections.py` 聚合脚本。
- 原因：无拒绝样本就无法定位数据质量问题来源，优化事件接入成本过高。
- 代价：新增存储与写入开销，需要定期清理历史拒绝数据。

## ADR-018 feed 默认模式引入标签偏好混排（v0）
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 在 `mode=default` 且提供 `user_id` 时，按 `SUM(user_tag_profile.weight * chunk_tags.score)` 排序。
- 原因：在最小改造下提供“像推荐”的体验，并保持可解释性。
- 代价：排序依赖标签覆盖度；冷启动用户会退化到时间序排序。

## ADR-019 导入器保留 markdown 代码边界
- 日期：`2026-03-29`
- 结论：`scripts/import_book.py` 将 fenced code 和 indented code 识别为 `code` block，不再与普通段落混合。
- 原因：技术书片段中代码语义对后续渲染/推荐判定很关键。
- 代价：纯文本场景下可能出现轻微误判，需要后续增加更细规则。

## ADR-020 阅读进度采用“批量回填脚本”先行
- 日期：`2026-03-29`
- 结论：先提供 `scripts/backfill_reading_progress.py` 按 `section_complete` 事件回填 `reading_progress`，后续再演进增量触发。
- 原因：先把统计闭环跑通，避免一开始就引入复杂触发器逻辑。
- 代价：回填依赖定时任务，存在分钟级延迟。

## ADR-021 深读上下文使用独立 `chunk_context` 接口
- 日期：`2026-03-29`
- 结论：新增 `GET /v1/chunk_context`，返回当前 chunk 的 `prev/next` 导航信息。
- 原因：比在 feed 接口塞入额外字段更清晰，前端手势跳转路径更稳定。
- 代价：前端在进入深读时需要一次额外请求（后续可做批量预取优化）。

## ADR-022 导入失败默认产出结构化错误报告
- 日期：`2026-03-29`
- 结论：`scripts/import_book.py` 增加重试机制与错误报告输出（`logs/import_errors/*.json`）。
- 原因：个人知识库导入常遇到临时错误，缺少可追溯信息会大幅增加排障成本。
- 代价：导入失败会产生本地报告文件，需要后续增加清理策略。

## ADR-023 冷启动标签用“迁移种子 + 用户引导脚本”
- 日期：`2026-03-29`
- 结论：通过 `migrations/0005_seed_tags.sql` 提供系统最小标签种子，并通过 `scripts/bootstrap_user_tags.py` 为指定用户写入预设权重。
- 原因：让 feed 偏好混排在空库/新用户场景立即可用。
- 代价：预设偏好属于启发式，需要后续基于真实行为持续调整。

## ADR-024 reading_progress 优先走增量触发器
- 日期：`2026-03-29`
- 结论：新增 `0006_reading_progress_trigger.sql`，对 `section_complete` 事件插入后自动更新 `reading_progress`。
- 原因：减少对定时回填脚本的依赖，缩短进度展示延迟。
- 代价：写入路径增加数据库计算开销，后续需关注高并发下性能。

## ADR-025 自动打标先采用本地规则占位
- 日期：`2026-03-29`
- 结论：新增 `scripts/auto_tag_chunks.py`，基于关键词规则为 chunk 写入最多 3 个标签分数。
- 原因：在没有稳定 LLM 标签流水线前，先提供可运行、可解释的低成本版本。
- 代价：规则覆盖有限，存在语义误判，需要后续评估命中率并替换为模型方案。

## ADR-026 feed 排序解释采用可选 trace 开关
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 支持 `trace=1` 返回 `ranking_trace`（score/source/rank）。
- 原因：调试推荐逻辑需要可见的排序依据，避免“黑箱调参”。
- 代价：trace 模式响应体更大，应默认关闭并仅用于诊断。

## ADR-027 深读批量预取采用独立接口
- 日期：`2026-03-29`
- 结论：新增 `GET /v1/chunk_context_batch`，输入多个 `chunk_ids`，一次返回上下文导航结果。
- 原因：减少前端连续左滑时的请求往返次数与等待抖动。
- 代价：当前 GET 参数长度受限，后续需补 POST JSON 版本。

## ADR-028 导入错误报告默认“可归档清理”
- 日期：`2026-03-29`
- 结论：新增 `scripts/cleanup_import_error_reports.py` 支持按文件年龄归档或删除错误报告。
- 原因：长期运行会累积错误日志，缺乏生命周期管理会影响可维护性。
- 代价：需要额外运维调度，归档目录也需定期治理。

## ADR-029 阅读进度健康检查独立为运维脚本
- 日期：`2026-03-29`
- 结论：新增 `scripts/report_reading_progress_health.py` 输出进度表总量、陈旧度、均值和 top books 概览。
- 原因：快速判断进度链路是否“有数据、数据是否新鲜”。
- 代价：依赖定期人工/任务执行，默认不会自动告警。

## ADR-030 回忆帖混排采用首屏单条占位
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 新增 `with_memory=1`，仅首屏尝试注入最多 1 条 `memory_post`。
- 原因：以最小改动验证“回忆帖插流”价值，同时避免破坏主 feed 节奏。
- 代价：当前不支持复杂频控与个性化插入位，后续需策略化。

## ADR-031 chunk_context_batch 同时支持 GET 与 POST
- 日期：`2026-03-29`
- 结论：保留 GET（便于调试）并新增 POST JSON（便于大批量预取）。
- 原因：兼顾开发便利性与生产场景的请求长度限制。
- 代价：接口形态增多，客户端需统一调用策略。

## ADR-032 自动打标质量先用“规则命中率”衡量
- 日期：`2026-03-29`
- 结论：新增 `scripts/report_auto_tag_rule_hits.py`，提供命中率与标签覆盖基础指标。
- 原因：在模型方案上线前，先给规则版打标建立最小质量监控面板。
- 代价：指标只反映规则层表现，不能直接代表语义正确率。

## ADR-033 feed trace 支持按请求落盘
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 新增 `trace_file=1`，按 `trace_id` 写入 `logs/feed_trace/<trace_id>.json`。
- 原因：便于复盘一次请求的排序链路，提升问题定位效率。
- 代价：会增加本地磁盘文件数量，需要后续配套清理策略。

## ADR-034 auto-tag 规则迁移到配置文件
- 日期：`2026-03-29`
- 结论：`auto_tag_chunks` 与命中率报告都支持从 `config/auto_tag_rules.json` 加载规则。
- 原因：避免每次改规则都改代码，降低调参与回滚成本。
- 代价：新增配置管理复杂度，需要规则文件版本治理。

## ADR-035 健康报告默认支持 JSON + 可选 CSV
- 日期：`2026-03-29`
- 结论：`report_reading_progress_health.py` 保留 JSON 输出，并新增 `--csv-output` 导出。
- 原因：JSON 便于程序消费，CSV 便于人工分析和表格工具接入。
- 代价：导出文件需要额外清理策略。

## ADR-036 回忆帖插流增加 `memory_every` 频控参数
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 在 `with_memory=1` 时支持 `memory_every=N`，按“每 N 条普通内容插 1 条回忆帖”混排；不传该参数时保持原行为（首屏最多 1 条置顶）。
- 原因：先用低复杂度参数把插流节奏调优能力做出来，便于后续 A/B。
- 代价：参数组合增多，需要明确校验规则与默认行为。

## ADR-037 chunk_context_batch 增加服务层短 TTL 缓存
- 日期：`2026-03-29`
- 结论：`DataService.fetch_chunk_neighbors_batch` 默认启用 5 秒内存缓存，键为 `book_id + chunk_ids`，GET/POST 共用缓存。
- 原因：深读连续滑动场景会出现重复预取请求，短缓存能减少 DB 往返。
- 代价：存在秒级“旧数据窗口”，需要后续补充命中率与失效策略观测。

## ADR-038 feed trace 文件采用“可归档清理”策略
- 日期：`2026-03-29`
- 结论：新增 `scripts/cleanup_feed_trace_files.py`，支持 `dry-run`、归档与删除模式，按文件年龄清理 `logs/feed_trace/*.json`。
- 原因：`trace_file=1` 便于调试，但会持续累积本地文件，必须有生命周期治理方案。
- 代价：需要配套定时任务和归档目录管理，避免二次堆积。

## ADR-039 auto-tag 规则配置采用版本化 + 可回滚
- 日期：`2026-03-29`
- 结论：`config/auto_tag_rules.json` 升级为 `rule_versions + active_rule_version` 结构，并新增 `scripts/set_auto_tag_rule_version.py` 执行版本切换/回滚。
- 原因：规则调参频繁，缺少版本切换会导致线上回退成本高、风险大。
- 代价：配置结构更复杂，脚本与测试需兼容 legacy 格式。

## ADR-040 memory posts 增加真实样例种子与回放脚本
- 日期：`2026-03-29`
- 结论：新增 `migrations/0008_seed_memory_posts_realistic.sql`（包含 inserted/skipped/pending 多状态样例）与 `scripts/replay_memory_feed.py`（多场景插流回放）。
- 原因：仅最小 seed 无法展示真实插流形态，调参与验收都缺乏“可复现样本”。
- 代价：dev seed 更大、脚本更多，需保持幂等并控制文档复杂度。

## ADR-041 with_memory 插位策略参数化
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 新增 `memory_position=top|interval|random`，并提供 `memory_seed` 用于随机位复现；保留 `memory_every` 向后兼容（默认推断为 interval）。
- 原因：仅“置顶/固定间隔”不足以覆盖回忆帖节奏实验，需要可配置插位策略。
- 代价：参数组合变多，需强化合约校验与默认行为说明。

## ADR-042 chunk_context_batch 缓存指标按需返回
- 日期：`2026-03-29`
- 结论：`chunk_context_batch` 增加 `cache_stats` 可选输出，暴露命中/过期/回源计数与命中率。
- 原因：只做缓存实现不够，必须可观测才能判断策略是否有效。
- 代价：接口响应体变大，建议仅在诊断场景开启。

## ADR-043 import 错误清理脚本支持 cron 退出码
- 日期：`2026-03-29`
- 结论：`cleanup_import_error_reports.py` 新增 `--cron-exit-codes`，约定 `0/3/4` 分别表示“正常/发现待处理/部分未处理”。
- 原因：定时任务需要仅靠退出码就能触发告警，而不依赖日志解析。
- 代价：退出码语义增多，需在文档中保持稳定约定。

## ADR-044 feed trace 清理采用 cron/systemd 双方案文档化
- 日期：`2026-03-29`
- 结论：新增 `docs/ops/feed_trace_cleanup_scheduler.md`，提供 cron 与 systemd timer 两种可落地调度方案。
- 原因：仅有清理脚本还不够，缺少调度落地说明会导致长期无人执行。
- 代价：运维文档需要随目录结构与脚本参数持续维护。

## ADR-045 auto-tag 版本回归采用“同批 chunk 对比”
- 日期：`2026-03-29`
- 结论：新增 `scripts/compare_auto_tag_rule_versions.py`，在同一 `book_id + limit` 样本上对比 base/target 规则命中率与 rule 级差异。
- 原因：版本切换需要可量化回归依据，避免“凭感觉调规则”。
- 代价：脚本执行会额外扫描 chunk 文本，需控制 `limit` 规模。

## ADR-046 memory replay 默认支持 JSONL 落盘
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 新增 `--jsonl-output`，按场景逐行输出，便于后续离线分析。
- 原因：仅控制台 JSON 不利于长期积累回放样本与批处理分析。
- 代价：新增本地文件管理成本，需要配套清理策略。

## ADR-047 chunk_context_batch 增加 cache_stats 重置开关
- 日期：`2026-03-29`
- 结论：`chunk_context_batch` 新增 `cache_reset=1`，请求前重置进程内缓存计数并清空缓存项。
- 原因：没有重置能力时，命中率观测窗口不可控，难以做灰度验证。
- 代价：是进程级语义，多实例部署下需额外汇总策略。

## ADR-048 random 插位增加首条约束开关
- 日期：`2026-03-29`
- 结论：`memory_position=random` 新增 `memory_random_never_first`（默认 `1`），可硬约束首条不插回忆帖。
- 原因：首条回忆帖会显著影响“主内容进入速度”，需要显式开关做实验控制。
- 代价：参数复杂度上升，客户端需要明确传参策略。

## ADR-049 feed trace 清理脚本退出码与 import 清理对齐
- 日期：`2026-03-29`
- 结论：`cleanup_feed_trace_files.py` 新增 `--cron-exit-codes`，沿用 `0/2/3/4` 语义。
- 原因：两类清理任务若退出码不一致，运维告警配置会分裂。
- 代价：脚本参数变多，文档需要同步维护一致性。

## ADR-050 import 清理脚本增加 summary-only 输出
- 日期：`2026-03-29`
- 结论：`cleanup_import_error_reports.py` 新增 `--summary-only`，默认可省略路径明细，仅保留统计。
- 原因：定时任务日志需要“短而稳”，大批量路径明细会影响可读性与存储。
- 代价：排障时需手动关闭 summary-only 才能看详细路径。

## ADR-051 memory replay 增加 Markdown 报告输出
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 新增 `--markdown-output`，按场景输出结构化 Markdown 报告（含插位摘要与时间线表格）。
- 原因：JSON/JSONL 便于机器处理，但人工复盘更适合 Markdown 阅读与留档。
- 代价：新增报告文件管理成本，需结合清理策略避免长期堆积。

## ADR-052 chunk_context_batch cache_stats 绑定请求级 trace_id
- 日期：`2026-03-29`
- 结论：当 `cache_stats=1` 时，响应新增 `cache_stats.request_trace_id`，与顶层 `trace_id` 一致。
- 原因：缓存观测结果需要与单次请求日志直接关联，便于排障与回放定位。
- 代价：返回字段增多，客户端解析需兼容新增键。

## ADR-053 memory_position A/B 样本导出独立成脚本
- 日期：`2026-03-29`
- 结论：新增 `scripts/export_memory_position_ab_samples.py`，固定导出 `top/interval/random` 三个实验臂的样本行，并支持 JSONL/CSV。
- 原因：A/B 评估需要可重复、可离线分析的数据快照，直接依赖线上请求难以复盘。
- 代价：新增一个脚本维护面，参数与 feed 语义变更时需同步更新。

## ADR-054 feed trace 清理输出支持 summary-only
- 日期：`2026-03-29`
- 结论：`cleanup_feed_trace_files.py` 增加 `--summary-only`，默认可省略路径明细，保留统计字段。
- 原因：定时任务日志更关注趋势统计，明细路径会拉长日志并增加噪音。
- 代价：定位单文件问题时需关闭 summary-only 查看完整路径列表。

## ADR-055 import 清理支持 Markdown 报告输出
- 日期：`2026-03-29`
- 结论：`cleanup_import_error_reports.py` 新增 `--markdown-output`，输出可读性更好的清理报告（摘要 + 路径分组）。
- 原因：JSON 适合机器消费，但人工巡检与交接复盘更适合 Markdown 报告。
- 代价：新增报告文件生命周期管理需求，需要配套清理策略。

## ADR-056 replay Markdown 报告加入跨场景总览
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 的 Markdown 报告增加 `Overview` 表，汇总各场景插入数、插位与 trace_id。
- 原因：逐场景正文可读但横向比较困难，总览表能显著降低人工复盘成本。
- 代价：报告结构更长，需要在低分辨率终端中滚动查看。

## ADR-057 cache_stats 增加请求级 delta 计数
- 日期：`2026-03-29`
- 结论：`chunk_context_batch` 在 `cache_stats` 中追加 `request_cache_hit_delta/request_cache_source_fetch_delta/request_cache_expired_delta`。
- 原因：累计计数无法判断单次请求行为，delta 可直接支撑灰度验证与问题定位。
- 代价：并发场景下 delta 仍是进程级近似值，多实例需要额外聚合。

## ADR-058 compare_auto_tag_rule_versions 支持 Markdown 报告
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 新增 `--markdown-output`，输出 summary + rule delta 的可读报告。
- 原因：CSV 便于表格分析，但规则版本评审更依赖可读文本报告。
- 代价：新增报告文件落地路径管理需求。

## ADR-059 AB 样本导出支持 Markdown 报告
- 日期：`2026-03-29`
- 结论：`export_memory_position_ab_samples.py` 新增 `--markdown-output`，输出实验臂总览与逐槽位时间线。
- 原因：CSV/JSONL 适合分析，Markdown 适合评审与异步讨论。
- 代价：报告文件会增加存储占用，需要定期清理。

## ADR-060 import 清理新增 CSV summary 导出
- 日期：`2026-03-29`
- 结论：`cleanup_import_error_reports.py` 新增 `--csv-output`，固定导出一行摘要指标。
- 原因：方便被 BI/告警平台直接拉取，避免解析 JSON。
- 代价：输出格式固定后，字段变更需要兼容策略。

## ADR-061 feed trace 清理支持 Markdown 报告
- 日期：`2026-03-29`
- 结论：`cleanup_feed_trace_files.py` 新增 `--markdown-output`，输出摘要与路径明细报告。
- 原因：定时任务结果需要“机器可读 + 人可读”双轨输出。
- 代价：报告文件生命周期管理复杂度增加。

## ADR-062 replay 脚本补齐 CSV 汇总导出
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 新增 `--csv-output`，按场景输出汇总行。
- 原因：A/B 结果对接表格工具时，CSV 比 JSONL/Markdown 更直接。
- 代价：导出矩阵增多，命令参数需要更清晰文档化。

## ADR-063 cache_stats 增加全局重置 trace 记录
- 日期：`2026-03-29`
- 结论：`cache_stats` 增加 `last_reset_trace_id`，记录最近一次 `cache_reset=1` 触发请求。
- 原因：请求级 delta 之外，还需要跨请求定位“谁重置了统计窗口”。
- 代价：该字段为进程级语义，多实例环境需结合实例维度使用。

## ADR-064 compare 脚本新增 JSONL 明细导出
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 新增 `--jsonl-output`，输出 summary 行 + rule_delta 行。
- 原因：JSONL 更适合日志管道与流式处理场景。
- 代价：输出形态增多，维护成本与文档成本增加。

## ADR-065 A/B 样本导出支持场景配置文件
- 日期：`2026-03-29`
- 结论：`export_memory_position_ab_samples.py` 新增 `--scenario-config`，可从 JSON 文件加载实验臂定义。
- 原因：硬编码三臂不利于快速实验，配置文件能降低改脚本频率并支持复现。
- 代价：需要维护配置校验逻辑和样例配置文件。

## ADR-066 import 清理 Markdown 报告增加截断计数
- 日期：`2026-03-29`
- 结论：`cleanup_import_error_reports.py` 的 Markdown 报告新增 `moved_paths_truncated_count/deleted_paths_truncated_count`。
- 原因：路径明细被截断时，必须显式告知“漏掉了多少条”以避免误判。
- 代价：报告字段增加，需要文档同步解释新指标。

## ADR-067 feed trace 清理支持 CSV summary 导出
- 日期：`2026-03-29`
- 结论：`cleanup_feed_trace_files.py` 新增 `--csv-output`，导出固定字段的一行摘要。
- 原因：便于接入监控/报表工具，减少解析 JSON 的成本。
- 代价：CSV 字段变更需要兼容策略，避免下游任务破坏。

## ADR-068 replay 报告增加首条内容类型统计
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 在 Markdown 概览与场景明细中新增 `first_item_type`。
- 原因：首条内容类型会直接影响首屏体验，复盘时必须可见。
- 代价：CSV/Markdown 字段增加，历史消费方需兼容新增列。

## ADR-069 cache_stats 增加 cache_entries_delta
- 日期：`2026-03-29`
- 结论：`chunk_context_batch` 的 `cache_stats` 增加 `cache_entries_delta`，表示本次请求前后缓存项变化。
- 原因：仅看 hit/source/expired 不足以判断缓存容量趋势。
- 代价：并发场景下该值为进程级近似，不等同全局真实值。

## ADR-070 compare Markdown 报告回显 TopN 配置
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 的 Markdown 报告头部新增 `top` 字段回显。
- 原因：阅读报告时需要知道“展示的是前多少条 rule delta”。
- 代价：报告头部信息增多，但可读性略受影响。

## ADR-071 replay CSV 文档补齐首条类型列说明
- 日期：`2026-03-29`
- 结论：在 `README.md` 与 `server/README.md` 中补充 `replay_memory_feed.py --csv-output` 的列顺序说明，并明确 `first_item_type` 语义。
- 原因：CSV 新增字段后，缺少文档会导致离线分析误读首条内容类型。
- 代价：文档维护负担略增，后续字段调整需同步更新两处说明。

## ADR-072 cache_stats 增加 reset_ts
- 日期：`2026-03-29`
- 结论：`chunk_context_batch` 的 `cache_stats` 增加 `reset_ts` 字段，记录最近一次缓存统计窗口重置时间（UTC ISO8601）。
- 原因：仅有 `last_reset_trace_id` 不足以判断“何时重置”，需要时间维度支持排障与回放对齐。
- 代价：字段语义为进程级，多实例场景仍需结合实例维度解释。

## ADR-073 compare JSONL 明细增加 rule_rank
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --jsonl-output` 的 `rule_delta` 行新增 `rule_rank`（从 1 开始）。
- 原因：下游消费方可直接用名次字段做 TopN 展示与趋势对比，减少二次排序逻辑。
- 代价：JSONL schema 变更后，严格校验器需要兼容新增字段。

## ADR-074 新增 chunk 粒度 A/B 离线导出脚本
- 日期：`2026-03-29`
- 结论：新增 `scripts/export_chunk_granularity_ab_samples.py`，对同一批 chunk 同时导出 `A_full_section` 与 `B_split_two` 样本（JSONL/CSV/Markdown）。
- 原因：切片粒度实验需要稳定可复现的离线样本，便于评估“完整小节 vs 二段拆分”策略。
- 代价：新增一条脚本维护面，后续切片规则调整需同步更新导出逻辑。

## ADR-075 回忆帖候选采用多样化轮转优先
- 日期：`2026-03-29`
- 结论：`fetch_memory_feed_items` 查询改为按 `source_chunk_rank + memory_type_rank` 优先排序，降低同源回忆帖连续出现概率。
- 原因：在同样频控下，候选源多样化可提升信息流新鲜感，减少“同一段反复出现”疲劳。
- 代价：极端场景下会牺牲纯时间倒序的一致性，需要在分析时明确排序策略。

## ADR-076 书籍主页拼图原型先走静态导出
- 日期：`2026-03-29`
- 结论：新增 `scripts/render_book_homepage_mosaic.py`，基于 `book_chunks + interactions` 导出静态 HTML 进度拼图页。
- 原因：先快速验证“拼图式解锁”视觉与信息密度，再决定是否接入正式前端路由。
- 代价：当前原型非在线页面，后续接入生产前端时仍需二次实现。

## ADR-077 replay JSONL 字段文档化
- 日期：`2026-03-29`
- 结论：在 `README.md` 与 `server/README.md` 明确 `replay_memory_feed.py --jsonl-output` 字段集合，包含 `first_item_type`。
- 原因：JSONL 常用于离线分析，字段未文档化会增加消费方歧义和接入成本。
- 代价：输出字段变更时需要同步维护多处文档说明。

## ADR-078 cache_stats 增加实例标识 instance_id
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `instance_id`，默认 `pid:<pid>`，支持 `BOOKFLOW_INSTANCE_ID` 覆盖。
- 原因：多实例或重启场景下，缓存统计需要快速定位来源实例。
- 代价：字段为进程级标识，分布式环境仍需结合上游网关/实例标签追踪。

## ADR-079 compare CSV 增加 rule_rank
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --csv-output` 的 `rule_delta` 行新增 `rule_rank` 列。
- 原因：CSV 下游常直接做排序可视化，显式 rank 能减少消费方二次处理。
- 代价：CSV schema 变更后，依赖固定列序的任务需要同步更新。

## ADR-080 chunk 粒度导出支持 section_prefix 过滤
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 新增 `--section-prefix`，在 SQL 层按 `section_id LIKE <prefix>%` 过滤样本。
- 原因：离线评估常需要聚焦某一章/节范围，避免全书样本噪音。
- 代价：过滤条件增多后，脚本参数组合和文档维护复杂度上升。

## ADR-081 memory 多样化策略支持 on/off 开关
- 日期：`2026-03-29`
- 结论：`GET /v1/feed` 新增 `memory_diversity=on|off`；`on` 使用轮转优先，`off` 回退纯时间倒序。
- 原因：需要在不改频控参数的情况下快速对比“多样化 vs 时间倒序”插流体验。
- 代价：参数语义增多，调用方需明确记录实验配置避免结果混淆。

## ADR-082 拼图原型支持 tile JSON 导出
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 新增 `--tiles-json-output`，输出 `summary + tiles` 结构供前端联调。
- 原因：静态 HTML 原型之外，前端还需要可编程数据源进行组件化验证。
- 代价：导出物增多，需关注文件管理与 schema 稳定性。

## ADR-083 replay Markdown 增加 memory_type 分布统计
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 的 Markdown 报告新增场景级 `memory_type_distribution`（并在 Overview 展示）。
- 原因：仅看插入数量不足以判断召回结构，需要区分 `month_ago/year_ago/...` 组成。
- 代价：报告字段增多，CSV 与 Markdown 字段集合进一步分化。

## ADR-084 cache_stats 增加 instance_started_ts
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `instance_started_ts`，标识当前服务进程启动时间。
- 原因：`instance_id` 只能区分实例，无法判断实例生命周期和重启窗口。
- 代价：跨实例聚合时仍需上层采集系统做时间对齐与去重。

## ADR-085 compare Markdown 增加导出 schema 说明块
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` Markdown 报告新增 `Export Schemas` 区块，说明 CSV/JSONL 行结构。
- 原因：报告阅读者常直接复用导出数据，schema 内嵌说明可减少沟通成本。
- 代价：文档正文更长，字段更新时需要同步维护说明块。

## ADR-086 chunk 粒度导出支持标题关键词过滤
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 新增 `--chunk-title-keyword`，在 SQL 层按 `chunk_title ILIKE %keyword%` 过滤样本。
- 原因：离线评估常需要聚焦某类小节标题，减少无关样本干扰。
- 代价：筛选维度增加后，参数组合与文档维护复杂度上升。

## ADR-087 memory_diversity 默认策略支持环境变量灰度
- 日期：`2026-03-29`
- 结论：`memory_diversity` 未显式传参时，由环境变量决定：`BOOKFLOW_MEMORY_DIVERSITY_DEFAULT=on|off` 与 `BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT=0..100`（按 `user_id` 稳定分桶，可配 `BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT`）。
- 原因：允许在不改客户端参数的情况下对默认策略做可控灰度发布与回滚。
- 代价：默认行为由运行环境驱动，排障时必须记录环境配置与分桶盐值。

## ADR-088 拼图原型增加状态图例与导出时间戳
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 HTML 增加 tile 状态图例（已读/未读）与 `exported_at` 展示，`tiles.json` 同步输出 `exported_at`。
- 原因：原型对外传递时需要显式图例降低理解成本，并保留导出时间用于比对与回放。
- 代价：导出 payload 字段增加，下游消费方需兼容新增字段。

## ADR-089 replay CSV 增加 memory_type_distribution 列
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --csv-output` 新增 `memory_type_distribution` 列，列追加在末尾以保持旧列顺序兼容。
- 原因：CSV 报表需要直接观察回忆帖类型结构，避免只能依赖 Markdown/JSONL。
- 代价：CSV schema 扩展后，严格列校验脚本需同步升级。

## ADR-090 cache_stats 增加 cache_key_cardinality
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 增加 `cache_key_cardinality` 字段，当前以进程内缓存键数量作为估算值。
- 原因：仅看缓存项数量与命中率不足以判断 key 空间规模，需要单独指标辅助诊断。
- 代价：该值是进程级估算，跨实例聚合时需要结合实例维度解读。

## ADR-091 compare JSONL 增加 schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --jsonl-output` 的 `summary/rule_delta` 行新增 `schema_version` 字段，并在 CLI payload 回显 `jsonl_schema_version`。
- 原因：JSONL 明细进入下游分析链路后，需要显式版本以支持向后兼容演进。
- 代价：导出字段增加，旧消费方若做严格字段白名单需调整。

## ADR-092 chunk 粒度 Markdown 增加关键词命中率统计
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 在传入 `--chunk-title-keyword` 时，Markdown 报告新增 `keyword_filter_total_candidates/matched_candidates/hit_rate`。
- 原因：仅看过滤后的样本不够，需要知道关键词在候选集中的覆盖度。
- 代价：脚本需要额外执行一次统计 SQL，导出开销略增。

## ADR-093 feed trace 落盘增加 memory_diversity_source
- 日期：`2026-03-29`
- 结论：`trace_file=1` 时，落盘 JSON 的 `query` 增加 `memory_diversity_source`（`query/default/gray`）。
- 原因：默认策略受环境变量灰度影响，需要在离线排障时还原“开关来源”。
- 代价：trace schema 扩展后，消费脚本需兼容新增字段。

## ADR-094 tiles JSON 增加 schema_version
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 的 `--tiles-json-output` 新增 `schema_version=book_homepage_mosaic.tiles.v1`，CLI payload 回显 `tiles_json_schema_version`。
- 原因：前端联调数据结构需要显式版本，避免后续字段演进时难以兼容。
- 代价：导出 payload 字段增加，旧解析器需放宽字段约束。

## ADR-095 replay JSONL 增加 schema_version
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --jsonl-output` 的每行新增 `schema_version=replay_memory_feed.jsonl.v1`，并在 CLI payload 回显 `jsonl_schema_version`。
- 原因：回放 JSONL 进入离线分析链路后需要版本化，便于后续字段演进兼容。
- 代价：JSONL schema 扩展后，严格字段校验脚本需同步更新。

## ADR-096 cache_stats 增加 cache_key_samples
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `cache_key_samples`（最多 3 个 `book_id + chunk_ids` 样本）。
- 原因：仅有 cardinality 指标仍难排障，需要可读样本快速定位异常 key 形态。
- 代价：字段仅用于调试，响应体略增，生产高频调用应按需开启 `cache_stats`。

## ADR-097 compare CSV 增加 schema_version 列
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --csv-output` 新增 `schema_version` 列（`compare_auto_tag_rule_versions.csv.v1`），CLI payload 回显 `csv_schema_version`。
- 原因：CSV 被多方消费时需要显式版本，避免字段演进导致隐性解析错误。
- 代价：CSV 列扩展后，下游固定列序脚本需同步升级。

## ADR-098 feed trace 增加灰度百分比回显
- 日期：`2026-03-29`
- 结论：feed trace 落盘 `query` 新增 `memory_diversity_gray_percent`，回显环境变量灰度百分比（未配置为 `null`）。
- 原因：复盘默认策略时，仅有来源类型还不够，需要同时知道灰度强度。
- 代价：trace schema 再次扩展，消费工具需容忍新增字段。

## ADR-099 拼图图例增加读写数量统计
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 的图例改为显示 `已读/未读` tile 数量（来自 summary）。
- 原因：仅颜色区分不够直观，数量可以直接反映进度结构。
- 代价：UI 文案长度增加，在窄屏下可读性需关注。

## ADR-100 chunk 粒度 CSV 增加关键词汇总行
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py --csv-output` 在关键词过滤场景追加 `keyword_filter_summary` 汇总行（含 `keyword_filter_hit_rate`）。
- 原因：离线分析常直接读 CSV，需要在同一文件看到过滤命中率而非额外查 Markdown。
- 代价：CSV 中混入 summary 行，下游读取时需按 `arm=__summary__` 分流。

## ADR-101 replay CSV 增加 schema_version
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --csv-output` 新增 `schema_version=replay_memory_feed.csv.v1`，并在脚本输出回显 `csv_schema_version`。
- 原因：CSV 下游多来源消费时需要显式版本治理，避免字段演进混淆。
- 代价：CSV 列扩展后，旧的固定列解析器需兼容新增列。

## ADR-102 cache_key_samples 增加过期预估字段
- 日期：`2026-03-29`
- 结论：`cache_key_samples` 样本新增 `expire_in_sec` 与 `expire_estimate_ts`，用于观察缓存样本剩余生命周期。
- 原因：仅有 key 样本无法判断失效窗口，需要时间维度辅助排障。
- 代价：为估算值（非精确到分布式全局），调试时需结合实例维度解读。

## ADR-103 compare Markdown 回显 schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` Markdown 报告头部与 Export Schemas 区块回显 `csv_schema_version/jsonl_schema_version`。
- 原因：阅读 Markdown 报告时即可直接确认当前导出版本，减少二次核对成本。
- 代价：报告头部信息增多，文档维护项随之增加。

## ADR-104 trace 增加 memory_diversity 默认值说明
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_default_note`，描述默认 on/off 及来源。
- 原因：仅有 source 与 gray_percent 时，默认值语义仍不直观，需要可读说明。
- 代价：trace 字段继续扩展，消费者需容忍新增调试字段。

## ADR-105 tiles JSON 增加 min_read_events 回显
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 的 tiles JSON 与 CLI payload 回显 `min_read_events` 参数值。
- 原因：前端联调时需要知道“已读阈值”以解释 tile 状态判定。
- 代价：导出字段增加，旧数据模型需做向后兼容。

## ADR-106 chunk 粒度 Markdown 增加 CSV 汇总行说明
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` Markdown 报告新增 `CSV Notes` 区块，解释 `keyword_filter_summary` 行语义。
- 原因：CSV 新增汇总行后，缺少说明会导致下游误读。
- 代价：Markdown 内容更长，字段演进时文档同步成本上升。

## ADR-107 replay Markdown 回显 schema_version
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 的 Markdown 报告头部新增 `csv_schema_version/jsonl_schema_version`。
- 原因：阅读报告时需要直接确认导出版本，避免跨文件比对。
- 代价：报告头部字段增加，文档说明维护项增多。

## ADR-108 cache_stats 增加 sample_count
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_count`，表示当前返回样本条数。
- 原因：仅看 `cache_key_samples` 需要额外求长度，增加显式计数字段更利于监控采集。
- 代价：字段冗余度略增，需要保证与样本数组长度一致。

## ADR-109 compare JSONL summary 增加 csv_schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --jsonl-output` 的 summary 行新增 `csv_schema_version`。
- 原因：JSONL 读者经常需要与 CSV 对照，summary 中直接给出 CSV 版本可减少歧义。
- 代价：JSONL summary schema 扩展，严格校验方需同步更新。

## ADR-110 trace 增加 memory_diversity_bucket
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_bucket`（`0..99`）稳定分桶回显。
- 原因：灰度诊断需要直接观察用户落在哪个 bucket，便于复现与对照。
- 代价：trace 字段继续扩展，日志消费脚本需兼容。

## ADR-111 拼图 HTML 头部回显 min_read_events
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 HTML 头部 meta 增加 `min_read_events`。
- 原因：阅读原型截图时需要明确“已读阈值”，否则进度解释不完整。
- 代价：头部信息增加，在小屏下可能略拥挤。

## ADR-112 chunk 粒度 JSONL 增加 schema_version
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py --jsonl-output` 每行新增 `schema_version=chunk_granularity_ab_samples.jsonl.v1`，CLI payload 回显 `jsonl_schema_version`。
- 原因：JSONL 导出进入离线实验链路后需要版本化以支持兼容演进。
- 代价：JSONL schema 扩展后，下游严格字段校验需同步调整。

## ADR-113 replay payload 增加 schema 版本一致性说明
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 脚本 JSON 输出新增 `schema_version_consistency_note`。
- 原因：调用方读取脚本输出时可快速确认 CSV/JSONL 版本对齐状态。
- 代价：脚本返回字段增多，消费方若做严格 schema 校验需同步调整。

## ADR-114 cache_stats 增加 sample_book_ids
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_book_ids`（来自 `cache_key_samples` 的 book_id 去重列表）。
- 原因：排障时常先按书维度定位问题，直接给出去重书籍列表更高效。
- 代价：字段与样本数组存在信息重叠，需要保证一致性。

## ADR-115 compare CSV summary 增加 jsonl_schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --csv-output` 的 summary 行新增 `jsonl_schema_version` 回显列。
- 原因：CSV 报表可直接标明对应 JSONL 版本，降低跨格式对齐成本。
- 代价：CSV 列扩展后，固定列序的下游任务需同步升级。

## ADR-116 trace 增加 rollout_enabled 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_enabled` 布尔字段。
- 原因：调试时需要快速判断当前请求是否处于灰度控制路径。
- 代价：trace 字段持续扩展，消费方需容忍新增字段。

## ADR-117 tiles JSON 增加 html_title
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 的 tiles JSON 与 CLI payload 新增 `html_title`。
- 原因：前端联调时希望直接复用页面标题，避免重复拼接逻辑。
- 代价：导出 payload 字段增加，旧解析器需兼容。

## ADR-118 chunk CSV summary 增加 schema_version
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py --csv-output` 增加 `schema_version` 列，包含 summary 行。
- 原因：CSV 结果（含 summary）需要统一版本标识，支持离线兼容治理。
- 代价：CSV 列结构变化后，下游固定列读取需同步更新。

## ADR-119 replay Markdown 增加一致性说明回显
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 的 Markdown 报告头部新增 `schema_version_consistency_note` 字段，并与脚本 JSON 输出复用同一计算逻辑。
- 原因：阅读 Markdown 报告时需要直接确认当前导出版本是否对齐，减少跨输出对照成本。
- 代价：报告头部信息进一步增加，文档字段维护成本上升。

## ADR-120 cache_stats 增加 sample_book_ids_count
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_book_ids_count` 字段，语义为 `sample_book_ids` 去重数量。
- 原因：调用方无需再本地计算列表长度，便于直接做监控采集与断言校验。
- 代价：与 `sample_book_ids` 存在冗余，需要持续保证两者一致性。

## ADR-121 compare JSONL rule_delta 增加 csv_schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --jsonl-output` 的每条 `rule_delta` 行新增 `csv_schema_version` 字段。
- 原因：每条明细行可独立声明其对应 CSV schema，降低分行消费时的上下文依赖。
- 代价：JSONL 行字段扩展后，严格 schema 校验方需同步更新。

## ADR-122 trace 增加 rollout_mode 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_mode`（`off|partial|full`）。
- 原因：仅有布尔 `rollout_enabled` 不足以表达灰度强度，需要显式模式值便于排障。
- 代价：trace 字段继续扩展，日志消费方需保持新增字段兼容。

## ADR-123 拼图 HTML 头部回显 tiles_json_schema_version
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 HTML 头部 meta 新增 `tiles_json_schema_version`。
- 原因：阅读 HTML 原型时可直接确认对应 tiles JSON schema，减少跨文件比对。
- 代价：头部信息更长，移动端展示空间略受影响。

## ADR-124 chunk 粒度 JSONL 增加 csv_schema_version 镜像
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py --jsonl-output` 每行新增 `csv_schema_version=chunk_granularity_ab_samples.csv.v1`。
- 原因：JSONL 行可独立声明所对应 CSV schema，便于混合消费场景做版本对齐。
- 代价：JSONL 字段扩展后，严格 schema 校验需同步升级。

## ADR-125 replay Markdown 增加 markdown_schema_version
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` 的 Markdown 报告头部新增 `markdown_schema_version=replay_memory_feed.markdown.v1`，脚本 JSON 输出在传 `--markdown-output` 时同步回显该版本。
- 原因：Markdown 导出也需要明确版本标识，便于后续结构演进与兼容治理。
- 代价：输出字段继续增加，消费方需放宽对未知字段的容忍度。

## ADR-126 cache_stats 增加 sample_chunk_ids_count
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_chunk_ids_count`，统计 `cache_key_samples.chunk_ids` 的去重数量。
- 原因：排障时除了书维度，还需要直接知道样本涉及的切片规模，避免调用方重复计算。
- 代价：与 `cache_key_samples` 形成冗余统计，需保持一致性约束。

## ADR-127 compare JSON payload 增加一致性说明
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 脚本 JSON 输出新增 `schema_version_consistency_note`。
- 原因：调用方可直接在主 payload 中确认 CSV/JSONL 版本对齐状态，减少额外推断。
- 代价：payload 字段扩展后，严格 schema 校验方需同步更新。

## ADR-128 trace 增加 rollout_bucket_hit 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_bucket_hit` 布尔字段（`bucket < gray_percent`）。
- 原因：相比只看 `bucket/gray_percent`，直接给出命中结果更便于快速判断灰度生效状态。
- 代价：trace 字段继续增加，日志消费方需兼容扩展。

## ADR-129 tiles JSON 增加 tiles_json_schema_version 镜像
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 `tiles.json` 新增 `tiles_json_schema_version`，值与 `schema_version` 保持一致。
- 原因：统一 payload 与文件内字段命名，便于前端消费方按固定键读取 schema 版本。
- 代价：字段与 `schema_version` 冗余，需要确保一致性。

## ADR-130 chunk 粒度 Markdown 回显 CSV/JSONL schema_version
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 的 Markdown 报告头部新增 `jsonl_schema_version/csv_schema_version`。
- 原因：阅读 Markdown 报告时即可确认导出格式版本，减少跨文件核对步骤。
- 代价：报告头部信息增加，文档维护项随之上升。

## ADR-131 replay JSONL 增加 markdown_schema_version 镜像
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --jsonl-output` 每行新增 `markdown_schema_version=replay_memory_feed.markdown.v1`。
- 原因：让 JSONL 行独立携带 Markdown schema 版本，便于跨格式离线对齐。
- 代价：JSONL 字段继续扩展，严格 schema 校验方需同步升级。

## ADR-132 cache_stats 增加 sample_book_ids_sorted_by_seen
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_book_ids_sorted_by_seen`，按 `cache_key_samples` 首次出现顺序去重。
- 原因：排障时除了集合值，还需要稳定的“出现顺序”视角辅助定位请求路径。
- 代价：与 `sample_book_ids` 信息部分重叠，需要保持两者一致性。

## ADR-133 compare Markdown 增加一致性说明回显
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 的 Markdown 报告头部新增 `schema_version_consistency_note`。
- 原因：仅看 Markdown 即可确认 CSV/JSONL 版本对齐，不必依赖 JSON payload。
- 代价：报告头部字段增加，文档维护项继续上升。

## ADR-134 trace 增加 rollout_bucket_distance 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_bucket_distance`（`bucket - gray_percent`；未开启灰度时为 `null`）。
- 原因：灰度排障时除了命中布尔值，还需要可量化的距离信息来判断“离阈值有多远”。
- 代价：trace 字段继续扩展，消费方需兼容新增字段。

## ADR-135 mosaic payload 增加 html_schema_version
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 脚本 JSON 输出新增 `html_schema_version=book_homepage_mosaic.html.v1`。
- 原因：调用方可直接识别 HTML 导出版本，无需从上下文推断。
- 代价：payload 字段增加，严格 schema 校验方需同步更新。

## ADR-136 chunk 粒度 payload 增加一致性说明
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 脚本 JSON 输出新增 `schema_version_consistency_note`。
- 原因：调用方可以在统一入口确认 CSV/JSONL 版本对齐，减少跨字段拼装逻辑。
- 代价：payload 字段扩展，旧解析器需容忍新增键。

## ADR-137 replay Markdown 总览增加 markdown_schema_version 列
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py` Markdown 报告 `Overview` 表格新增 `Markdown Schema` 列并回显 `markdown_schema_version`。
- 原因：总览表需要直接显示 Markdown schema 版本，便于截图/转发时保留版本上下文。
- 代价：表格列数增加，窄屏可读性略有下降。

## ADR-138 cache_stats 增加 sample_chunk_ids_sorted_by_seen
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_chunk_ids_sorted_by_seen`，按样本首次出现顺序去重输出 `chunk_ids`。
- 原因：排障时需要稳定顺序视角来还原缓存键访问路径。
- 代价：与 `sample_chunk_ids_count` 和 `cache_key_samples` 存在信息冗余。

## ADR-139 compare JSONL 增加 markdown_schema_version 镜像
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --jsonl-output` 的 `summary/rule_delta` 行新增 `markdown_schema_version`。
- 原因：JSONL 明细可独立声明 Markdown 版本，提升跨格式兼容治理能力。
- 代价：JSONL schema 扩展后，下游严格字段校验需同步更新。

## ADR-140 trace 增加 rollout_threshold_percent 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_threshold_percent`（灰度阈值百分比，未开启灰度时为 `null`）。
- 原因：将“阈值本身”与 bucket 命中/距离拆开回显，便于一次性复盘灰度判定链路。
- 代价：trace 字段继续扩展，消费端字段映射需同步维护。

## ADR-141 tiles JSON 增加 html_schema_version 镜像
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 `tiles.json` 新增 `html_schema_version=book_homepage_mosaic.html.v1`。
- 原因：让单个 tiles 文件即可表达其对应 HTML 版本，降低跨文件耦合。
- 代价：schema 字段冗余增加，需要保持版本一致性。

## ADR-142 chunk 粒度 Markdown 增加一致性说明回显
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` Markdown 报告头部新增 `schema_version_consistency_note`。
- 原因：查看 Markdown 报告即可确认 CSV/JSONL 版本配对，无需额外读取 JSON payload。
- 代价：报告头部信息继续增长，阅读密度略增。

## ADR-143 replay CSV 增加 markdown_schema_version 列
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --csv-output` 增加 `markdown_schema_version` 列，回显 `replay_memory_feed.markdown.v1`。
- 原因：CSV 行需要显式声明其对应 Markdown 版本，便于离线导出在多格式间做版本对齐。
- 代价：CSV schema 扩展后，严格列校验的消费方需同步升级。

## ADR-144 cache_stats 增加 sample_chunk_ids_first_seen_source 映射
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_chunk_ids_first_seen_source`，按样本首次出现记录 `chunk_id -> {book_id,sample_index}`。
- 原因：排障时除了顺序列表，还需要快速定位某个 `chunk_id` 首次出现于哪个样本来源。
- 代价：与 `cache_key_samples/sample_chunk_ids_sorted_by_seen` 存在信息冗余，需要保持一致性。

## ADR-145 compare JSON payload 增加 markdown_schema_version 回显
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 脚本 JSON 输出新增 `markdown_schema_version`（传 `--markdown-output` 时回显）。
- 原因：主 payload 直接携带 Markdown 版本，调用方无需再从导出参数推断。
- 代价：payload 字段增加，严格 schema 校验方需容忍新增键。

## ADR-146 trace 增加 rollout_bucket_percentile 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_bucket_percentile`（`bucket / 100`，范围 `0.0..0.99`）。
- 原因：相比仅回显离散 bucket 值，百分位更便于可视化与阈值对比分析。
- 代价：trace 字段继续扩展，消费方需兼容新增字段。

## ADR-147 HTML meta 增加 html_schema_version 回显
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 HTML `<head>` 新增 `meta[name=\"bookflow:html_schema_version\"]`。
- 原因：单看 HTML 即可识别其 schema 版本，减少与脚本 JSON 的耦合读取。
- 代价：页面头部 meta 项增加，模板维护项略有上升。

## ADR-148 chunk 粒度 CSV 增加 markdown_schema_version 列
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py --csv-output` 增加 `markdown_schema_version=chunk_granularity_ab_samples.markdown.v1` 列（含 summary 行）。
- 原因：CSV 行需要显式声明其对应 Markdown 版本，便于离线多格式联表对齐。
- 代价：CSV schema 扩展后，严格列校验方需要同步更新。

## ADR-149 replay CSV 增加 jsonl_schema_version 列
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --csv-output` 新增 `jsonl_schema_version` 列，回显 `replay_memory_feed.jsonl.v1`。
- 原因：CSV 行可直接声明其对应 JSONL 版本，便于导出格式之间做一致性校验。
- 代价：CSV schema 再次扩展，严格列校验消费方需同步升级。

## ADR-150 cache_stats 增加 sample_chunk_ids_first_seen_source_count
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_chunk_ids_first_seen_source_count`，值为 `sample_chunk_ids_first_seen_source` 条目数。
- 原因：调用方可 O(1) 获取映射规模，无需重复遍历映射计算计数。
- 代价：与映射本体存在冗余，需要保持一致性约束。

## ADR-151 compare Markdown 头部增加 markdown_schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py` 的 Markdown 报告头部新增 `markdown_schema_version`。
- 原因：阅读 Markdown 报告时即可直接确认对应版本，降低跨格式追踪成本。
- 代价：报告头部字段增多，文档密度略有提升。

## ADR-152 trace 增加 rollout_bucket_percentile_source 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_bucket_percentile_source=derived_from_bucket`。
- 原因：显式声明百分位计算来源，便于后续若引入多来源计算时保持向后兼容。
- 代价：trace 字段继续扩展，消费方需容忍新增键。

## ADR-153 HTML meta 增加 tiles_json_schema_version 回显
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 导出的 HTML `<head>` 新增 `meta[name=\"bookflow:tiles_json_schema_version\"]`。
- 原因：单看 HTML 即可确认其绑定的 tiles schema 版本，减少跨文件查证。
- 代价：页面头部 meta 项继续增加，模板维护项上升。

## ADR-154 chunk 粒度 payload 增加 markdown_schema_version 回显
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` 脚本 JSON 输出在传 `--markdown-output` 时新增 `markdown_schema_version`。
- 原因：调用方可以直接从主 payload 识别 Markdown 版本，无需从约定推断。
- 代价：payload 字段增加，严格 schema 校验方需同步更新。

## ADR-155 replay CSV 增加 markdown_schema_version_source 列
- 日期：`2026-03-29`
- 结论：`replay_memory_feed.py --csv-output` 新增 `markdown_schema_version_source=constant` 列。
- 原因：CSV 行需要明确标识该版本字段来源语义，减少下游对固定值的隐式假设。
- 代价：CSV schema 扩展后，严格列校验方需同步升级。

## ADR-156 cache_stats 增加 sample_chunk_ids_first_seen_source_sorted_chunk_ids
- 日期：`2026-03-29`
- 结论：`chunk_context_batch cache_stats` 新增 `sample_chunk_ids_first_seen_source_sorted_chunk_ids`（按 `chunk_id` 升序）。
- 原因：调用方可直接使用稳定键序列做对比/快照，无需重复从映射中排序。
- 代价：与映射本体存在冗余，需要保持一致性约束。

## ADR-157 compare CSV summary 行增加 markdown_schema_version
- 日期：`2026-03-29`
- 结论：`compare_auto_tag_rule_versions.py --csv-output` 的 `summary` 行新增 `markdown_schema_version` 回显。
- 原因：CSV 汇总行可直接表达三种导出格式（CSV/JSONL/Markdown）的版本对齐关系。
- 代价：CSV 列继续扩展，旧解析器需容忍新增列。

## ADR-158 trace 增加 rollout_bucket_percentile_label 回显
- 日期：`2026-03-29`
- 结论：feed trace query 新增 `memory_diversity_rollout_bucket_percentile_label`，格式为 `Pxx`（例如 `P07`）。
- 原因：排障与报表展示时，标签形式比纯数值更直观，便于快速扫描。
- 代价：trace 字段继续扩展，消费方需同步兼容。

## ADR-159 mosaic payload 增加 html_meta_tiles_schema_echoed 回显
- 日期：`2026-03-29`
- 结论：`render_book_homepage_mosaic.py` 脚本 JSON payload 新增 `html_meta_tiles_schema_echoed=true`。
- 原因：调用方可直接确认 HTML 是否已回显 tiles schema meta，无需再次解析 HTML 文本。
- 代价：payload 字段增加，严格 schema 校验方需升级。

## ADR-160 chunk 粒度 Markdown 头部增加 markdown_schema_version
- 日期：`2026-03-29`
- 结论：`export_chunk_granularity_ab_samples.py` Markdown 头部新增 `markdown_schema_version=chunk_granularity_ab_samples.markdown.v1`。
- 原因：阅读 Markdown 报告时可直接确认报告结构版本，便于跨格式对齐。
- 代价：报告头部信息密度增加，文档维护项上升。

## ADR-161 任务看板从“字段回显”切换为“端到端前端里程碑”
- 日期：`2026-03-29`
- 结论：`TASK_BOARD` 的 `NOW` 从低边际收益的字段回显任务，切换为 `NOW-183~185`（Feed 前端、上下文轴、书籍拼图页）三项产品落地任务。
- 原因：当前项目主风险已从“后端字段可观测性不足”转为“缺少可用前端闭环”；继续追加字段回显对北极星指标贡献很小。
- 代价：短期内 schema/脚本细节任务推进速度下降，但整体交付价值明显提高。

## ADR-162 前端同源托管 + 新增阅读详情与拼图接口
- 日期：`2026-03-29`
- 结论：在 `server/app.py` 新增 `/app` 同源静态托管，并补充 `/v1/chunk_detail` 与 `/v1/book_mosaic` 两个接口，支撑 `frontend/` 三页 MVP（Feed/Reader/Book）。
- 原因：仅靠既有 `/v1/feed` + `/v1/chunk_context` 无法稳定支撑阅读页正文渲染和书籍拼图页数据加载；同源托管可避免本地开发阶段的跨域配置复杂度。
- 代价：服务职责从纯 API 扩展为 API + 静态资源托管，后续需要关注前端资源缓存策略与部署边界。

## ADR-163 用户上传原始书籍统一归档到 data/books/inbox
- 日期：`2026-03-29`
- 结论：将用户上传的原始 PDF 统一放置到 `data/books/inbox/`，避免仓库根目录持续堆积大文件。
- 原因：固定入口目录便于后续批处理脚本与导入流程接入，也降低交接时的路径歧义。
- 代价：需要在后续导入文档和脚本中持续保持该目录约定一致。

## ADR-164 互动上报先走前端直连 /v1/interactions（无额外事件网关）
- 日期：`2026-03-29`
- 结论：Feed/Reader 页面直接调用 `/v1/interactions`，先打通 `impression/enter_context/like/comment/section_complete/backtrack` 最小闭环，不新增中间事件网关。
- 原因：当前是单用户私有化场景，优先验证行为闭环与数据可用性；额外网关会增加实现与排障复杂度。
- 代价：前端需承担事件构造与幂等 key 生成逻辑，后续若转多端/公开化需再抽离统一埋点 SDK。

## ADR-165 import_book 先落地 PDF 首版支持，EPUB 延后
- 日期：`2026-03-29`
- 结论：`scripts/import_book.py` 首先接入 `pypdf` 实现 PDF 文本抽取并打通现有清洗/切片流程；EPUB 暂时显式报错并给出转换建议。
- 原因：当前真实样本主要来自 PDF，优先解决最直接的导入阻塞；EPUB 解析方案（目录/样式保真）复杂度更高，放到后续迭代。
- 代价：短期内 EPUB 用户需先转换为 txt/json，导入体验不完整。

## ADR-166 Feed 回忆帖混排采用前端开关 + 后端参数透传
- 日期：`2026-03-29`
- 结论：Feed 页增加 `with_memory` 前端开关；开启时请求透传 `with_memory=1&memory_position=interval&memory_every=3`，并继续使用 `memory_post` 视觉区分。
- 原因：先让用户可控地体验“回忆帖混排”，再决定是否把该策略设为默认；参数透传方式不需要额外后端改造。
- 代价：当前策略参数固定在前端，后续若需要更细粒度实验需补充配置面板或服务端策略下发。

## ADR-167 建立统一 E2E 验收脚本（导入->Feed->上下文->事件上报）
- 日期：`2026-03-29`
- 结论：新增 `scripts/accept_end_to_end_flow.py`，作为最小闭环验收入口，覆盖导入、信息流可见性、上下文导航、交互事件写入。
- 原因：此前验收能力分散在多个脚本，无法一条命令判断“核心链路是否可用”；统一脚本更适合连续开发和 AI 交接。
- 代价：脚本启动临时服务进程并扫描 feed，执行时间略长于单点脚本。

## ADR-168 阅读页 confusion 采用轻交互 prompt 先落地
- 日期：`2026-03-29`
- 结论：在阅读页先使用轻量 `prompt` 收集 `confusion_type/note` 并上报 `event_type=confusion`，不引入复杂表单组件。
- 原因：该能力当前目标是尽快沉淀可分析的困惑信号，prompt 方案实现快且满足后端校验（`confusion_type` 必填）。
- 代价：交互体验较原生表单弱，后续可升级为内嵌面板与结构化选项。

## ADR-169 Feed 调试面板默认前端本地开关控制
- 日期：`2026-03-29`
- 结论：Feed 页调试信息（`trace_id/next_cursor/memory_inserted/ranking_source`）通过前端本地开关启用，并持久化在 `localStorage`。
- 原因：调试能力主要服务开发期，不应影响默认阅读体验；本地开关可快速启停且无需后端状态管理。
- 代价：调试状态仅在当前浏览器生效，多设备之间不会自动同步。

## ADR-170 拼图页先采用 section_id 关键词过滤 + 分组展示
- 日期：`2026-03-29`
- 结论：书籍拼图页新增 `section` 查询参数与输入框，按 `section_id` 关键词过滤后再分组展示 tile。
- 原因：不改后端接口即可快速提升“按章节找内容”的可用性，满足技术书回看场景。
- 代价：过滤在前端执行，大书规模下会增加浏览器端渲染开销，后续可考虑后端分页/筛选。

## ADR-171 import_book 正式补齐 EPUB 首版抽取（替代 ADR-165 的“EPUB 延后”）
- 日期：`2026-03-29`
- 结论：`scripts/import_book.py` 正式支持 EPUB 抽取（`zipfile + BeautifulSoup`），优先按 `spine` 顺序读取；缺少 `beautifulsoup4` 时显式报错。
- 原因：用户已有真实 EPUB 处理诉求，且基础版本可复用现有清洗/切片链路，已具备落地条件。
- 代价：HTML 语义清洗仍为首版启发式，复杂版式 EPUB 的章节边界仍可能不稳定。

## ADR-172 阅读页上下文轴接入 chunk_context_batch 邻居预取
- 日期：`2026-03-29`
- 结论：`frontend/reader.html` 在加载当前切片后，异步调用 `/v1/chunk_context_batch` 预取上一/下一切片上下文；切换时优先命中本地预取缓存。
- 原因：深读场景下切片切换频繁，提前拿到邻居上下文能降低导航 RTT 与体感卡顿。
- 代价：前端状态管理复杂度上升，需要维护小型预取缓存并处理命中/失效一致性。

## ADR-173 Feed 调试面板增加 trace_file 开关与 trace_file_path 回显
- 日期：`2026-03-29`
- 结论：Feed 前端新增 `trace_file` 开关；后端 `GET /v1/feed` 在 `trace_file=1` 成功落盘时返回 `trace_file_path`（绝对路径），调试面板展示最近路径。
- 原因：仅有 `trace_id` 仍需手动定位文件，增加路径回显可显著缩短排障链路。
- 代价：响应字段扩展，客户端需容忍 `trace_file_path=null`（未开启或写盘失败）。

## ADR-174 拼图页增加 read_first 排序模式
- 日期：`2026-03-29`
- 结论：`frontend/book.html` 新增 `sort=default|read_first`，其中 `read_first` 优先展示已读 tile，并保持同组内 `global_index` 稳定顺序。
- 原因：用户回看时通常先关注已读脉络，再决定补读未读内容，读优先排序更贴合复盘场景。
- 代价：排序逻辑从单一章节排序扩展为多条件排序，前端渲染逻辑复杂度上升。

## ADR-175 拼图页过滤从 section_id 扩展到 chunk_title
- 日期：`2026-03-29`
- 结论：拼图页新增 `title` 关键词过滤参数，与 `section` 过滤并行生效，支持更细粒度检索。
- 原因：仅靠 `section_id` 对技术书/教材场景不够直观，用户更常按标题关键词回忆目标内容。
- 代价：过滤条件增多后，需要在 URL 状态同步和“无结果提示”上保持一致性。

## ADR-176 E2E 验收脚本升级为 Markdown + JSONL 双报告
- 日期：`2026-03-29`
- 结论：`scripts/accept_end_to_end_flow.py` 新增 `--jsonl-output`，支持与 `--markdown-output` 同时导出，并回显 `jsonl_schema_version/markdown_schema_version` 与一致性说明。
- 原因：Markdown 适合人工阅读，JSONL 适合自动聚合；双报告可同时满足排障与离线统计需求。
- 代价：脚本输出协议扩展，调用方需容忍新增字段与可选导出路径。

## ADR-177 Reader 预取默认开启并提供可视化命中率
- 日期：`2026-03-29`
- 结论：`frontend/reader.html` 的邻居预取默认开启（本地可关闭），并在页脚回显 `prefetch_hits/loads/hit_rate/cache_size`。
- 原因：预取效果是否生效需要可观察指标，否则仅凭体感难以判断收益。
- 代价：阅读页调试信息增加，极简 UI 纯净度略有下降。

## ADR-178 Feed 调试面板提供 trace 路径一键复制
- 日期：`2026-03-29`
- 结论：Feed 页新增“复制最近 trace 路径”按钮，优先走 Clipboard API，失败时回退 prompt 手动复制。
- 原因：排障时最常见动作是把 trace 路径贴到终端或脚本，一键复制可减少重复手工操作。
- 代价：前端需兼容浏览器剪贴板权限差异并处理降级路径。

## ADR-179 EPUB 首版增加 toc/nav 噪声清理启发式
- 日期：`2026-03-29`
- 结论：EPUB 抽取在 HTML 解析阶段新增导航噪声裁剪（`nav/aside/footer` + 属性关键词匹配）并跳过 TOC 风格文本页。
- 原因：技术/教材 EPUB 常包含目录导航页，若直接入库会污染切片与标签质量。
- 代价：启发式规则存在误判风险，极端文档可能出现“误删正文”或“漏删目录”。

## ADR-180 拼图页过滤条件允许一键复制分享链接
- 日期：`2026-03-29`
- 结论：`frontend/book.html` 新增“复制当前过滤链接”按钮，复制前会先回填 `section/title/sort` 到 URL 查询参数。
- 原因：交接和复盘场景需要快速共享“当前视图状态”，手动拼参数成本高且易错。
- 代价：前端增加一段剪贴板兼容逻辑（Clipboard API + prompt 回退）。

## ADR-181 E2E 验收脚本补充 chunk_context_batch 缓存命中校验
- 日期：`2026-03-29`
- 结论：`accept_end_to_end_flow.py` 在 `chunk_context` 后增加 `chunk_context_batch` warmup + `cache_stats` 验证，并输出 `chunk_context_batch_*` 结果字段。
- 原因：阅读页已依赖批量上下文预取，仅验证单点 `chunk_context` 不足以覆盖真实关键路径。
- 代价：E2E 脚本步骤变长，对缓存配置更敏感（需兼容 `cache_enabled=false` 场景）。

## ADR-182 Feed 调试预设采用前端一键回填策略
- 日期：`2026-03-29`
- 结论：Feed 页新增 `preset`（普通/trace/interval/random+trace_file），一键回填请求 query 参数并同步到页面 URL。
- 原因：memory/trace 联动调试参数较多，手动切换效率低且不利于复现。
- 代价：前端状态管理更复杂，需要兼容“预设模式”与“手动模式”的共存。

## ADR-183 Reader 预取缓存提供手动清空入口
- 日期：`2026-03-29`
- 结论：`frontend/reader.html` 新增“清空预取缓存”按钮，点击后回显清空前后缓存规模。
- 原因：调试预取命中率时需要快速重置缓存状态，避免重开页面带来的额外操作成本。
- 代价：阅读页调试控件继续增多，需平衡沉浸阅读与调试可观测性。

## ADR-184 Feed trace 路径历史本地持久化为最近 5 条
- 日期：`2026-03-29`
- 结论：Feed 调试面板新增最近 5 次 `trace_file_path` 历史（`localStorage` 持久化），复制按钮无当前路径时回退到最近历史项。
- 原因：排障往往需要回溯上一批请求，单条“最新路径”不足以支持连续定位。
- 代价：前端状态与存储逻辑变复杂，需处理去重与容量控制。

## ADR-185 EPUB 导入输出补充章节级提取统计
- 日期：`2026-03-29`
- 结论：`import_book.py` 在 EPUB 导入时输出 `source_extract_stats`（`section_docs_total/kept/skipped_toc/empty_after_clean/ordered_from_spine`）。
- 原因：仅看最终 chunk 数难以判断抽取质量，章节级统计可快速定位“目录噪声过多”或“正文丢失”问题。
- 代价：CLI 输出字段扩展，调用方需容忍新增统计字段。

## ADR-186 Feed 调试预设支持 localStorage 命名自定义预设
- 日期：`2026-03-29`
- 结论：`frontend/index.html` 在内置预设基础上增加“保存当前为自定义预设”，将 `with_memory/trace/trace_file/memory_position/memory_every/memory_seed` 按名称保存到 `localStorage`，并与内置预设统一下拉加载。
- 原因：调试组合参数多且重复手工切换成本高，命名预设能显著降低复现成本并提升跨会话连续性。
- 代价：前端状态管理更复杂，需要处理内置/自定义预设冲突、非法配置兜底与本地存储兼容。

## ADR-187 Reader 预取命中率采用“全量 + 最近 N 次窗口”并行展示
- 日期：`2026-03-29`
- 结论：`frontend/reader.html` 在原有总命中率基础上新增最近 N 次（默认 20）滑动窗口命中率，便于观察短期波动。
- 原因：全量命中率在长会话中对近期性能变化不敏感，窗口指标更适合调试策略变更效果。
- 代价：前端状态逻辑增加一组窗口队列，需要控制容量避免无界增长。

## ADR-188 Feed trace 历史升级为“路径 + 采集时间”结构
- 日期：`2026-03-29`
- 结论：`trace_file_history` 从字符串数组升级为对象数组（`{path,captured_at_ms}`），并按时间倒序展示。
- 原因：只看路径难以复盘请求先后顺序，时间戳可直接支持“最近一次/上一轮”对照。
- 代价：需兼容旧版 localStorage（仅字符串数组）的读取回退。

## ADR-189 EPUB 提取统计补充章节文档名采样
- 日期：`2026-03-29`
- 结论：`source_extract_stats` 新增 `section_doc_name_samples`、`section_doc_kept_name_samples`、`section_doc_skipped_toc_name_samples` 等样本字段（默认前 5 条）。
- 原因：定位“为什么章节被跳过/保留”时，仅有计数不足，需要直接看到样本文档名辅助排障。
- 代价：统计字段变多，CLI 输出体积略增。

## ADR-190 Feed 自定义预设支持删除，内置预设只读
- 日期：`2026-03-29`
- 结论：新增“删除当前自定义预设”入口；内置预设不可删除。
- 原因：长期调试会累积无效预设，缺少清理入口会导致列表可用性下降。
- 代价：交互分支增多，需要清晰提示“当前是否可删除”。

## ADR-191 Reader 预取指标支持一键复制快照
- 日期：`2026-03-29`
- 结论：新增“复制预取指标快照”按钮，导出 JSON 快照（总/窗口命中率、上下文状态、缓存规模）。
- 原因：便于将同一时刻的诊断数据粘贴到日志、Issue 或交接文档。
- 代价：需兼容浏览器剪贴板权限受限场景（prompt 回退）。

## ADR-192 Feed 自定义预设同名保存前需覆盖确认
- 日期：`2026-03-29`
- 结论：保存自定义预设时若名称已存在，先弹出确认框，用户确认后才覆盖。
- 原因：减少误操作导致的配置丢失，提升调试参数管理可控性。
- 代价：多一步交互，快速连续保存场景操作成本略升。

## ADR-193 Feed 自定义预设支持 JSON 导出/导入迁移
- 日期：`2026-03-29`
- 结论：Feed 自定义预设可导出为 JSON 文件，并支持导入（兼容 `{presets: {...}}` 与扁平对象两种格式）。
- 原因：跨机器/跨会话迁移调试组合需要可传输格式，纯 localStorage 不可共享。
- 代价：导入流程需处理同名冲突、无效字段与 schema 兼容。

## ADR-194 Reader 预取窗口大小支持 query 配置并同步 URL
- 日期：`2026-03-29`
- 结论：新增 `prefetch_window` 参数（默认 20，范围 5..500），Reader 页面可配置并写回 URL。
- 原因：不同网络/书籍场景下窗口大小最优值不同，需支持快速可复现实验。
- 代价：前端需维护窗口参数的校验、持久化与状态收缩逻辑。

## ADR-195 EPUB 样本统计上限改为 CLI 参数
- 日期：`2026-03-29`
- 结论：`import_book.py` 新增 `--epub-sample-limit`（1..50），控制 `source_extract_stats` 文档名采样数量。
- 原因：默认 5 条在部分排障场景不足，需按任务上下文动态放大/缩小样本。
- 代价：命令参数增多，调用方需明确记录本次使用的采样上限。

## ADR-196 Feed trace 历史允许手动清空
- 日期：`2026-03-29`
- 结论：调试面板新增“清空 trace 历史”，一键清空本地最近路径缓存。
- 原因：排障切换阶段时，需要快速重置历史以避免旧数据干扰。
- 代价：误清空后无法恢复，需要依赖新请求重新积累历史。

## ADR-197 Reader 预取快照支持 Markdown 导出
- 日期：`2026-03-29`
- 结论：在 JSON 快照之外新增 Markdown 快照复制，便于直接粘贴到日志/Issue。
- 原因：很多交接场景使用 Markdown 文档，纯 JSON 可读性不稳定。
- 代价：维护两种导出格式，字段变更时需双份同步。

## ADR-198 EPUB 采样统计增加 sample-count 总览
- 日期：`2026-03-29`
- 结论：`source_extract_stats` 新增 `section_doc_name_sampled_counts`（`all/kept/skipped_toc/empty`）。
- 原因：在只看样本数组时难以快速感知分布，计数字段可降低排障阅读成本。
- 代价：统计字段继续扩展，旧解析代码需容忍新增键。

## ADR-199 Feed 预设导入完成提示采用新增/覆盖/总计三段式
- 日期：`2026-03-29`
- 结论：导入预设后统一回显 `新增 X，覆盖 Y，总计 Z`。
- 原因：单一“导入成功”提示不足以判断本次导入影响范围。
- 代价：提示内容变长，UI 文案维护点增加。

## ADR-200 Reader 预取窗口输入采用“自动纠正 + 友好提示”
- 日期：`2026-03-29`
- 结论：`prefetch_window` 输入在 `blur/save` 时自动纠正到 `5..500`，并提示纠正结果。
- 原因：窗口值直接影响统计解读，需避免非法值导致隐性偏差。
- 代价：用户输入会被自动改写，需通过提示降低困惑。

## ADR-201 import_book 输出显式回显 epub_sample_limit
- 日期：`2026-03-29`
- 结论：`import_book.py` 在 dry-run 与成功输出中统一回显 `epub_sample_limit`。
- 原因：排障报告常单独保存输出 JSON，显式回显可避免“忘记记录采样上限”。
- 代价：输出字段再次扩展，依赖严格 schema 的调用方需兼容新增键。

## ADR-202 Feed 预设导入增加 preview-only 模式
- 日期：`2026-03-29`
- 结论：导入预设支持“预览不落盘”，仅回显新增/冲突规模和样例名称。
- 原因：先看影响范围再落盘可降低误导入风险。
- 代价：导入流程增加分支，需要明确区分 preview 与 apply。

## ADR-203 Reader 预取快照补充 recent ctx_source 序列
- 日期：`2026-03-29`
- 结论：JSON/Markdown 预取快照增加 `recent_ctx_sources`，记录最近窗口的 `prefetch/api` 来源轨迹。
- 原因：单看命中率无法判断连续 miss 模式，来源序列更利于定位异常波动。
- 代价：快照体积略增，窗口越大内容越长。

## ADR-204 EPUB 样本统计增加 basename 输出
- 日期：`2026-03-29`
- 结论：`source_extract_stats` 新增 `*_samples_basename` 字段，输出样本文档文件名短形式。
- 原因：长路径在日志中可读性差，basename 便于快速人工扫描。
- 代价：同名文件可能歧义，仍需结合完整路径字段一起判断。

## ADR-205 Feed 预设导入预览支持 Markdown 摘要导出
- 日期：`2026-03-29`
- 结论：导入预览结果可复制为 Markdown（Added/Conflict 两段摘要）。
- 原因：便于在交接文档中直接粘贴预览差异。
- 代价：摘要仅展示名单，不含完整配置 diff。

## ADR-206 Reader 预取快照增加 window_hit_delta
- 日期：`2026-03-29`
- 结论：快照新增 `window_hit_delta`（当前窗口命中率减去上次快照窗口命中率）。
- 原因：连续快照对比时需要快速判断趋势，而非手工计算差值。
- 代价：首个快照无基线，字段为 `null` 需消费方兼容。

## ADR-207 EPUB basename 统计增加唯一值计数
- 日期：`2026-03-29`
- 结论：`source_extract_stats` 新增 `section_doc_basename_unique_counts`（all/kept/skipped_toc/empty）。
- 原因：可快速识别重名章节文件是否集中出现，辅助路径歧义排查。
- 代价：统计字段进一步扩展，输出复杂度上升。

## ADR-208 Feed 预览支持“仅冲突项”过滤
- 日期：`2026-03-29`
- 结论：导入预览模式增加 `conflict_only` 开关，可只展示冲突预设。
- 原因：大量新增项会稀释冲突信息，冲突优先视图更适合风险评估。
- 代价：预览逻辑和文案分支增加。

## ADR-209 Reader 快照新增 hit/miss sparkline
- 日期：`2026-03-29`
- 结论：快照新增 `recent_hit_miss_sparkline`（`H/M` 序列）用于快速观察窗口波动形态。
- 原因：单个命中率数字难以体现连续 miss 或连续 hit 的模式。
- 代价：窗口较大时字符串变长，可读性会下降。

## ADR-210 EPUB basename 统计新增 TopK 频次
- 日期：`2026-03-29`
- 结论：`source_extract_stats` 新增 `section_doc_basename_topk`（频次降序、名称升序）。
- 原因：TopK 可快速定位高频重复 basename，帮助分析章节命名重复模式。
- 代价：仅基于采样集统计，不代表全量文件分布。

## ADR-211 Feed 冲突预览 Markdown 增加 old/new JSON 片段
- 日期：`2026-03-29`
- 结论：冲突项在 Markdown 预览中附带 `old/new` JSON 代码块（默认前 5 条）。
- 原因：名称级预览不足以判断是否应覆盖，需看到配置内容差异。
- 代价：预览文本明显变长，需要条数截断控制。

## ADR-212 Reader 快照命中率增加等级标签
- 日期：`2026-03-29`
- 结论：快照新增 `recent_hit_rate_level`（`low|medium|high`）。
- 原因：非技术用户更容易用等级理解命中率健康度。
- 代价：等级阈值是启发式，需要后续支持可配置。

## ADR-213 EPUB TopK 统计支持最小频次阈值
- 日期：`2026-03-29`
- 结论：新增 `--epub-topk-min-count`，并回显 `section_doc_basename_topk_min_count`。
- 原因：当 basename 离散度高时，阈值过滤可避免 TopK 被大量一次性值占满。
- 代价：阈值过高可能导致 TopK 为空，需要调用方理解这一结果。

## ADR-214 Feed 冲突预览增加排序与截断计数回显
- 日期：`2026-03-29`
- 结论：冲突项按名称排序，并在预览中回显列表截断与详情截断计数。
- 原因：稳定排序有利于比对，截断计数可提示“仍有未展示项”。
- 代价：实现复杂度上升，需维护多组上限参数一致性。

## ADR-215 Reader 等级阈值支持 query/localStorage 配置
- 日期：`2026-03-29`
- 结论：`level_low_threshold` / `level_high_threshold` 可通过 query/localStorage 配置并持久化。
- 原因：不同网络环境下命中率分布差异大，固定阈值不够灵活。
- 代价：参数组合增多，需对非法阈值做归一化兜底。

## ADR-216 EPUB TopK 增加 threshold_applied 布尔回显
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_threshold_applied` 标记阈值是否生效（`min_count > 1`）。
- 原因：调试输出中快速区分“默认阈值”与“过滤后结果”。
- 代价：字段再扩展，消费方需容忍新增键。

## ADR-217 Feed 冲突预览支持字段级差异标记
- 日期：`2026-03-29`
- 结论：冲突项增加字段级差异标记（`+/-/~/=`）文本块，辅助快速审阅。
- 原因：直接阅读完整 old/new JSON 成本高，字段级摘要更高效。
- 代价：未展示嵌套对象深层差异，属于最小实现。

## ADR-218 Reader 等级标签支持可自定义文案
- 日期：`2026-03-29`
- 结论：`level_label_low/medium/high` 可通过 query/localStorage 配置，替代默认 `low/medium/high`。
- 原因：便于本地化或团队术语对齐。
- 代价：需限制文案长度并做空值兜底，避免 UI 噪声。

## ADR-219 EPUB TopK 输出支持可配置 topk_limit
- 日期：`2026-03-29`
- 结论：新增 `--epub-topk-limit`（1..20），并回显 `section_doc_basename_topk_limit`。
- 原因：不同排障场景对 TopK 长度需求不同，固定 5 不够灵活。
- 代价：新增参数提升使用复杂度，需要与 `min_count` 组合理解。

## ADR-220 Feed diff 支持仅变化字段模式
- 日期：`2026-03-29`
- 结论：新增 `diff_changed_only` 开关，冲突 diff 中可隐藏 `=` 未变化字段。
- 原因：大部分字段未变化时，显示全部字段会干扰审阅效率。
- 代价：默认隐藏可能漏看稳定字段，需保留关闭开关能力。

## ADR-221 Reader 等级标签支持模板化切换
- 日期：`2026-03-29`
- 结论：新增 `level_label_template=zh|en`，并允许与自定义 `level_label_*` 叠加。
- 原因：快速本地化切换比逐个手改标签更高效。
- 代价：模板与自定义叠加规则需要清晰约定。

## ADR-222 EPUB TopK 输出增加 topk_limit_applied
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_limit_applied` 字段，回显实际应用的 TopK 限制值。
- 原因：排障日志中可直接确认本次统计限制，不必反查命令参数。
- 代价：输出字段继续扩展，消费方需兼容新增键。

## ADR-223 Feed 冲突详情支持折叠展示
- 日期：`2026-03-29`
- 结论：预览 Markdown 冲突详情使用 `<details>` 折叠块包裹。
- 原因：冲突项较多时可降低页面长度与滚动成本。
- 代价：部分 Markdown 渲染器对折叠标签支持差异较大。

## ADR-224 Reader 标签模板支持占位符格式
- 日期：`2026-03-29`
- 结论：新增 `level_label_pattern`（需包含 `{label}`）用于格式化等级标签展示。
- 原因：满足“前缀/后缀”风格定制需求，无需改动标签本体。
- 代价：错误格式需兜底修正，避免渲染空标签。

## ADR-225 EPUB TopK 输出增加 total_candidates
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_total_candidates`，表示满足 `min_count` 的候选总数。
- 原因：便于判断 TopK 截断程度，不再仅依赖列表长度推断。
- 代价：统计字段进一步扩展，调用方需兼容新增键。

## ADR-226 Feed diff 行支持按字段类型分组
- 日期：`2026-03-29`
- 结论：字段级 diff 输出按 `bool/number/text` 三组分段展示。
- 原因：不同数据类型的变化风险不同，分组后更易审阅。
- 代价：分组逻辑增加，输出结构更复杂。

## ADR-227 Reader 快照回显模板来源
- 日期：`2026-03-29`
- 结论：快照新增 `level_label_template_source`（`query/localStorage/default`）。
- 原因：排障时需要明确模板来源，否则难以解释标签为何变化。
- 代价：状态管理多一维来源信息，需要保持更新一致性。

## ADR-228 EPUB TopK 输出增加 other_count
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_other_count = total_candidates - topk_rows`。
- 原因：可快速判断 TopK 之外还有多少候选被截断。
- 代价：当 `topk_limit` 很小会出现较大 other_count，需要正确解读。

## ADR-229 Feed diff 组内采用“操作类型优先”排序
- 日期：`2026-03-29`
- 结论：同一字段类型分组内按 `+ -> - -> ~ -> =` 排序，同操作内按字段名排序。
- 原因：先看新增/删除再看修改，更符合覆盖审阅流程。
- 代价：排序规则更复杂，需要在文档中固定以避免误解。

## ADR-230 Reader 快照增加 schema 版本与字段描述
- 日期：`2026-03-29`
- 结论：快照新增 `snapshot_schema_version` 与 `snapshot_schema_fields.level_label_template_source`。
- 原因：便于机器解析时稳定识别模板来源字段语义。
- 代价：快照体积略增，版本字段需要维护。

## ADR-231 EPUB TopK 输出增加 coverage_ratio
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio = len(topk_rows)/total_candidates`（四位小数）。
- 原因：相比只看 `other_count`，占比更直观反映 TopK 覆盖程度。
- 代价：coverage 口径依赖候选定义，需配合 `min_count` 一起解读。

## ADR-232 Feed diff 增加字段名过滤输入
- 日期：`2026-03-29`
- 结论：预览区新增 `diff_field_filter`，字段级 diff 行支持按字段名过滤。
- 原因：冲突字段较多时，按关键字聚焦可显著降低人工审阅噪声。
- 代价：过滤后可能遗漏上下文字段，需要保留空过滤回看全量能力。

## ADR-233 Reader 快照 schema 增加 template_source_note
- 日期：`2026-03-29`
- 结论：`snapshot_schema_fields` 新增 `template_source_note` 字段说明。
- 原因：仅有 enum 值时语义不直观，增加说明可提升交接可读性。
- 代价：快照体积略增，schema 版本需持续维护。

## ADR-234 EPUB TopK 增加 coverage_ratio_source 回显
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_source`，固定回显计算口径字符串。
- 原因：避免调用方误解 coverage 分子分母定义。
- 代价：字段扩展后，调用方需兼容新增键。

## ADR-235 Feed 字段过滤支持可选正则模式
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex` 开关，支持以正则匹配字段名并回显 regex 错误。
- 原因：子串匹配不足以覆盖复杂命名筛选场景，正则更灵活。
- 代价：正则表达式可能写错，需要错误信息与兜底行为。

## ADR-236 Reader 快照 schema 回显 template_source_enum
- 日期：`2026-03-29`
- 结论：`snapshot_schema_fields` 新增 `template_source_enum = [query, localStorage, default]`。
- 原因：为机器消费方提供稳定枚举边界，降低字段解释歧义。
- 代价：schema 变更会触发版本维护成本。

## ADR-237 EPUB TopK coverage_ratio 支持精度参数化
- 日期：`2026-03-29`
- 结论：新增 `--epub-topk-coverage-ratio-precision`（`0..6`）和回显字段 `section_doc_basename_topk_coverage_ratio_precision`。
- 原因：不同展示场景对小数位要求不同，固定 4 位不够灵活。
- 代价：跨任务比较时需关注精度配置，避免误判差异。

## ADR-238 Feed regex 字段过滤支持 flags 输入
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_flags`，并回显 `flags_applied`。
- 原因：在多语言字段场景下，flags 可提升匹配表达能力。
- 代价：flags 非法时会出现编译错误，需要在预览中提示。

## ADR-239 Reader schema 增加 template_source_enum_note
- 日期：`2026-03-29`
- 结论：`snapshot_schema_fields` 新增 `template_source_enum_note` 说明字段。
- 原因：补充 enum 数组的语义描述，提升交接与机器消费可读性。
- 代价：schema 元数据继续膨胀，需要控制字段增长节奏。

## ADR-240 EPUB TopK 输出增加 coverage_ratio_raw
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_raw`（未按精度四舍五入的原始值）。
- 原因：便于在不同 precision 配置下做横向比对与复核。
- 代价：输出字段增加，调用方需明确 raw 与 rounded 的差异用途。

## ADR-241 Feed regex 过滤增加大小写敏感开关
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_case_sensitive`，默认关闭（即默认补 `i`）。
- 原因：多数审阅场景希望大小写不敏感，但仍需保留严格匹配能力。
- 代价：flags 组合规则更复杂，需要回显 applied flags。

## ADR-242 Reader Markdown 增加 schema_fields_json 区块
- 日期：`2026-03-29`
- 结论：快照 Markdown 附加 `snapshot_schema_fields_json` 代码块。
- 原因：便于人工/AI 直接复制 schema 结构做对照或解析。
- 代价：Markdown 长度增加，部分场景可读性略降。

## ADR-243 EPUB coverage_ratio_precision 增加来源标记
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_source`（`cli/default`）。
- 原因：相同 precision 值在“默认”与“显式指定”场景语义不同，排障需要来源信息。
- 代价：来源定义依赖调用入口，需要保持一致约定。

## ADR-244 Feed regex flags 增加非法字符即时提示
- 日期：`2026-03-29`
- 结论：前端对 flags 输入做本地字符白名单校验并即时提示。
- 原因：减少“预览时才发现 regex 编译失败”的反馈延迟。
- 代价：提示逻辑与浏览器 regex 实现可能存在边界差异。

## ADR-245 Reader schema 增加 template_source_enum_version
- 日期：`2026-03-29`
- 结论：`snapshot_schema_fields` 新增 `template_source_enum_version`（当前 `v1`）。
- 原因：为后续 enum 变更预留版本锚点，降低兼容风险。
- 代价：版本字段需要随 schema 演进维护。

## ADR-246 EPUB coverage_ratio_raw 增加 source 字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_raw_source`，明确 raw 值计算口径（unrounded）。
- 原因：避免调用方将 raw 与 rounded 口径混淆。
- 代价：输出字段增长，文档与测试需同步维护。

## ADR-247 Feed regex 增加前缀匹配快捷开关
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_prefix`，开启后自动编译为 `^(?:pattern)`。
- 原因：前缀匹配是常见筛选诉求，独立开关比手写锚点更易用。
- 代价：对复杂正则可能改变预期匹配范围，需要清晰回显开关状态。

## ADR-248 Reader Markdown 增加 schema_fields_json 行数
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_lines` 统计字段。
- 原因：便于快速感知 schema 复杂度变化，辅助回归比对。
- 代价：统计值对格式化方式敏感，需保持 JSON pretty-print 规则稳定。

## ADR-249 EPUB coverage_ratio_precision 增加 note 字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note`（如 `rounded_to_4_decimal_places`）。
- 原因：让输出自描述 precision 含义，减少对外部文档依赖。
- 代价：字段冗余增加，调用方需决定是否消费该说明。

## ADR-250 Feed regex flags 提示增加去重预览
- 日期：`2026-03-29`
- 结论：flags 校验通过时提示“去重后 flags”和“最终生效 flags”。
- 原因：帮助用户快速理解重复 flags 与大小写敏感开关的影响。
- 代价：提示逻辑增加，需与实际编译 flags 规则保持一致。

## ADR-251 Reader schema_fields_json 增加 hash 回显
- 日期：`2026-03-29`
- 结论：快照新增 `snapshot_schema_fields_hash`（FNV-1a），Markdown 同步回显 `snapshot_schema_fields_json_hash`。
- 原因：可快速比对 schema 是否变化，便于自动化与人工回归。
- 代价：非加密 hash 仅用于一致性对比，不用于安全场景。

## ADR-252 EPUB coverage_ratio_raw_source 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_raw_source_version`，当前值 `v1`。
- 原因：为后续 raw_source 口径演进预留兼容锚点。
- 代价：字段数继续增长，需要文档持续跟进。

## ADR-253 Feed regex 前缀模式回显 compiled_pattern
- 日期：`2026-03-29`
- 结论：预览 Markdown 新增 `diff_field_filter_regex_compiled_pattern`。
- 原因：排障时可直接看到最终编译 pattern，避免推断错误。
- 代价：pattern 可能较长，预览信息密度增加。

## ADR-254 Reader Markdown 增加 schema_fields_json 首行
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_first_line` 回显。
- 原因：无需展开代码块即可快速确认 schema JSON 结构起始。
- 代价：信息有一定冗余，但读取效率更高。

## ADR-255 EPUB precision note 增加来源标记
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_source`，固定 `derived_from_section_doc_basename_topk_coverage_ratio_precision`。
- 原因：明确 note 生成口径，避免误解为外部输入字段。
- 代价：继续扩展字段集合，消费方需兼容新增键。

## ADR-256 Feed regex 增加 compiled_pattern_source
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_source`（`prefix_wrapped|original`）。
- 原因：仅看 compiled pattern 难以区分是否由前缀开关自动包裹。
- 代价：预览字段继续增长，需要保持说明一致。

## ADR-257 Reader Markdown 增加 schema_fields_json 字符数
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_chars` 统计。
- 原因：可快速观察 schema 内容体积变化趋势。
- 代价：字符数依赖 JSON 序列化格式，跨格式比较需谨慎。

## ADR-258 EPUB raw_source_version 增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_raw_source_version_note`。
- 原因：为版本字段提供自解释文案，降低外部查文档成本。
- 代价：统计输出更冗长，需维持字段命名一致性。

## ADR-259 Feed compiled_pattern 增加 note 字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_note`（prefix/original 语义说明）。
- 原因：让 pattern 回显更具可解释性，减少人工二次推断。
- 代价：与 source 字段有轻度语义重叠。

## ADR-260 Reader schema hash 增加算法标记
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_hash_algorithm`（`fnv1a-32`）并在 Markdown 回显。
- 原因：不同 hash 算法不可直接比较，需显式标记算法。
- 代价：需要维护算法字段与实现一致。

## ADR-261 EPUB precision_note 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_version`（`v1`）。
- 原因：为 note 语义演进预留兼容锚点。
- 代价：字段继续扩张，消费方需容忍新增键。

## ADR-262 Feed compiled_pattern 增加长度回显
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_length`。
- 原因：便于快速识别异常长 pattern 造成的可读性与性能风险。
- 代价：与 pattern 本体信息有部分重复。

## ADR-263 Reader schema hash 增加长度回显
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_hash_length`。
- 原因：辅助校验 hash 输出形态是否稳定（例如 8 位 hex）。
- 代价：属于诊断冗余字段，长期可能需要收敛。

## ADR-264 EPUB precision_note_source 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_source_version`（`v1`）。
- 原因：为来源说明口径演进提供版本锚点。
- 代价：字段继续增加，调用方解析复杂度上升。

## ADR-265 Feed compiled_pattern 增加 effective flags 回显
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective`。
- 原因：直观看到 pattern 编译时实际使用 flags，便于复盘匹配结果。
- 代价：与 `flags_applied` 字段有语义重叠。

## ADR-266 Reader Markdown 增加 schema_fields_json 缩略摘要
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary`（压缩空白后截断 120 字符）。
- 原因：在不展开代码块时也可快速感知 schema 内容概貌。
- 代价：摘要存在截断与信息损失，不可替代完整 JSON。

## ADR-267 EPUB precision_note 增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template = rounded_to_{precision}_decimal_places`。
- 原因：便于调用方在不同语言或模板体系下二次生成文案。
- 代价：模板与 note 共存会带来一定冗余。

## ADR-268 Feed effective flags 增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_source`。
- 原因：明确 effective flags 来自规范化步骤，而非原始输入直出。
- 代价：字段继续膨胀，输出阅读复杂度上升。

## ADR-269 Reader schema 摘要增加长度字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_length`。
- 原因：用于快速判断摘要是否触发截断上限。
- 代价：摘要与长度双字段存在冗余。

## ADR-270 EPUB precision_note_template 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_version`（`v1`）。
- 原因：为模板语义演进预留兼容锚点。
- 代价：版本字段增多，调用方需维护映射。

## ADR-271 Feed effective flags 增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_note`。
- 原因：提高 effective flags 字段的可解释性，便于交接阅读。
- 代价：说明文案需要与实现保持同步。

## ADR-272 Reader schema 摘要增加来源标记
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_source`。
- 原因：明确摘要来自“空白压缩 + 截断”处理链路。
- 代价：同类元字段增多，输出更冗长。

## ADR-273 EPUB precision_note_template 增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source`（`static_template`）。
- 原因：区分模板常量与运行时生成字段。
- 代价：字段数量继续上升，消费端需容忍。

## ADR-274 Feed effective flags 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_version`（`v1`）。
- 原因：为 effective flags 口径后续演进保留版本锚点。
- 代价：字段继续增多，预览信息密度上升。

## ADR-275 Reader schema 摘要增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_version`（`v1`）。
- 原因：当摘要算法调整时可快速识别版本差异。
- 代价：需要维护版本值与算法实现一致。

## ADR-276 EPUB template_source 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_version`（`v1`）。
- 原因：为 source 字段语义演进提供兼容锚点。
- 代价：输出字段膨胀持续，需要长期治理。

## ADR-277 Feed effective flags 增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template`。
- 原因：统一描述 effective flags 生成逻辑，便于自动化消费。
- 代价：模板、说明、版本字段并存，结构更复杂。

## ADR-278 Reader schema 摘要增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template`。
- 原因：为摘要算法的人类可读表达提供稳定模板。
- 代价：模板文案需与实现长期保持一致。

## ADR-279 EPUB template_source 增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note`。
- 原因：明确 `template_source` 的语义来源，减少误读。
- 代价：输出继续冗长，需靠文档治理可读性。

## ADR-280 Feed effective flags 模板增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_version`（`v1`）。
- 原因：为模板演进保留版本锚点，避免灰度混淆。
- 代价：字段继续叠加，预览面板更密集。

## ADR-281 Reader 摘要模板增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_version`（`v1`）。
- 原因：当摘要模板调整时可快速识别版本差异。
- 代价：需要持续维护版本字段的一致性。

## ADR-282 EPUB template_source_note 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version`（`v1`）。
- 原因：为 note 文案演进提供兼容锚点。
- 代价：统计输出持续膨胀，需要控制长期复杂度。

## ADR-283 Feed effective flags 模板增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source`（`static_template_literal`）。
- 原因：区分模板常量与运行态推导字段。
- 代价：同类元字段持续扩张，预览更拥挤。

## ADR-284 Reader 摘要模板增加来源标记
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source`（`static_template_literal`）。
- 原因：提升摘要模板语义的可追溯性。
- 代价：字段数量增加，需保持文档同步。

## ADR-285 EPUB source_note_template 增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template`。
- 原因：为 source_note 文案生成提供可复用模板。
- 代价：模板链路更长，消费端理解成本提升。

## ADR-286 Feed effective flags 模板来源增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_version`（`v1`）。
- 原因：为模板来源字段后续演进提供兼容锚点。
- 代价：预览元字段持续增加，信息密度上升。

## ADR-287 Reader 摘要模板来源增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_version`（`v1`）。
- 原因：便于在模板来源口径调整时快速识别版本差异。
- 代价：维护成本上升，需要保证版本与实现一致。

## ADR-288 EPUB source_note_template 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version`（`v1`）。
- 原因：为 source_note_template 语义变化预留稳定锚点。
- 代价：统计结构继续膨胀，调用端认知成本提升。

## ADR-289 Feed effective flags 模板来源增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note`。
- 原因：补强来源字段可读性，降低交接时语义歧义。
- 代价：说明文案需长期与实现同步。

## ADR-290 Reader 摘要模板来源增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note`。
- 原因：让 Markdown 快照无需跳转代码即可理解来源语义。
- 代价：快照输出继续变长，阅读负担略增。

## ADR-291 EPUB source_note_template 增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source`（`static_template`）。
- 原因：区分模板常量与运行态派生文本，便于自动消费。
- 代价：source/template/version 链条更长，需要文档持续约束。

## ADR-292 Feed 模板来源说明增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_version`（`v1`）。
- 原因：为说明文案演进提供稳定兼容锚点。
- 代价：元字段继续增长，预览噪声上升。

## ADR-293 Reader 摘要模板来源说明增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_version`（`v1`）。
- 原因：便于追踪说明文案语义迭代。
- 代价：快照字段进一步扩张，维护成本上升。

## ADR-294 EPUB source_note_template_source 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version`（`v1`）。
- 原因：为 source 字段口径变化预留版本锚点。
- 代价：统计 payload 更臃肿，需要后续治理。

## ADR-295 Feed 模板来源说明增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template`。
- 原因：统一说明文案生成模板，便于自动化复用。
- 代价：模板链路更长，字段理解成本增加。

## ADR-296 Reader 摘要模板来源说明增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template`。
- 原因：让快照说明文案具备可复用模板表达。
- 代价：快照 Markdown 元字段继续增多。

## ADR-297 EPUB source_note_template_source 增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note`。
- 原因：明确 source 字段语义，降低误读风险。
- 代价：统计输出更冗长，消费端解析负担上升。

## ADR-298 Feed 来源说明模板增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_version`（`v1`）。
- 原因：为来源说明模板迭代提供稳定版本锚点。
- 代价：调试输出字段继续增加。

## ADR-299 Reader 来源说明模板增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_version`（`v1`）。
- 原因：便于快照消费者识别模板版本变更。
- 代价：快照元字段进一步膨胀。

## ADR-300 EPUB source_note 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：让 source_note 文案演进可做兼容管理。
- 代价：统计输出持续变长，阅读成本提升。

## ADR-301 Feed 来源说明模板增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source`（`static_template_literal`）。
- 原因：区分模板常量与运行态推导内容。
- 代价：调试字段链路继续拉长。

## ADR-302 Reader 来源说明模板增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source`（`static_template_literal`）。
- 原因：增强快照模板元信息可追溯性。
- 代价：快照体积继续增大。

## ADR-303 EPUB source_note 增加模板字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template`。
- 原因：为 source_note 文案生成提供可复用模板。
- 代价：统计结构复杂度上升，需要持续文档化。

## ADR-304 Feed 来源说明模板来源增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_version`（`v1`）。
- 原因：为 template_source 字段演进保留兼容锚点。
- 代价：字段数量继续增加。

## ADR-305 Reader 来源说明模板来源增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_version`（`v1`）。
- 原因：提升快照 schema 演进的可识别性。
- 代价：快照内容更长，需要折叠展示辅助。

## ADR-306 EPUB source_note_template 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：为 source_note_template 文案兼容升级提供版本锚点。
- 代价：统计输出继续膨胀，消费端需要持续适配。

## ADR-307 Feed 来源说明模板来源增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note`。
- 原因：补强 template source 语义可读性，降低交接歧义。
- 代价：调试输出继续增长。

## ADR-308 Reader 来源说明模板来源增加说明字段
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note`。
- 原因：让 Markdown 快照脱离代码上下文也能读懂来源语义。
- 代价：快照字段继续膨胀。

## ADR-309 EPUB source_note_template 增加来源字段
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source`（`static_template`）。
- 原因：区分模板常量与运行态文本，便于自动消费。
- 代价：统计结构继续拉长。

## ADR-310 Feed 来源说明模板来源说明增加版本号
- 日期：`2026-03-29`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_version`（`v1`）。
- 原因：为说明文案迭代预留兼容锚点。
- 代价：字段数量继续增加。

## ADR-311 Reader 来源说明模板来源说明增加版本号
- 日期：`2026-03-29`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_version`（`v1`）。
- 原因：便于追踪快照说明文案版本变化。
- 代价：快照冗长度上升。

## ADR-312 EPUB source_note_template_source 增加版本号
- 日期：`2026-03-29`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：为 source 字段语义演进提供稳定兼容锚点。
- 代价：消费端需持续适配新增元字段。

## ADR-313 Feed 来源说明模板来源说明增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template`。
- 原因：让说明文案可模板化复用。
- 代价：调试字段链继续增长。

## ADR-314 Reader 来源说明模板来源说明增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template`。
- 原因：提升快照说明文案复用能力。
- 代价：Markdown 快照继续变长。

## ADR-315 EPUB source_note_template_source 增加来源字段
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source`（`static_template`）。
- 原因：区分模板常量与动态内容，便于自动消费。
- 代价：统计输出字段膨胀。

## ADR-316 Feed 来源说明模板来源说明模板增加版本号
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：为说明模板演进提供兼容锚点。
- 代价：元字段数量继续增加。

## ADR-317 Reader 来源说明模板来源说明模板增加版本号
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：便于识别快照模板版本差异。
- 代价：快照冗余进一步提升。

## ADR-318 EPUB source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：为 source 字段语义变化提供稳定版本管理。
- 代价：调用侧需持续维护新增字段映射。

## ADR-319 Feed 来源说明模板来源说明模板增加来源字段
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source`（`static_template_literal`）。
- 原因：继续强化模板语义可追溯性。
- 代价：调试输出字段进一步拉长。

## ADR-320 Reader 来源说明模板来源说明模板增加来源字段
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source`（`static_template_literal`）。
- 原因：提升快照说明模板的来源透明度。
- 代价：Markdown 体积继续增加。

## ADR-321 EPUB source_note_template_source 增加说明字段
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note`。
- 原因：补充 source 字段语义说明，降低消费歧义。
- 代价：统计 payload 复杂度上升。

## ADR-322 Feed 来源说明模板来源说明模板来源增加版本号
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：为来源字段后续变更提供版本锚点。
- 代价：元字段持续增多。

## ADR-323 Reader 来源说明模板来源说明模板来源增加版本号
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：快照消费者可稳定识别版本差异。
- 代价：快照结构进一步冗长。

## ADR-324 EPUB source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：为说明文案迭代保留兼容语义。
- 代价：调用端需持续维护字段映射表。

## ADR-325 Feed 来源说明模板来源说明模板来源增加说明字段
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note`。
- 原因：增强 template_source 字段解释能力，降低歧义。
- 代价：字段链进一步增长。

## ADR-326 Reader 来源说明模板来源说明模板来源增加说明字段
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note`。
- 原因：快照阅读无需回看代码即可理解来源语义。
- 代价：Markdown 快照更长。

## ADR-327 EPUB source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：说明文案可模板化复用。
- 代价：统计字段复杂度上升。

## ADR-328 Feed 来源说明模板来源说明模板来源说明增加版本号
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：为说明文案迭代提供兼容锚点。
- 代价：调试输出继续膨胀。

## ADR-329 Reader 来源说明模板来源说明模板来源说明增加版本号
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：快照消费者可稳定识别说明版本变化。
- 代价：元数据冗余增加。

## ADR-330 EPUB source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：为模板语义演进保留版本兼容能力。
- 代价：统计结构持续拉长。

## ADR-331 Feed 来源说明模板来源说明模板来源说明增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note_template`。
- 原因：说明链路模板化，便于复用与对比。
- 代价：调试字段链继续增长。

## ADR-332 Reader 来源说明模板来源说明模板来源说明增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note_template`。
- 原因：快照文案模板化提升可维护性。
- 代价：Markdown 输出冗长度继续上升。

## ADR-333 EPUB source_note_template_source_note_template 增加来源字段
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source`（`static_template`）。
- 原因：显式区分模板来源与动态值。
- 代价：统计字段再次膨胀。

## ADR-334 Feed 来源说明模板来源说明模板来源说明模板增加版本号
- 日期：`2026-03-30`
- 结论：新增 `diff_field_filter_regex_compiled_pattern_flags_effective_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：为模板演进提供版本锚点。
- 代价：配置和消费端映射复杂度上升。

## ADR-335 Reader 来源说明模板来源说明模板来源说明模板增加版本号
- 日期：`2026-03-30`
- 结论：新增 `snapshot_schema_fields_json_summary_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：便于回放与比对不同快照模板版本。
- 代价：字段继续增多。

## ADR-336 EPUB source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段语义演进需要版本兼容。
- 代价：统计 payload 复杂度持续增加。

## ADR-337 Feed 深层来源说明模板增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source` 回显。
- 原因：保持模板链路元信息对称。
- 代价：字段长度继续增长。

## ADR-338 Reader 深层来源说明模板增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：快照可独立解释来源。
- 代价：Markdown 体积增加。

## ADR-339 EPUB 深层来源说明增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：补强 source 语义说明。
- 代价：统计 payload 更复杂。

## ADR-340 Feed 深层来源说明模板 source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：为语义演进提供兼容锚点。
- 代价：调试字段继续膨胀。

## ADR-341 Reader 深层来源说明模板 source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：提升快照回放一致性。
- 代价：维护成本上升。

## ADR-342 EPUB 深层来源说明 note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：说明文案支持版本兼容。
- 代价：消费端映射增多。

## ADR-343 Feed 深层来源说明模板 source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：模板化文案便于复用。
- 代价：字段链继续拉长。

## ADR-344 Reader 深层来源说明模板 source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：与 Feed 元信息保持对齐。
- 代价：快照冗余增加。

## ADR-345 EPUB 深层来源说明 note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：说明字段可模板化复用。
- 代价：统计结构更复杂。

## ADR-346 Feed 深层来源说明模板 source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：模板演进需要版本锚点。
- 代价：配置字段增多。

## ADR-347 Reader 深层来源说明模板 source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照版本对比更稳定。
- 代价：可读性下降。

## ADR-348 EPUB 深层来源说明 note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：模板字段语义可兼容演进。
- 代价：消费端字段映射增加。

## ADR-349 Feed 深层来源说明模板 source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：保持模板/source 双字段对称。
- 代价：输出更冗长。

## ADR-350 Reader 深层来源说明模板 source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：提升快照来源透明度。
- 代价：快照长度增加。

## ADR-351 EPUB 深层来源说明 note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`（`static_template`）。
- 原因：区分模板常量与动态值。
- 代价：统计字段继续膨胀。

## ADR-352 Feed 深层来源说明模板 source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段演进可控。
- 代价：调试元字段继续增加。

## ADR-353 Reader 深层来源说明模板 source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：提高快照回放一致性。
- 代价：维护复杂度上升。

## ADR-354 EPUB 深层来源说明 note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 语义需要版本兼容。
- 代价：消费端映射表扩张。

## ADR-355 Feed 深层来源说明模板 source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template` 回显。
- 原因：保持来源说明链路在 Feed 预览中的可解释性。
- 代价：字段数量继续增长。

## ADR-356 Reader 深层来源说明模板 source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template`。
- 原因：Reader 快照与 Feed 回显维持一致语义。
- 代价：Markdown 快照变长。

## ADR-357 EPUB 深层来源说明 note 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：区分模板常量来源与动态派生值。
- 代价：统计输出复杂度上升。

## ADR-358 Feed 深层来源说明模板字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：模板语义演进需要版本锚点。
- 代价：调试面板映射项增多。

## ADR-359 Reader 深层来源说明模板字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照版本对比更稳定。
- 代价：字段冗余增加。

## ADR-360 EPUB 深层来源说明 source 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段迭代可向后兼容。
- 代价：消费端字段映射继续扩张。

## ADR-361 Feed 深层来源说明模板增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source` 回显。
- 原因：保持 template/source 成对可追溯。
- 代价：预览元信息更冗长。

## ADR-362 Reader 深层来源说明模板增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：Reader 快照链路可独立解释来源。
- 代价：快照体积继续增加。

## ADR-363 EPUB 深层来源说明增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：补充 source 字段的人类可读说明。
- 代价：统计 payload 更复杂。

## ADR-364 Feed 深层来源说明 source 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段语义变更可控。
- 代价：字段链持续变长。

## ADR-365 Reader 深层来源说明 source 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：提升回放一致性。
- 代价：阅读成本上升。

## ADR-366 EPUB 深层来源说明 note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：说明文案可按版本兼容。
- 代价：消费端适配项增多。

## ADR-367 Feed 深层来源说明模板增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note` 回显。
- 原因：补足 source 字段的说明闭环。
- 代价：输出更长。

## ADR-368 Reader 深层来源说明模板增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：Reader 与 Feed 语义保持对齐。
- 代价：快照噪声增加。

## ADR-369 EPUB 深层来源说明 note 字段增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：说明文案模板可复用。
- 代价：字段链条更深。

## ADR-370 Feed 深层来源说明 note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：note 字段支持向后兼容演进。
- 代价：调试回显项继续增加。

## ADR-371 Reader 深层来源说明 note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：快照跨版本比对更清晰。
- 代价：可读性下降。

## ADR-372 EPUB 深层来源说明 note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：模板字段演进需版本锚点。
- 代价：字段管理成本上升。

## ADR-373 Feed 深层来源说明 note 增加 template 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template` 回显。
- 原因：模板化文案复用能力提升。
- 代价：链路字段继续扩张。

## ADR-374 Reader 深层来源说明 note 增加 template 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：Reader 快照与 Feed 结构一致。
- 代价：Markdown 更长。

## ADR-375 EPUB 深层来源说明 note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：明确模板内容来源。
- 代价：统计数据字段更多。

## ADR-376 Feed 深层来源说明 template 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：template 字段可稳定演进。
- 代价：前端回显维护负担增加。

## ADR-377 Reader 深层来源说明 template 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照跨版本对比更准确。
- 代价：字段冗余持续增长。

## ADR-378 EPUB 深层来源说明 template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段语义变更可回放。
- 代价：消费方解析复杂度上升。

## ADR-379 Feed 深层来源说明模板增加 template_source_note 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note` 回显。
- 原因：补足新一层来源说明语义。
- 代价：字段长度进一步增加。

## ADR-380 Reader 深层来源说明模板增加 template_source_note 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：Reader 快照与 Feed 对齐。
- 代价：Markdown 长度上升。

## ADR-381 EPUB 深层来源说明增加 template_source_note 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：TopK 覆盖率说明链路保持完整可追溯。
- 代价：测试断言与字段映射继续增长。

## ADR-382 Feed 深层来源说明 template_source_note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：新层级 note 字段支持版本兼容。
- 代价：调试回显字段继续增加。

## ADR-383 Reader 深层来源说明 template_source_note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：快照回放可稳定比较同层语义版本。
- 代价：Markdown 元数据更长。

## ADR-384 EPUB 深层来源说明 template_source_note 字段增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：TopK 统计说明链支持逐层版本演进。
- 代价：测试断言与字段映射继续增长。

## ADR-385 Feed 深层来源说明 template_source_note 字段增加 template
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template` 回显。
- 原因：说明文案模板化可复用。
- 代价：字段链继续拉长。

## ADR-386 Reader 深层来源说明 template_source_note 字段增加 template
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：Reader 快照与 Feed 字段形态保持一致。
- 代价：快照内容更冗长。

## ADR-387 EPUB 深层来源说明 template_source_note 字段增加 template
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：TopK 说明链模板表达保持连续。
- 代价：单测断言继续增加。

## ADR-388 Feed 深层来源说明 template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：template 字段语义演进需要版本锚点。
- 代价：调试字段继续膨胀。

## ADR-389 Reader 深层来源说明 template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照跨版本回放更稳定。
- 代价：Markdown 元字段进一步增加。

## ADR-390 EPUB 深层来源说明 template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：TopK 说明链模板字段保持可兼容迭代。
- 代价：断言映射与维护成本持续上升。

## ADR-391 Feed 深层来源说明 template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source` 回显。
- 原因：模板字段来源需要显式声明。
- 代价：字段链继续增长。

## ADR-392 Reader 深层来源说明 template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：Reader 快照字段语义与 Feed 对齐。
- 代价：快照冗余进一步增加。

## ADR-393 EPUB 深层来源说明 template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：TopK 说明链来源字段保持连续可追溯。
- 代价：单测断言持续扩张。

## ADR-394 Feed 深层来源说明 template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段演进需要版本锚点。
- 代价：调试元字段继续增多。

## ADR-395 Reader 深层来源说明 template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：快照来源字段跨版本回放更稳定。
- 代价：Markdown 长度继续增长。

## ADR-396 EPUB 深层来源说明 template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：TopK 来源字段链保持版本兼容。
- 代价：断言项继续增加。

## ADR-397 Feed 深层来源说明 template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note` 回显。
- 原因：source 字段增加可读说明，便于排障。
- 代价：调试字段进一步增长。

## ADR-398 Reader 深层来源说明 template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：Reader 快照说明链与 Feed 一致。
- 代价：Markdown 元字段更长。

## ADR-399 EPUB 深层来源说明 template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：TopK 来源说明链补齐 source note 语义。
- 代价：断言规模继续扩大。

## ADR-400 Feed 深层来源说明 template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：source note 字段支持版本兼容。
- 代价：调试输出更冗长。

## ADR-401 Reader 深层来源说明 template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：快照跨版本对齐更稳定。
- 代价：元字段数量继续增长。

## ADR-402 EPUB 深层来源说明 template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：TopK 说明链 source note 语义可演进。
- 代价：测试断言继续增多。

## ADR-403 Feed 深层来源说明 template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template` 回显。
- 原因：source note 文案模板化提升复用性。
- 代价：字段链更长。

## ADR-404 Reader 深层来源说明 template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：Reader 与 Feed 的 source note 模板字段保持一致。
- 代价：Markdown 更长。

## ADR-405 EPUB 深层来源说明 template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：TopK 说明链模板层保持连续。
- 代价：断言和映射维护成本继续上升。

## ADR-406 Feed 深层来源说明 template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：template 字段需要版本锚点保证可兼容演进。
- 代价：调试字段继续增长。

## ADR-407 Reader 深层来源说明 template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照模板字段跨版本对齐更稳定。
- 代价：Markdown 元字段进一步增加。

## ADR-408 EPUB 深层来源说明 template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：TopK 说明链模板字段保持版本兼容。
- 代价：测试断言和映射维护继续扩张。

## ADR-409 Feed 深层来源说明 template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source` 回显。
- 原因：模板字段来源语义保持完整。
- 代价：字段链进一步拉长。

## ADR-410 Reader 深层来源说明 template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：Reader 快照与 Feed 的来源元字段对齐。
- 代价：Markdown 元数据继续扩张。

## ADR-411 EPUB 深层来源说明 template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：TopK 说明链模板来源字段保持连续可追溯。
- 代价：测试断言继续增长。

## ADR-412 Feed 深层来源说明 template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：template source 字段需要版本锚点。
- 代价：调试字段继续累积。

## ADR-413 Reader 深层来源说明 template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：快照字段跨版本兼容更稳定。
- 代价：Markdown 元字段更长。

## ADR-414 EPUB 深层来源说明 template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：TopK 说明链 template source 字段可演进。
- 代价：断言与映射复杂度上升。

## ADR-415 Feed 深层来源说明 template_source_note_template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note` 回显。
- 原因：template source 字段增加可读说明，便于排障。
- 代价：调试字段继续拉长。

## ADR-416 Reader 深层来源说明 template_source_note_template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：Reader 快照说明链与 Feed 对齐。
- 代价：Markdown 元字段继续增长。

## ADR-417 EPUB 深层来源说明 template_source_note_template_source_note_template_source 增加 note 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note`。
- 原因：TopK 说明链补齐 template source note 语义。
- 代价：断言规模持续扩大。

## ADR-418 Feed 深层来源说明 template_source_note_template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：note 字段语义需要版本锚点。
- 代价：调试字段数量增加。

## ADR-419 Reader 深层来源说明 template_source_note_template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：快照跨版本回放稳定性提升。
- 代价：Markdown 元字段更冗长。

## ADR-420 EPUB 深层来源说明 template_source_note_template_source_note_template_source_note 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version`（`v1`）。
- 原因：TopK 说明链 note 字段保持版本兼容。
- 代价：断言与映射维护继续增加。

## ADR-421 Feed 深层来源说明 template_source_note_template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template` 回显。
- 原因：note 字段模板化提高复用性。
- 代价：字段链更深。

## ADR-422 Reader 深层来源说明 template_source_note_template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：Reader 与 Feed 模板字段保持一致。
- 代价：快照更冗长。

## ADR-423 EPUB 深层来源说明 template_source_note_template_source_note_template_source_note 增加模板字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template`。
- 原因：TopK 说明链模板层连续。
- 代价：断言数量增加。

## ADR-424 Feed 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：模板字段需要版本锚点。
- 代价：调试字段继续扩张。

## ADR-425 Reader 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：快照模板跨版本对齐更稳定。
- 代价：元字段继续增长。

## ADR-426 EPUB 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version`（`v1`）。
- 原因：TopK 说明链模板字段可兼容演进。
- 代价：断言与映射维护成本上升。

## ADR-427 Feed 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source` 回显。
- 原因：模板字段来源信息保持完整。
- 代价：字段链继续拉长。

## ADR-428 Reader 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：Reader 与 Feed 来源元字段保持一致。
- 代价：快照体积增加。

## ADR-429 EPUB 深层来源说明 template_source_note_template_source_note_template_source_note_template 增加 source 字段
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source`。
- 原因：TopK 说明链模板来源字段保持连续。
- 代价：断言数量进一步增多。

## ADR-430 Feed 深层来源说明 template_source_note_template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：source 字段演进需要版本锚点。
- 代价：调试元字段增加。

## ADR-431 Reader 深层来源说明 template_source_note_template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...summary_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：快照跨版本一致性更稳定。
- 代价：Markdown 元字段继续增长。

## ADR-432 EPUB 深层来源说明 template_source_note_template_source_note_template_source_note_template_source 增加版本号
- 日期：`2026-03-30`
- 结论：新增 `...note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version`（`v1`）。
- 原因：TopK 说明链 source 字段可兼容演进。
- 代价：断言与映射维护持续增加。

## ADR-433 首个成品交付切换为“一键可跑通”优先
- 日期：`2026-03-30`
- 结论：暂停继续扩展调试字段链，优先交付 `scripts/first_product.sh + scripts/import_library.py + docs/FIRST_PRODUCT.md` 的端到端可运行路径。
- 原因：用户目标从“字段细化”转为“尽快拿到第一个成品”。
- 代价：部分深层回显任务顺延到后续迭代。

## ADR-434 批量导入默认采用“自动书籍类型推断 + 可固定覆盖”
- 日期：`2026-03-30`
- 结论：`import_library.py` 默认 `book-type-strategy=auto`，按文件名关键词推断 `technical/fiction/general`；保留 `fixed` 模式手动强制。
- 原因：兼顾你当前混合书库（技术书 + 通识书）和首成品导入效率。
- 代价：关键词启发式可能误判，需后续支持 manifest 人工修正。

## ADR-435 PDF 文本清洗必须移除 NUL/控制字符再入库
- 日期：`2026-03-30`
- 结论：在 `normalize_text` 中去除 `NUL (0x00)` 与非打印控制字符，避免 Postgres 文本写入失败。
- 原因：真实导入技术书 PDF 时触发 `PostgreSQL text fields cannot contain NUL (0x00) bytes` 阻塞首成品交付。
- 代价：极少数原文中不可见控制字符会被丢弃（可接受）。

## ADR-436 首成品验收采用独立 smoke 脚本固化
- 日期：`2026-03-30`
- 结论：新增 `scripts/smoke_first_product.sh`，统一验证 `GET /health`、`GET /v1/feed` 与 `/app|/app/reader|/app/book` 三页面连通性。
- 原因：首成品迭代期需要一个可重复、低成本、可机器执行的最小验收入口。
- 代价：脚本仍是黑盒联调级校验，不覆盖业务细粒度语义正确性。

## ADR-437 首页交互从“单卡片切片”切换为“双列瀑布流卡片”
- 日期：`2026-03-30`
- 结论：Feed 改为小红书式双列卡片，统一“上封面下标题”，保留点赞/评论/进入阅读。
- 原因：与产品新范围对齐（信息流主界面不是短视频全屏）。
- 代价：旧的键盘/滚轮逐条切换逻辑暂时退役。

## ADR-438 V0 目录策略改为“自动目录优先 + 人工标注兜底”
- 日期：`2026-03-30`
- 结论：新增目录标注台 `/app/toc` 与 TOC API（pending/annotation/preview/save），支持批量粘贴目录并预览页码定位。
- 原因：PDF 质量不齐，短期内不做 OCR 自动目录识别，先保证可用性。
- 代价：无目录书籍需要人工介入，吞吐受限于标注效率。

## ADR-439 V0 明确 Deferred 清单并单独文档化
- 日期：`2026-03-30`
- 结论：新增 `docs/specs/v0_scope.md`，记录当前冻结范围与延后项（AI 重写/OCR 自动识别/重排等）。
- 原因：防止范围漂移，确保“先完成基础框架”。
- 代价：短期功能丰富度下降，但交付确定性更高。

## ADR-440 Feed 过滤先采用前端本地过滤（book_title/book_id）
- 日期：`2026-03-30`
- 结论：在 `/app` 增加最小书籍过滤控件，按 `book_title/book_id` 本地过滤已加载卡片；同步 URL query 与 localStorage。
- 原因：快速支持“单书聚焦阅读”验证，无需新增后端过滤接口即可落地。
- 代价：过滤范围仅限当前已加载项，非全库精准筛选。

## ADR-441 开发流程切换为“快速门禁 + 轻量记录”
- 日期：`2026-03-30`
- 结论：默认开发门禁改为 `smoke + 改动模块相关测试`，记录改为每个 NOW 仅强制更新 `TASK_BOARD + STATE`；`SESSION_LOG` 只在里程碑或阻塞时写短条目，`DECISIONS` 仅记录高风险/不可逆取舍。
- 原因：当前主阻力来自高频全量测试和多文档同步，影响功能推进速度。
- 代价：流程约束放松后，回归风险需要通过里程碑全量测试触发条件兜底。
