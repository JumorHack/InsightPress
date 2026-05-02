# InsightPress

PDF 进，结构化书评（Markdown）出。8 阶段流水线，强调**可执行的具体建议**与**批判性分析**，不是泛泛摘要。

## 快速开始

```bash
# 1. 安装依赖（推荐 uv）
uv sync
# 或
pip install -e .

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY

# 3. 启动服务
uvicorn backend.main:app --reload --port 8000

# 4. 浏览器打开
open http://localhost:8000
```

## 使用

1. 上传一本带文字层的 PDF（扫描件暂不支持）
2. 等待 8 阶段流水线跑完（实时进度）
3. 在线预览或下载 Markdown 书评

## 流水线阶段

1. 输入解析（PDF → 结构化文本）
2. 解析与分类（书种识别）
3. 智能切分
4. 逐块提取（Map）
5. 合成与去重（Reduce）
6. 批判性分析
7. 质量门控
8. 模板渲染（Jinja，零 LLM）

详见 [CLAUDE.md](CLAUDE.md)。

## 范围

MVP 阶段单本、单用户、单线流水线。不做账户、队列、数据库、Docker。
