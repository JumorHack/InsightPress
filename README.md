# InsightPress

PDF 进，结构化书评（Markdown）出。8 阶段流水线，每条建议都**具体可执行 + 绑定原文证据 + 指明适用场景**，并附**红队批判**指出建议的隐藏假设和反例。不是泛泛摘要。

## 0. 前置条件

- Python ≥ 3.11
- LLM API key（任选一）：
  - **DeepSeek**：`https://platform.deepseek.com/` 申请 → key 形如 `sk-xxx`，便宜但有 reasoning 模型偶发性问题
  - **Anthropic 官方**：`https://console.anthropic.com/` 申请 → key 形如 `sk-ant-xxx`
- PDF 必须**带文字层**（图书馆扫描件暂不支持）

## 1. 安装

```bash
# 克隆并进入目录
git clone https://github.com/JumorHack/InsightPress.git
cd InsightPress

# 创建虚拟环境 + 装依赖
python3 -m venv .venv
.venv/bin/pip install -e .

# 配置 API key
cp .env.example .env
# 编辑 .env，至少填 ANTHROPIC_API_KEY；用 DeepSeek 还要把 ANTHROPIC_BASE_URL 取消注释
```

`.env` 示例（DeepSeek）：
```
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
```

`.env` 示例（Anthropic 官方）：
```
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_BASE_URL 不用填
```

## 2. 启动 + 跑一次

```bash
.venv/bin/uvicorn backend.main:app --reload --port 8000
```

浏览器打开 http://localhost:8000，会看到：

1. **上传区** — 选书种（MVP 仅"致用类"开放）+ 选 PDF + 「开始生成」
2. **进度区** — 8 个阶段实时高亮；门控不通过会触发重试，进度文字会显示「质量门控重试 1/2」
3. **预览区** — 流水线结束后渲染 Markdown，可下载 `.md`

**典型耗时**：单本 30 万字中文书约 5-10 分钟（含 1-2 次重试）。

## 3. 怎么挑测试 PDF

**好的测试候选**（流水线对它们效果最好）：

- **致用类中文书**：时间管理 / 写作方法 / 沟通技巧 / 健身指南这类「方法论 + 案例」结构。例如《深度工作》《非暴力沟通》《原子习惯》《卡片笔记写作法》。
- **页数 50-300 页**：太短抽不出 3-5 条核心建议（会触发"未抽取到原则"错误），太长 token 成本高。

**会失败或效果差的**：

- **小说 / 散文 / 历史 / 哲学**：MVP 还没实现叙事/理论/工具类的 prompt，会被前端 disabled 掉
- **扫描件**：stage 1 检测到文字 < 500 字符直接报错
- **教科书 / 工具书**：充满目录、公式、表格，pdfplumber 抽出来一团乱
- **超长书**（> 50 万字）：token 成本可能超 ¥10，且容易超 LLM 上下文

## 4. 测试时观察什么

**正常通过的标志**：
- 8 个阶段全绿
- 最终 Markdown 头部 `质量评分: 7-9/10` + `门控结论: pass`
- 3-5 条核心建议，每条都有「适用场景 / 不适用 / 原文证据」三段
- 「批判」段给出具体反例（不是"因人而异"这种废话）

**警告信号**（产出还能用，但建议留意）：
- `门控结论: warn` — 评分在 5-7，建议至少有一处不够具体
- `门控结论: fail` 但 `overall_score >= 5` — 通常是 evidence 维度偏低（synthesis 没把 quotes 池里的金句用上，是已知 prompt 问题）

**失败模式**（应该看 artifacts/ 排查）：
- `质量评分: 0/10` + 「核心论点」是 `（无法合成：未抽取到任何...）` → stage 4 抽取空，详见下面 #6
- 流水线中途报错 → 进度文字会显示具体阶段和错误信息

## 5. 调试：每个阶段的产物落盘在哪

每次任务的中间结果都存在 `artifacts/{job_id}/`：

