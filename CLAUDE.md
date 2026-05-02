# CLAUDE.md

> 本文件是 Claude Code 在本仓库工作时的指南。开发前请通读一遍，特别是「核心不变量」与「禁止事项」两节。

## 项目目标

一个最小可用的 AI 书评生成器：

1. 用户通过简易网页上传 PDF 书籍
2. 后端 8 阶段流水线把 PDF 转成结构化书评（Markdown）
3. 网页实时显示生成进度，完成后即时渲染 Markdown 预览
4. 用户可以下载最终 `.md` 文件

**产品差异化**：不只生成"摘要"，要生成带**对读者人生有益的具体建议**和**批判性分析**的真书评。这是和市面上 90% AI 拆书工具的核心区别——细节见「书评质量铁律」一节。

## MVP 范围（务必遵守，不要扩张）

**做**：
- PDF 输入（含文字层；扫描件先拒绝，不做 OCR）
- 单本处理，单用户
- 全流程 8 阶段（输入 → 解析与分类 → 切分 → 提取 → 合成 → 批判 → 门控 → 渲染）
- 单一书种模板（致用类优先；其他三种留 stub 不实现）
- 网页：上传 + 进度（SSE）+ Markdown 预览 + 下载
- 中文书优先，但代码不写死中文

**不做**：
- 用户账户、登录、权限
- 数据库（用文件系统）
- 任务队列（用 FastAPI BackgroundTasks）
- 多语言切换（生成阶段都用中文 prompt）
- 外部元数据增强（不接 豆瓣/Goodreads/Google Books）
- 多种输出格式（只输出一份完整 Markdown，不做精简版/行动版）
- 缓存优化（除 Anthropic prompt caching 之外不做）
- Docker 化、CI/CD、监控（首版跑得起来再说）

砍这些不是因为不重要，而是 MVP 阶段加了反而拖慢迭代。功能扩展前先验证产品-市场契合度。

## 技术栈

```
Python      ≥ 3.11
FastAPI     ≥ 0.110
uvicorn     ≥ 0.27
anthropic   最新版（要支持 prompt caching 和 tool use）
pdfplumber  ≥ 0.11
pypdf       ≥ 4.0    （兜底元数据提取）
pydantic    ≥ 2.6
jinja2      ≥ 3.1
sse-starlette ≥ 2.0
python-dotenv ≥ 1.0
python-multipart 最新（FastAPI 文件上传依赖）

前端：纯 HTML + 原生 JS + marked.js（CDN）
```

**Anthropic 模型选用**（当前生产可用）：
- 主流程：`claude-sonnet-4-6` —— 合成、批判性分析、质量评判
- 廉价阶段：`claude-haiku-4-5-20251001` —— 书种分类、逐块提取（Map）

模型字符串放在 `backend/config.py` 的常量里，不要硬编码到调用点。

## 项目结构

```
.
├── CLAUDE.md                  # 本文件
├── README.md                  # 用户向，简单说明怎么跑
├── .env.example               # ANTHROPIC_API_KEY=sk-ant-...
├── pyproject.toml             # 依赖与项目元信息
├── backend/
│   ├── __init__.py
│   ├── main.py                # FastAPI app 入口
│   ├── config.py              # 配置常量（模型名、阈值、目录路径）
│   ├── schemas.py             # Pydantic 数据契约（贯穿所有阶段）
│   ├── llm_client.py          # 唯一的 Anthropic 调用封装
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # 串联所有阶段，发 SSE 进度
│   │   ├── stage1_input.py    # PDF 解析 → ParsedBook
│   │   ├── stage2_classify.py # 元数据 + 书种分类
│   │   ├── stage3_chunk.py    # 智能切分
│   │   ├── stage4_extract.py  # Map：逐块提取
│   │   ├── stage5_synthesize.py  # Reduce：合成核心建议
│   │   ├── stage6_critique.py    # 批判性分析
│   │   ├── stage7_gate.py     # 质量门控（LLM-as-judge）
│   │   └── stage8_render.py   # Jinja 模板渲染
│   ├── prompts/               # 所有 prompt 都从文件加载，不硬编码
│   │   ├── classify.txt
│   │   ├── extract_practical.txt
│   │   ├── synthesize.txt
│   │   ├── critique.txt
│   │   └── judge.txt
│   ├── templates/             # Jinja2 输出模板
│   │   └── practical.md.jinja
│   └── utils/
│       ├── pdf.py             # PDF 解析与章节启发式
│       ├── chunking.py        # 切分逻辑（含 token 计数）
│       └── quote_validator.py # 引文长度上限检查（版权红线）
├── frontend/
│   ├── index.html             # 单页：上传 + 进度 + 预览
│   ├── app.js                 # 上传逻辑 + SSE 监听 + Markdown 渲染
│   └── style.css
└── artifacts/                 # 运行时生成（.gitignore）
    └── {job_id}/
        ├── input.pdf
        ├── stage1_parsed.json
        ├── stage2_classification.json
        ├── stage3_chunks.json
        ├── stage4_extractions.json
        ├── stage5_synthesis.json
        ├── stage6_critique.json
        ├── stage7_gate.json
        └── review.md          # 最终输出
```

