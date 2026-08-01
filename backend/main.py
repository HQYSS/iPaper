"""
iPaper Backend - FastAPI 入口
"""
import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from routers import papers, chat, config, profile, translation, auth, preferences, sync
from middleware.auth import get_current_user
from middleware.request_logging import RequestLoggingMiddleware
from services.arxiv_service import arxiv_service
from services.log_context import RequestContextFilter
from services.runtime_info import get_runtime_info
from services.sync_service import sync_service
from services.chat_task_service import chat_task_service
from services.cloud_generation_service import cloud_generation_service
from services.cloud_chat_service import cloud_chat_service


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


def create_app() -> FastAPI:
    """创建应用实例，便于测试在隔离配置下构造完整 ASGI 应用。"""
    application = FastAPI(
        title="iPaper API",
        description="论文阅读助手后端 API",
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)

    application.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    application.include_router(preferences.router, prefix="/api/preferences", tags=["preferences"])
    application.include_router(papers.router, prefix="/api/papers", tags=["papers"])
    application.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    application.include_router(config.router, prefix="/api/config", tags=["config"])
    application.include_router(profile.router, prefix="/api/profile", tags=["profile"])
    application.include_router(translation.router, prefix="/api/papers", tags=["translation"])
    application.include_router(sync.router, prefix="/api/sync", tags=["sync"])

    @application.get("/")
    async def root():
        """健康检查"""
        return {"status": "ok", "message": "iPaper API is running"}

    @application.get("/api/health/runtime")
    async def runtime_health():
        """Return runtime version and process metadata for deployment/debug checks."""
        return get_runtime_info()

    @application.get("/api/health/live")
    async def live_health():
        return {"status": "live"}

    @application.get("/api/health/ready")
    async def ready_health():
        data_dir_ready = settings.data_dir.exists() and os.access(settings.data_dir, os.W_OK)
        payload = {
            "status": "ready" if data_dir_ready else "not_ready",
            "data_dir_writable": data_dir_ready,
            "sync_role": settings.sync_role,
        }
        return JSONResponse(payload, status_code=200 if data_dir_ready else 503)

    @application.get("/api/health/tasks")
    async def task_health(user: dict = Depends(get_current_user)):
        return {
            "user_id": user["id"],
            "chat": chat_task_service.get_status(user["id"]),
            "cloud_generation": cloud_generation_service.get_status(user["id"]),
            "cloud_chat_circuit": cloud_chat_service.get_status(),
            "sync": sync_service.get_status(),
        }

    @application.post("/api/client-logs")
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

    @application.on_event("startup")
    async def startup_event():
        if settings.is_sync_server and int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
            raise RuntimeError("CloudGenerationService 当前要求 WEB_CONCURRENCY=1")
        logging.getLogger(__name__).info("backend startup runtime=%s", get_runtime_info())
        await sync_service.startup()
        arxiv_service.recover_incomplete_downloads()

    @application.on_event("shutdown")
    async def shutdown_event():
        await sync_service.shutdown()

    return application


# 保持 ``uvicorn main:app`` 和现有导入方式兼容。
app = create_app()



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )
