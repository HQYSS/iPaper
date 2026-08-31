"""
同步 API 路由 — Electron 本地后端与云端后端之间的数据同步
"""
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, Header
from fastapi.responses import JSONResponse

from middleware.auth import get_sync_user
from services.sync_service import sync_service

router = APIRouter()


def _digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _digest_json(content: dict) -> str:
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _check_revision(expected: Optional[str], actual: Optional[str]) -> None:
    if expected is None:
        return
    normalized_actual = actual or "__none__"
    if expected != normalized_actual:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sync_conflict",
                "expected_revision": expected,
                "actual_revision": normalized_actual,
            },
        )


def _paper_revision(user_id: str, paper_id: str, field: str) -> Optional[str]:
    manifest = sync_service.get_manifest(user_id).to_dict()
    paper = next(
        (item for item in manifest.get("papers", []) if item["arxiv_id"] == paper_id),
        None,
    )
    return paper.get(field) if paper else None


def _deduplicated(
    user_id: str,
    operation_id: Optional[str],
    payload_digest: Optional[str],
) -> Optional[dict]:
    record = sync_service.get_operation_record(user_id, operation_id)
    if record:
        if record.get("payload_digest") != payload_digest:
            raise HTTPException(
                status_code=409,
                detail={"code": "idempotency_payload_mismatch"},
            )
        return {"status": "ok", "deduplicated": True}
    return None


async def _atomic_apply(
    user_id: str,
    entity: str,
    operation_id: Optional[str],
    expected_revision: Optional[str],
    actual_revision,
    apply,
    invalid_detail: str,
    payload_digest: Optional[str] = None,
) -> dict:
    async with sync_service.entity_lock(user_id, entity):
        bound_operation_id = (
            f"{entity}:{operation_id}" if operation_id else None
        )
        duplicate = _deduplicated(
            user_id,
            bound_operation_id,
            payload_digest,
        )
        if duplicate:
            return duplicate
        _check_revision(expected_revision, actual_revision())
        if not apply():
            raise HTTPException(status_code=400, detail=invalid_detail)
        sync_service.mark_operation_applied(
            user_id,
            bound_operation_id,
            payload_digest,
        )
        return {"status": "ok"}


@router.get("/manifest")
async def get_manifest(
    sync_protocol: Optional[str] = Header(None, alias="X-Sync-Protocol"),
    user: dict = Depends(get_sync_user),
):
    """返回该用户所有论文的 {arxiv_id, updated_at} 清单 + 偏好和画像的 updated_at"""
    manifest = sync_service.get_manifest(user["id"])
    data = manifest.to_dict()
    data["user_id"] = user["id"]
    data["username"] = user.get("username", "")
    if sync_protocol != "2":
        data["papers"] = [
            paper for paper in data["papers"] if paper.get("pdf_available")
        ]
    return data


@router.get("/papers/{paper_id}/bundle")
async def download_paper_bundle(paper_id: str, user: dict = Depends(get_sync_user)):
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
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传某篇论文的完整数据包"""
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大（上限 100MB）")
    return await _atomic_apply(
        user["id"],
        f"paper:{paper_id}",
        idempotency_key,
        x_base_revision,
        lambda: _paper_revision(user["id"], paper_id, "paper_updated_at"),
        lambda: sync_service.extract_paper_bundle(user["id"], paper_id, content),
        "无效的 zip 文件",
        _digest_bytes(content),
    )


@router.get("/papers/{paper_id}/metadata/bundle")
async def download_paper_metadata_bundle(
    paper_id: str,
    user: dict = Depends(get_sync_user),
):
    bundle = sync_service.create_paper_metadata_bundle(user["id"], paper_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="论文元信息不存在")
    return Response(content=bundle, media_type="application/zip")


@router.put("/papers/{paper_id}/metadata/bundle")
async def upload_paper_metadata_bundle(
    paper_id: str,
    file: UploadFile = File(...),
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="元信息包过大（上限 20MB）")
    return await _atomic_apply(
        user["id"],
        f"paper:{paper_id}",
        idempotency_key,
        x_base_revision,
        lambda: _paper_revision(user["id"], paper_id, "paper_updated_at"),
        lambda: sync_service.extract_paper_bundle(user["id"], paper_id, content),
        "无效的元信息 zip 文件",
        _digest_bytes(content),
    )


@router.get("/papers/{paper_id}/pdf")
async def download_pdf_asset(paper_id: str, user: dict = Depends(get_sync_user)):
    """下载独立 PDF 资产。"""
    content = sync_service.create_pdf_asset(user["id"], paper_id)
    if content is None:
        raise HTTPException(status_code=404, detail="PDF 不存在")
    return Response(content=content, media_type="application/pdf")


@router.put("/papers/{paper_id}/pdf")
async def upload_pdf_asset(
    paper_id: str,
    file: UploadFile = File(...),
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传源站无法由云端可靠获取的 PDF 资产。"""
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF 过大（上限 100MB）")
    return await _atomic_apply(
        user["id"],
        f"pdf:{paper_id}",
        idempotency_key,
        x_base_revision,
        lambda: _paper_revision(user["id"], paper_id, "pdf_hash"),
        lambda: sync_service.extract_pdf_asset(user["id"], paper_id, content),
        "无效的 PDF 文件",
        _digest_bytes(content),
    )