## 核心数据契约

每个阶段都是纯函数 `stage_n(input: PydanticModel) -> PydanticModel`。所有跨阶段数据必须经过 `backend/schemas.py` 里定义的 Pydantic 模型。**不允许阶段之间传字典**——出了问题没法定位。

关键 schema 名称（细节实现时定义）：

- `ParsedBook` — 阶段 1 输出：metadata + chapters + raw_text
- `BookClassification` — 阶段 2 输出：四类书种概率分布
- `ChunkSet` — 阶段 3 输出：chunks 列表（含 chunk_id、char_range、context_before）
- `ChunkExtraction` — 阶段 4 单块输出：principles / evidence / quotes / claims
- `Synthesis` — 阶段 5 输出：core_thesis / target_audience / core_advice
- `Critique` — 阶段 6 输出：per_advice_critique / factual_issues / alternative_books
- `GateVerdict` — 阶段 7 输出：pass/warn/fail + per_advice_scores

**每个阶段开始时验证输入、结束时序列化输出到 `artifacts/{job_id}/stageN_*.json`**。这一步是为了：
1. 调试时能从任意阶段重启
2. 改 prompt 后只重跑相关阶段，不浪费 token
3. 用户报错时能回溯具体是哪个阶段的问题

## 流水线职责（高层）

只列每阶段的"输入 → 输出"和"必须做的事"。具体 prompt 设计放到 `backend/prompts/` 里迭代。

| 阶段 | 输入 | 输出 | 关键动作 |
|---|---|---|---|
| 1. 输入解析 | PDF 文件 | ParsedBook | pdfplumber 提取文本，启发式重建章节树（PDF outline → TOC 页 → 字号聚类，按优先级降级） |
| 2. 解析与分类 | ParsedBook | BookClassification | LLM 单次调用（haiku），输入封面 + 目录 + 第一章前 1500 字，输出四类概率分布 |
| 3. 智能切分 | ParsedBook | ChunkSet | 章节优先，无章节降级到语义切分；每块 ~2000 tokens；保留 200 tokens 重叠（给 context_before 字段） |
| 4. 逐块提取 | ChunkSet | List[ChunkExtraction] | 并发调用 haiku（≤10 并发），强制 tool use 输出 schema；每条抽取必须有 source_span（原文 5-30 字片段） |
| 5. 合成与去重 | List[ChunkExtraction] | Synthesis | embedding 聚类去重 → LLM (sonnet) 在每组里挑代表 → 选 3-5 条核心建议 |
| 6. 批判性分析 | Synthesis + ParsedBook | Critique | LLM (sonnet) 红队提示词；MVP 阶段**禁用 web search**，纯内部分析；逐条建议判定 立得住/部分立得住/不同意 |
| 7. 质量门控 | Synthesis + Critique | GateVerdict | LLM (sonnet) 四维评分（具体/证据/行动/反空泛），任一维 < 5 或总分 < 7 触发重试，N=2 |
| 8. 模板渲染 | Synthesis + Critique + GateVerdict | review.md | **Jinja2 渲染，不调 LLM**；引文长度自动截短 |

## 核心不变量（任何修改都不能破坏）

