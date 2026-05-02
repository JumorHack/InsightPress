import asyncio
import uuid

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .config import ARTIFACTS_DIR, PROJECT_ROOT
from .pipeline.orchestrator import JOBS, JobChannel, run_pipeline

load_dotenv()

app = FastAPI(title="InsightPress")

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/jobs", status_code=201)
async def create_job(file: UploadFile, background_tasks: BackgroundTasks):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")

    job_id = uuid.uuid4().hex[:12]
    job_dir = ARTIFACTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "文件为空")
    (job_dir / "input.pdf").write_bytes(pdf_bytes)

    JOBS[job_id] = JobChannel()
    background_tasks.add_task(run_pipeline, job_id)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "未找到任务")
    channel = JOBS[job_id]

    async def gen():
        async for ev in channel.stream():
            yield ev

    return EventSourceResponse(gen())


@app.get("/api/jobs/{job_id}/review")
async def get_review(job_id: str):
    path = ARTIFACTS_DIR / job_id / "review.md"
    if not path.exists():
        raise HTTPException(404, "书评尚未生成完成")
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@app.get("/api/jobs/{job_id}/review.md")
async def download_review(job_id: str):
    path = ARTIFACTS_DIR / job_id / "review.md"
    if not path.exists():
        raise HTTPException(404, "书评尚未生成完成")
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=f"review-{job_id}.md",
    )


# 静态前端兜底（必须最后挂载，否则会吞掉 /api/* 路由）
app.mount(
    "/",
    StaticFiles(directory=str(PROJECT_ROOT / "frontend"), html=True),
    name="frontend",
)
