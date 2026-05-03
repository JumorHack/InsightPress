from pathlib import Path

# 书种 — MVP 只完整支持 practical（致用类）。其余 3 种留位以便未来扩展。
GENRE_LABELS = {
    "practical": "致用类",
    "narrative": "叙事类",
    "theory": "理论类",
    "reference": "工具类",
}
SUPPORTED_GENRES = {"practical"}  # 当前模板能处理的书种

# 模型选用（当前接 DeepSeek 的 Anthropic 兼容端点；切回官方 Claude 改这里 + .env 的 base URL）
MAIN_MODEL = "deepseek-v4-pro"
CHEAP_MODEL = "deepseek-v4-flash"
JUDGE_MODEL = "deepseek-v4-pro"

# Anthropic 官方支持 prompt caching（cache_control: ephemeral）；DeepSeek 兼容端点不一定支持。
# 如果调用报 cache_control 相关错，关掉这个开关。
ENABLE_PROMPT_CACHING = False

# 质量门控阈值
GATE_MIN_DIMENSION_SCORE = 5
GATE_MIN_OVERALL_SCORE = 7
GATE_MAX_RETRIES = 2

# 切分参数
CHUNK_TARGET_TOKENS = 2000
CHUNK_OVERLAP_TOKENS = 200

# 并发
MAP_PHASE_CONCURRENCY = 10

# 引文限制（版权红线）
MAX_QUOTE_CHARS_ZH = 25
MAX_QUOTE_WORDS_EN = 15
MAX_TOTAL_QUOTES_CHARS = 200

# 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
PROMPTS_DIR = PROJECT_ROOT / "backend" / "prompts"
TEMPLATES_DIR = PROJECT_ROOT / "backend" / "templates"
