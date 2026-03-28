"""
同步 API 路由 — Electron 本地后端与云端后端之间的数据同步
"""
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from fastapi.responses import JSONResponse

from middleware.auth import get_current_user
from services.sync_service import sync_service

router = APIRouter()


@router.get("/manifest")
async def get_manifest(user: dict = Depends(get_current_user)):
    """返回该用户所有论文的 {arxiv_id, updated_at} 清单 + 偏好和画像的 updated_at"""
    manifest = sync_service.get_manifest(user["id"])
    return manifest.to_dict()


@router.get("/papers/{paper_id}/bundle")
async def download_paper_bundle(paper_id: str, user: dict = Depends(get_current_user)):
    """下载某篇论文的完整数据包（meta + PDF + 所有聊天 JSON，zip 格式）"""
    bundle = sync_service.create_paper_bundle(user["id"], paper_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={paper_id}.zip"},
    )


@router.put("/papers/{paper_id}/bundle")
async def upload_paper_bundle(
    paper_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传某篇论文的完整数据包"""
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（上限 100MB）")
    ok = sync_service.extract_paper_bundle(user["id"], paper_id, content)
    if not ok:
        raise HTTPException(status_code=400, detail="无效的 zip 文件")
    return {"status": "ok"}


@router.get("/preferences")
async def get_preferences(user: dict = Depends(get_current_user)):
    """下载偏好"""
    data = sync_service.get_preferences(user["id"])
    if data is None:
        return JSONResponse(content={}, status_code=200)
    return data


@router.put("/preferences")
async def put_preferences(body: dict, user: dict = Depends(get_current_user)):
    """上传偏好"""
    sync_service.put_preferences(user["id"], body)
    return {"status": "ok"}


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """下载画像"""
    content = sync_service.get_profile(user["id"])
    if content is None:
        return JSONResponse(content={"content": ""}, status_code=200)
    return {"content": content}


@router.put("/profile")
async def put_profile(body: dict, user: dict = Depends(get_current_user)):
    """上传画像"""
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content 必须是字符串")
    sync_service.put_profile(user["id"], content)
    return {"status": "ok"}
