"""
论文管理 API 路由
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from models import PaperCreate, PaperMeta, PaperListItem
from services.arxiv_service import arxiv_service

router = APIRouter()


@router.get("", response_model=list[PaperListItem])
async def list_papers():
    """获取论文列表"""
    papers = arxiv_service.list_papers()
    return [
        PaperListItem(
            arxiv_id=p.arxiv_id,
            title=p.title,
            title_zh=p.title_zh,
            summary=p.summary[:200] + "..." if len(p.summary) > 200 else p.summary,
            authors=p.authors,
            download_time=p.download_time
        )
        for p in papers
    ]


@router.post("", response_model=PaperMeta)
async def add_paper(request: PaperCreate):
    """添加论文"""
    success, message, meta = await arxiv_service.download_paper(request.arxiv_input)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return meta


@router.get("/{paper_id}", response_model=PaperMeta)
async def get_paper(paper_id: str):
    """获取论文详情"""
    meta = arxiv_service.get_paper(paper_id)
    
    if not meta:
        raise HTTPException(status_code=404, detail="论文不存在")
    
    return meta


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str):
    """删除论文"""
    success = arxiv_service.delete_paper(paper_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="论文不存在")
    
    return {"message": "删除成功"}


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(paper_id: str):
    """获取论文 PDF"""
    pdf_path = arxiv_service.get_pdf_path(paper_id)
    
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF 不存在")
    
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{paper_id}.pdf"
    )


@router.get("/{paper_id}/export")
async def export_paper(paper_id: str):
    """导出论文 PDF（与 get_pdf 相同，但触发下载）"""
    pdf_path = arxiv_service.get_pdf_path(paper_id)
    
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF 不存在")
    
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{paper_id}.pdf",
        headers={"Content-Disposition": f"attachment; filename={paper_id}.pdf"}
    )

