import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from ..config import ARTIFACTS_DIR, GATE_MAX_RETRIES
from ..schemas import Genre
from . import (
    stage1_input,
    stage2_classify,
    stage3_chunk,
    stage4_extract,
    stage5_synthesize,
    stage6_critique,
    stage7_gate,
    stage8_render,
)

logger = logging.getLogger(__name__)


class JobChannel:
    """单 job 的事件广播：append-only list + condition 唤醒所有订阅者，支持迟到订阅重放历史。"""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.cond = asyncio.Condition()
        self.closed = False

    async def emit(self, event: str, data: dict) -> None:
        async with self.cond:
            self.events.append(
                {"event": event, "data": json.dumps(data, ensure_ascii=False)}
            )
            self.cond.notify_all()

    async def close(self) -> None:
        async with self.cond:
            self.closed = True
            self.cond.notify_all()

    async def stream(self):
        i = 0
        while True:
            async with self.cond:
                while i >= len(self.events) and not self.closed:
                    await self.cond.wait()
                while i < len(self.events):
                    yield self.events[i]
                    i += 1
                if self.closed:
                    return


JOBS: dict[str, JobChannel] = {}


def _percent(stage: int, status: str) -> int:
    # running 时显示进入该阶段时的百分比；done 时显示该阶段结束的百分比。
    base = (stage - 1) * 100 // 8 if status == "running" else stage * 100 // 8
    return base


def _save(job_dir: Path, name: str, obj: Any) -> None:
    if isinstance(obj, list):
        data = [o.model_dump() for o in obj]
    else:
        data = obj.model_dump()
    (job_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


STAGE_NAMES = {
    1: "PDF 解析",
    2: "书种分类",
    3: "智能切分",
    4: "逐块提取",
    5: "合成与去重",
    6: "批判性分析",
    7: "质量门控",
    8: "模板渲染",
}


async def run_pipeline(job_id: str, book_type: Genre = "practical") -> None:
    job_dir = ARTIFACTS_DIR / job_id
    pdf_path = job_dir / "input.pdf"
    channel = JOBS[job_id]

    async def announce(stage: int, status: str, attempt: int = 0) -> None:
        payload: dict[str, Any] = {
            "stage": stage,
            "stage_name": STAGE_NAMES[stage],
            "status": status,
            "percent": _percent(stage, status),
        }
        if attempt > 0:
            payload["attempt"] = attempt  # 重试时带上次数，前端可选地展示
        await channel.emit("progress", payload)

    current = 0
    try:
        current = 1
        await announce(1, "running")
        parsed = await asyncio.to_thread(stage1_input.run, pdf_path)
        _save(job_dir, "stage1_parsed.json", parsed)
        await announce(1, "done")

        current = 2
        await announce(2, "running")
        classification = await asyncio.to_thread(
            stage2_classify.run, parsed, book_type
        )
        _save(job_dir, "stage2_classification.json", classification)
        await announce(2, "done")

        current = 3
        await announce(3, "running")
        chunks = await asyncio.to_thread(stage3_chunk.run, parsed)
        _save(job_dir, "stage3_chunks.json", chunks)
        await announce(3, "done")

        current = 4
        await announce(4, "running")
        extractions = await asyncio.to_thread(stage4_extract.run, chunks, book_type)
        _save(job_dir, "stage4_extractions.json", extractions)
        # 守门：所有 chunk 都返回空 = 后面阶段全是空跑，直接报错
        total_items = sum(
            len(e.principles) + len(e.evidence) + len(e.quotes) + len(e.claims)
            for e in extractions
        )
        if total_items == 0:
            raise RuntimeError(
                "PDF 中未抽取到任何可用原则/证据/金句。可能是 PDF 内容过短、"
                "扫描件未文字化、或 LLM 多次返回空。请重试或换一份 PDF。"
            )
        await announce(4, "done")

        # ====== 合成 → 批判 → 门控 (5/6/7) 一组，gate 不通过则带反馈重跑 ======
        current = 5
        await announce(5, "running")
        synthesis = await asyncio.to_thread(
            stage5_synthesize.run, extractions, chunks, None, book_type
        )
        _save(job_dir, "stage5_synthesis.json", synthesis)
        await announce(5, "done")

        current = 6
        await announce(6, "running")
        critique = await asyncio.to_thread(
            stage6_critique.run, synthesis, parsed, book_type
        )
        _save(job_dir, "stage6_critique.json", critique)
        await announce(6, "done")

        current = 7
        await announce(7, "running")
        gate = await asyncio.to_thread(
            stage7_gate.run, synthesis, critique, parsed, book_type
        )
        _save(job_dir, "stage7_gate.json", gate)
        await announce(7, "done")

        for attempt in range(1, GATE_MAX_RETRIES + 1):
            if gate.verdict == "pass":
                break
            logger.info(
                "Gate verdict=%s overall=%d, retrying stages 5-7 (attempt %d/%d)",
                gate.verdict, gate.overall_score, attempt, GATE_MAX_RETRIES,
            )

            current = 5
            await announce(5, "running", attempt)
            new_synthesis = await asyncio.to_thread(
                stage5_synthesize.run, extractions, chunks, gate.notes, book_type
            )
            _save(job_dir, f"stage5_synthesis_retry{attempt}.json", new_synthesis)
            await announce(5, "done", attempt)

            current = 6
            await announce(6, "running", attempt)
            new_critique = await asyncio.to_thread(
                stage6_critique.run, new_synthesis, parsed, book_type
            )
            _save(job_dir, f"stage6_critique_retry{attempt}.json", new_critique)
            await announce(6, "done", attempt)

            current = 7
            await announce(7, "running", attempt)
            new_gate = await asyncio.to_thread(
                stage7_gate.run, new_synthesis, new_critique, parsed, book_type
            )
            _save(job_dir, f"stage7_gate_retry{attempt}.json", new_gate)
            await announce(7, "done", attempt)

            # 取最高分那一次：覆盖 canonical 文件，进 stage 8 用最好的
            if new_gate.overall_score > gate.overall_score:
                synthesis, critique, gate = new_synthesis, new_critique, new_gate
                _save(job_dir, "stage5_synthesis.json", synthesis)
                _save(job_dir, "stage6_critique.json", critique)
                _save(job_dir, "stage7_gate.json", gate)

        current = 8
        await announce(8, "running")
        markdown = await asyncio.to_thread(
            stage8_render.run, synthesis, critique, gate, classification, parsed
        )
        (job_dir / "review.md").write_text(markdown, encoding="utf-8")
        await announce(8, "done")

        await channel.emit("complete", {"review_url": f"/api/jobs/{job_id}/review"})
    except Exception as e:
        await channel.emit("error", {"stage": current, "message": str(e)})
    finally:
        await channel.close()
