"""
iPaper Backend - FastAPI 入口
"""
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import papers, chat, config, profile, translation, auth, preferences, sync
from middleware.auth import get_current_user
from middleware.request_logging import RequestLoggingMiddleware
from services.arxiv_service import arxiv_service
from services.log_context import RequestContextFilter
from services.runtime_info import get_runtime_info
from services.sync_service import sync_service


def configure_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s user=%(user_id)s]: %(message)s"
    )
    context_filter = RequestContextFilter()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        root_logger.addHandler(handler)
    for handler in root_logger.handlers:
        handler.setLevel(logging.INFO)
        handler.addFilter(context_filter)
        handler.setFormatter(formatter)
    for logger_name in (
        "routers.chat",
        "services.chat_task_service",
        "services.llm_service",
        "services.cursor_cli_service",
    ):
        logging.getLogger(logger_name).setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


configure_logging()

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
app.add_middleware(RequestLoggingMiddleware)

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


@app.get("/api/health/runtime")
async def runtime_health():
    """Return runtime version and process metadata for deployment/debug checks."""
    return get_runtime_info()


@app.post("/api/client-logs")
async def client_logs(payload: dict, user: dict = Depends(get_current_user)):
    """Receive browser/Electron renderer diagnostics."""
    logging.getLogger("client").log(
        logging.WARNING if payload.get("level") in {"error", "warning"} else logging.INFO,
        "client event level=%s message=%s context=%s",
        payload.get("level", "info"),
        payload.get("message", ""),
        {**payload.get("context", {}), "client_user_id": user["id"]},
    )
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    logging.getLogger(__name__).info("backend startup runtime=%s", get_runtime_info())
    await sync_service.startup()
    arxiv_service.recover_incomplete_downloads()


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