```
artifacts/abc123def456/
├── input.pdf
├── stage1_parsed.json          # PDF 解析后的结构化文本 + 元数据
├── stage2_classification.json  # 用户选的书种
├── stage3_chunks.json          # 切分后的文本块
├── stage4_extractions.json     # 每块抽取的 principles / evidence / quotes / claims
├── stage5_synthesis.json       # 合成的核心论点 + 3-5 条建议
├── stage6_critique.json        # 红队批判
├── stage7_gate.json            # 四维评分 + verdict
├── stage5_synthesis_retry1.json   # 如果触发了重试，每次 retry 单独存盘
├── stage5_synthesis_retry2.json
├── ...
└── review.md                   # 最终输出
```

**job_id** 在浏览器请求 `/api/jobs` 的响应里，也能从 uvicorn 日志看到。

## 6. 常见问题排查

**Q: 进度卡在 stage 4，最后报"未抽取到任何原则"**

stage 4 用 LLM 给每个文本块做结构化抽取，DeepSeek v4-flash 偶发"调 tool 但传空参数"是已知 transient bug。代码已经有 4 次重试，但极端情况下还是会全部失败。

排查：看 [artifacts/{job_id}/stage3_chunks.json](artifacts/) 里 chunks 是不是合理（不是空的、不是只有目录页）。如果 chunks 正常但 stage 4 空，重试一次任务通常就好。

**Q: verdict 永远是 fail，evidence 维度都是 1-3**

已知问题：stage 5 prompt 没强制要求每条建议都配 1 条 evidence_quote，导致 4 维评分里 evidence 维度长期偏低。可以接受 fail 但 overall ≥ 5 的输出（实际内容质量是 OK 的），或者等后续 prompt 优化。

**Q: 上传后 SSE 连接断了**

uvicorn 默认有 keepalive timeout。`--timeout-keep-alive 600` 启动可以延长。或者刷新页面重连 — 后端 BackgroundTasks 还在跑，artifacts 会继续生成，但前端进度会丢。

**Q: 想测新 PDF 但不想等几分钟**

把 PDF 裁剪成前 30-50 页测试。或单独跑某一阶段：
```bash
.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
from backend.pipeline import stage4_extract
from backend.schemas import ChunkSet
import json
chunks = ChunkSet(**json.load(open('artifacts/<job_id>/stage3_chunks.json')))
for ext in stage4_extract.run(chunks):
    print(ext.model_dump())
"
```

## 7. 成本估算（DeepSeek）

单本中文书约 ¥2-5：
- Stage 4: 每个 chunk 1 次 v4-flash 调用，6 个 chunk × ~3000 tokens ≈ ¥0.5
- Stage 5: 1 次 v4-pro 调用，~10000 tokens ≈ ¥1
- Stage 6+7: 各 1 次 v4-flash，~5000 tokens × 2 ≈ ¥0.5
- 触发重试 ×2 ≈ ¥1-2 加价
- 用 Anthropic 官方约贵 5-10 倍

## 8. 流水线阶段简介

| 阶段 | 输入 → 输出 | 模型 |
|---|---|---|
| 1 PDF 解析 | PDF → ParsedBook | 无 LLM |
| 2 书种分类 | 用户选择 | 无 LLM |
| 3 智能切分 | ParsedBook → ChunkSet | 无 LLM |
| 4 逐块提取 | ChunkSet → List[ChunkExtraction] | v4-flash 并发 ≤10 |
| 5 合成与去重 | List[ChunkExtraction] → Synthesis | v4-pro |
| 6 批判性分析 | Synthesis → Critique | v4-flash |
| 7 质量门控 | Synthesis → GateVerdict | v4-flash（独立 session，judge 不知是 AI 写的） |
| 8 模板渲染 | 全部 → Markdown | Jinja，零 LLM |

详见 [CLAUDE.md](CLAUDE.md)。

## 9. MVP 范围限制

- 单本、单用户、单线（不并发）
- 仅"致用类"模板（叙事/理论/工具类前端可见但 disabled）
- 中文优先（prompt 都是中文）
- 文件系统而非数据库
- BackgroundTasks 而非 Celery/Redis
- 无登录、无 quota、无监控
- 不打包 Docker

要扩到多用户多书并发，看 [CLAUDE.md](CLAUDE.md) 的「禁止事项」一节决定要不要加哪些基础设施。
