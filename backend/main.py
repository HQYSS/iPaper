"""
iPaper Backend - FastAPI 入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import papers, chat, config, profile

# 创建 FastAPI 应用
app = FastAPI(
    title="iPaper API",
    description="论文阅读助手后端 API",
    version="0.1.0"
)

# CORS 配置（允许 Electron 前端访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron 本地应用
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(papers.router, prefix="/api/papers", tags=["papers"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "message": "iPaper API is running"}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True  # 开发模式
    )

