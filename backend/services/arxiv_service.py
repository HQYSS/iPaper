"""
arXiv 论文下载服务
"""
import re
import json
import httpx
import arxiv
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

from config import settings
from models import PaperMeta


class ArxivService:
    """arXiv 论文下载和管理服务"""
    
    ARXIV_ID_PATTERN = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')
    ARXIV_URL_PATTERN = re.compile(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?')
    
    def parse_arxiv_input(self, input_str: str) -> Optional[str]:
        """
        解析用户输入，提取 arXiv ID
        支持格式：
        - 2301.12345
        - 2301.12345v1
        - https://arxiv.org/abs/2301.12345
        - https://arxiv.org/pdf/2301.12345.pdf
        """
        input_str = input_str.strip()
        
        url_match = self.ARXIV_URL_PATTERN.search(input_str)
        if url_match:
            arxiv_id = url_match.group(1)
            version = url_match.group(2) or ""
            return arxiv_id + version
        
        id_match = self.ARXIV_ID_PATTERN.search(input_str)
        if id_match:
            arxiv_id = id_match.group(1)
            version = id_match.group(2) or ""
            return arxiv_id + version
        
        return None
    
    def get_paper_dir(self, user_id: str, arxiv_id: str) -> Path:
        base_id = self.ARXIV_ID_PATTERN.match(arxiv_id).group(1)
        return settings.get_user_papers_dir(user_id) / base_id
    
    async def download_paper(self, user_id: str, arxiv_input: str) -> Tuple[bool, str, Optional[PaperMeta]]:
        arxiv_id = self.parse_arxiv_input(arxiv_input)
        if not arxiv_id:
            return False, f"无法解析 arXiv ID: {arxiv_input}", None
        
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        if meta_file.exists():
            meta = self._load_meta(meta_file)
            return True, "论文已存在", meta
        
        try:
            client = arxiv.Client()
            search = arxiv.Search(id_list=[arxiv_id])
            results = list(client.results(search))
            
            if not results:
                return False, f"未找到论文: {arxiv_id}", None
            
            paper = results[0]
            
            paper_dir.mkdir(parents=True, exist_ok=True)
            
            pdf_path = paper_dir / "paper.pdf"
            paper.download_pdf(dirpath=str(paper_dir), filename="paper.pdf")
            
            meta = PaperMeta(
                arxiv_id=arxiv_id,
                title=paper.title,
                summary=paper.summary,
                authors=[author.name for author in paper.authors],
                download_time=datetime.now(),
                has_latex=False,
                pdf_path=str(pdf_path)
            )
            
            self._save_meta(meta_file, meta)
            self._update_index(user_id, meta)
            
            return True, "下载成功", meta
            
        except Exception as e:
            return False, f"下载失败: {str(e)}", None
    
    def get_paper(self, user_id: str, arxiv_id: str) -> Optional[PaperMeta]:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        if meta_file.exists():
            return self._load_meta(meta_file)
        return None
    
    def list_papers(self, user_id: str) -> List[PaperMeta]:
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"
        if not index_file.exists():
            return []
        
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        papers = []
        for item in data.get("papers", []):
            paper_dir = self.get_paper_dir(user_id, item["arxiv_id"])
            meta_file = paper_dir / "meta.json"
            if meta_file.exists():
                papers.append(self._load_meta(meta_file))
        
        return papers
    
    def delete_paper(self, user_id: str, arxiv_id: str) -> bool:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        if not paper_dir.exists():
            return False
        
        import shutil
        shutil.rmtree(paper_dir)
        
        self._remove_from_index(user_id, arxiv_id)
        
        return True
    
    def get_pdf_path(self, user_id: str, arxiv_id: str) -> Optional[Path]:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        pdf_path = paper_dir / "paper.pdf"
        if pdf_path.exists():
            return pdf_path
        return None
    
    def _load_meta(self, meta_file: Path) -> PaperMeta:
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PaperMeta(**data)
    
    def _save_meta(self, meta_file: Path, meta: PaperMeta):
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta.model_dump(mode="json"), f, indent=2, ensure_ascii=False, default=str)
    
    def _update_index(self, user_id: str, meta: PaperMeta):
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"
        
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"papers": []}
        
        for item in data["papers"]:
            if item["arxiv_id"] == meta.arxiv_id:
                return
        
        data["papers"].append({
            "arxiv_id": meta.arxiv_id,
            "title": meta.title,
            "download_time": meta.download_time.isoformat()
        })
        
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _remove_from_index(self, user_id: str, arxiv_id: str):
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"
        
        if not index_file.exists():
            return
        
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        data["papers"] = [p for p in data["papers"] if p["arxiv_id"] != arxiv_id]
        
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# 全局服务实例
arxiv_service = ArxivService()