1. **阶段隔离**：阶段 N 不允许直接调用阶段 M（M ≠ N-1）。所有依赖通过 orchestrator 串联。
2. **LLM 调用唯一入口**：所有 Anthropic 调用走 `backend/llm_client.py`。要换 provider 或加日志时改一处。
3. **Prompt 外置**：prompt 一律放 `backend/prompts/*.txt`，代码里只用 `load_prompt("name")` 加载。便于不改代码迭代 prompt。
4. **Source span 必验证**：阶段 4 提取的每条 `source_span` 字段必须是原文 substring（允许全角半角差异和连续空白归一化），不通过的条目丢弃或重试。这是防幻觉的最后防线。
5. **Judge 与生成隔离**：阶段 7 的 LLM 调用必须新开 session，prompt 里**不许出现"AI 生成"或"自动生成"字样**——让 judge 以为在评一篇人写的书评。
6. **不让 LLM 渲染最终 Markdown**：阶段 8 用 Jinja 模板，零 LLM 调用。引入 LLM 会污染所有前面的质量门控成果。
7. **每阶段产物落盘**：阶段成功后把输出 JSON 写到 `artifacts/{job_id}/stageN_*.json`。调试和重跑都靠它。
8. **进度 SSE 颗粒度到阶段**：8 个阶段每完成一个推一次进度事件 `{stage: 4, status: "done", percent: 50}`。阶段内不推。

## 书评质量铁律

这是产品质量的硬约束，不是建议。Prompt 设计、judge 评分、模板渲染都要服从。

**每条核心建议必须满足**：

1. **具体到可执行**："每周三 20:00 复盘"，不是"做好复盘"
2. **绑定原文证据**：必须能引用书中具体故事、数据、案例
3. **指明适用场景**：这条对谁有用？什么情况下不适用？
4. **删掉书名仍然成立 = 万能废话**：judge 阶段的反向探针专门抓这个

**禁止输出**：

- 抽象到任何书都能说的建议（"保持自律"、"持续学习"、"相信自己"）
- 营销腔过渡句（"这本书将彻底改变你的人生"）
- 没有原文支撑的论断（即使听起来有道理）
- 第一人称内容（"我认为"、"我建议"）—— 用户上传的书可能含自己的批注，过滤掉
- 引文超过 25 个汉字 / 15 个英文词（版权硬上限）

## 版权红线（不能违反）

- 单条引文 ≤ 25 汉字 / 15 英文词，超出自动截短并加省略号
- 单篇书评所有引文累计 ≤ 200 汉字
- 引文必须标出处（章节）：`> "..."  ——《书名》第 X 章`
- 不输出整段或整页的"摘录"
- `backend/utils/quote_validator.py` 在阶段 8 渲染前做最后一道检查

商业化前要做完整版权审查。MVP 阶段假设用户上传的是自己合法持有的书。

## API 设计

```
POST /api/jobs
  body: multipart/form-data, file=<PDF>
  → 201 { "job_id": "..." }

GET /api/jobs/{job_id}/events
  SSE stream:
    event: progress
    data: { "stage": 1-8, "stage_name": "...", "status": "running|done|error", "percent": 0-100 }
    event: complete
    data: { "review_url": "/api/jobs/{job_id}/review" }
    event: error
    data: { "stage": N, "message": "..." }

GET /api/jobs/{job_id}/review
  → text/markdown，最终书评内容

GET /api/jobs/{job_id}/review.md
  → text/markdown，Content-Disposition: attachment（下载）

# 静态资源
GET /  → frontend/index.html
GET /app.js, /style.css → 对应文件
```

## 常用命令

```bash
# 安装依赖（推荐 uv，pip 也行）
uv sync                          # 或 pip install -e .

# 复制环境变量
cp .env.example .env             # 然后编辑填入 ANTHROPIC_API_KEY

# 启动开发服务器
uvicorn backend.main:app --reload --port 8000

# 浏览器打开
open http://localhost:8000

# 单阶段调试（不走完整流水线，直接跑某一阶段）
python -m backend.pipeline.stage4_extract --input artifacts/abc123/stage3_chunks.json

# 清理产物
rm -rf artifacts/*
```

## 禁止事项

不要在没有显式确认前做以下任何一件：

