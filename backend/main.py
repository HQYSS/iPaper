"""
iPaper Backend - FastAPI 入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import papers, chat, config, profile, translation, auth, preferences, sync
from services.sync_service import sync_service

# 创建 FastAPI 应用
app = FastAPI(
    title="iPaper API",
    description="论文阅读助手后端 API",
    version="0.1.0"
)

# CORS 配置（允许 Electron 前端访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(preferences.router, prefix="/api/preferences", tags=["preferences"])
app.include_router(papers.router, prefix="/api/papers", tags=["papers"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(translation.router, prefix="/api/papers", tags=["translation"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "message": "iPaper API is running"}


@app.on_event("startup")
async def startup_event():
    await sync_service.startup()


@app.on_event("shutdown")
async def shutdown_event():
    await sync_service.shutdown()



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
