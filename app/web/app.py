"""FastAPI Web 应用入口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.web.routers.translate import router as translate_router

app = FastAPI(title="orange-translator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(translate_router)

# 挂载前端静态文件（Vue 构建产物）
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    from fastapi.responses import JSONResponse

    @app.get("/")
    async def root():
        return JSONResponse({"message": "orange-translator API", "docs": "/docs"})