@router.get("/papers/{paper_id}/chats/bundle")
async def download_paper_chats_bundle(paper_id: str, user: dict = Depends(get_sync_user)):
    """下载某篇论文的聊天数据包（仅 chats/，不含 PDF）"""
    bundle = sync_service.create_paper_chats_bundle(user["id"], paper_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="聊天数据不存在")
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={paper_id}-chats.zip"},
    )


@router.put("/papers/{paper_id}/chats/bundle")
async def upload_paper_chats_bundle(
    paper_id: str,
    file: UploadFile = File(...),
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传某篇论文的聊天数据包（仅 chats/）"""
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="聊天数据过大（上限 20MB）")
    return await _atomic_apply(
        user["id"],
        f"chats:{paper_id}",
        idempotency_key,
        x_base_revision,
        lambda: _paper_revision(user["id"], paper_id, "chats_updated_at"),
        lambda: sync_service.extract_paper_chats_bundle(user["id"], paper_id, content),
        "无效的聊天 zip 文件",
        _digest_bytes(content),
    )


@router.delete("/papers/{paper_id}")
async def delete_paper_bundle(
    paper_id: str,
    deleted_at: Optional[str] = None,
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """按 tombstone 删除某篇论文"""
    return await _atomic_apply(
        user["id"],
        f"paper:{paper_id}",
        idempotency_key,
        x_base_revision,
        lambda: _paper_revision(user["id"], paper_id, "paper_updated_at"),
        lambda: (
            sync_service.delete_paper(user["id"], paper_id, deleted_at) or True
        ),
        "论文删除失败",
        _digest_json({"deleted_at": deleted_at}),
    )


@router.get("/cross-paper/bundle")
async def download_cross_paper_bundle(user: dict = Depends(get_sync_user)):
    """下载串讲会话与历史快照。"""
    bundle = sync_service.create_cross_paper_bundle(user["id"])
    if bundle is None:
        raise HTTPException(status_code=404, detail="串讲数据不存在")
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=cross-paper.zip"},
    )


@router.put("/cross-paper/bundle")
async def upload_cross_paper_bundle(
    file: UploadFile = File(...),
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传串讲会话与历史快照。"""
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="串讲数据过大（上限 20MB）")
    return await _atomic_apply(
        user["id"],
        "cross-paper",
        idempotency_key,
        x_base_revision,
        lambda: sync_service.get_manifest(user["id"]).cross_paper_updated_at,
        lambda: sync_service.extract_cross_paper_bundle(user["id"], content),
        "无效的串讲 zip 文件",
        _digest_bytes(content),
    )


@router.get("/preferences")
async def get_preferences(user: dict = Depends(get_sync_user)):
    """下载偏好"""
    data = sync_service.get_preferences(user["id"])
    if data is None:
        return JSONResponse(content={}, status_code=200)
    return data


@router.put("/preferences")
async def put_preferences(
    body: dict,
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传偏好"""
    return await _atomic_apply(
        user["id"],
        "preferences",
        idempotency_key,
        x_base_revision,
        lambda: sync_service.get_manifest(user["id"]).preferences_updated_at,
        lambda: (sync_service.put_preferences(user["id"], body) or True),
        "无效的偏好数据",
        _digest_json(body),
    )


@router.get("/profile")
async def get_profile(user: dict = Depends(get_sync_user)):
    """下载画像"""
    content = sync_service.get_profile(user["id"])
    return {
        "content": content or "",
        "updated_at": sync_service.get_profile_updated_at(user["id"]),
    }


@router.put("/profile")
async def put_profile(
    body: dict,
    x_base_revision: Optional[str] = Header(None, alias="X-Base-Revision"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    user: dict = Depends(get_sync_user),
):
    """上传画像"""
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content 必须是字符串")
    updated_at = body.get("updated_at")
    if updated_at is not None and not isinstance(updated_at, str):
        raise HTTPException(status_code=400, detail="updated_at 必须是字符串")
    return await _atomic_apply(
        user["id"],
        "profile",
        idempotency_key,
        x_base_revision,
        lambda: sync_service.get_manifest(user["id"]).profile_updated_at,
        lambda: (
            sync_service.put_profile(user["id"], content, updated_at) or True
        ),
        "无效的画像数据",
        _digest_json({"content": content, "updated_at": updated_at}),
    )