1. **不要引入数据库**（SQLite 都不要）。MVP 文件系统就够。
2. **不要引入任务队列**（Celery / RQ / Redis）。用 FastAPI BackgroundTasks。
3. **不要引入前端框架**（React / Vue / Svelte）。一个 HTML + 一个 JS。
4. **不要引入构建工具**（webpack / vite / esbuild）。原生 ES modules + CDN。
5. **不要硬编码 prompt 在 .py 文件里**。一律外置。
6. **不要让 LLM 写最终 Markdown**。Jinja 模板渲染。
7. **不要在阶段 8 之后做"美化"或"润色"调用**。会把锐利变中庸。
8. **不要在 judge prompt 里塞 few-shot 示例**。会引入示例偏差，规则讲清楚就够。
9. **不要为了"完整性"加用户登录、配额、限流**。单用户夹具优先。
10. **不要追求 100% 测试覆盖率**。先跑通端到端 happy path，再补关键模块测试（utils/quote_validator、utils/chunking）。
11. **不要并发处理多本书**。单 worker 一次处理一本。多用户并发是后期问题。
12. **不要在错误时重试整条流水线**。失败回退到失败的阶段，前面阶段的 JSON 落盘可复用。

## 配置项（在 backend/config.py 中集中管理）

```python
# 模型选用
MAIN_MODEL = "claude-sonnet-4-6"
CHEAP_MODEL = "claude-haiku-4-5-20251001"
JUDGE_MODEL = "claude-sonnet-4-6"   # 暂用同模型，未来可换 GPT-4 提高隔离

# 阈值
GATE_MIN_DIMENSION_SCORE = 5
GATE_MIN_OVERALL_SCORE = 7
GATE_MAX_RETRIES = 2

# 切分参数
CHUNK_TARGET_TOKENS = 2000
CHUNK_OVERLAP_TOKENS = 200

# 并发
MAP_PHASE_CONCURRENCY = 10

# 输出限制
MAX_QUOTE_CHARS_ZH = 25
MAX_QUOTE_WORDS_EN = 15
MAX_TOTAL_QUOTES_CHARS = 200

# 路径
ARTIFACTS_DIR = "./artifacts"
PROMPTS_DIR = "./backend/prompts"
TEMPLATES_DIR = "./backend/templates"
```

## 前端最简实现

`frontend/index.html` 三个区块：

1. **上传区**：`<input type="file" accept=".pdf">` + 提交按钮
2. **进度区**：8 个阶段名 + 当前阶段高亮 + 百分比条；通过 EventSource 连 `/api/jobs/{id}/events`
3. **预览区**：完成后调 `/api/jobs/{id}/review` 拿 markdown，用 `marked.parse()` 渲染到 `<div>`，提供下载按钮

不需要路由、状态管理、组件化。一个文件搞定。**所有用户可见文本用中文**（按钮、错误提示、进度文字）。

## 何时该问用户

- 改动涉及核心不变量
- 添加新依赖（特别是会增加部署复杂度的，比如 Redis、Postgres）
- 改动会破坏 API 兼容
- prompt 改动可能影响输出风格的（用户可能有积累的偏好）
- MVP 范围扩张

不需要问的：
- bug 修复
- 重构内部实现（不破坏接口）
- 加日志、改错误处理
- 写测试
- 改 README

## 已知风险与未解决问题

- **PDF 章节切分**是工程量最大的不确定因素，30% 的中文 PDF 启发式会出错。第一版可以接受降级到机械切分，但要在最终书评里标"章节切分置信度低"
- **扫描件**直接拒绝（前 10 页文字字符 < 500 判定为扫描件）。OCR 不在 MVP 范围
- **超长书**（> 500k tokens）直接拒绝，提示用户裁剪后重传
- **LLM 输出不稳定**导致同一本书多次跑出不同建议——可接受少量措辞差异，但核心建议不能换。如果观察到这种漂移，是阶段 5 的去重和排名稳定性问题
- **成本估算**：一本 30 万字中文书全流程约 300-500k tokens，用上述模型分层约 ¥3-7 / 本（按当前汇率）。第一版不做成本上限保护，自己测试时注意

---

最后一句：先把 happy path 跑通端到端（哪怕每个阶段的 prompt 都是占位符），再回头逐阶段优化质量。**不要追求每个阶段都完美再串起来**——这条 pipeline 的复杂度不在单阶段而在串联。
