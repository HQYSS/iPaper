"""
iPaper 配置管理
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class LLMConfig(BaseSettings):
    """LLM 配置"""
    api_base: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    model: str = "google/gemini-3.1-pro-preview"
    temperature: float = 0.7
    max_tokens: int = 8192


class ProfileAnalysisConfig(BaseSettings):
    """画像分析专用模型配置（使用 Claude，指令跟随更好）"""
    model: str = "anthropic/claude-opus-4.6"
    temperature: float = 0.2
    max_tokens: int = 16384


PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """应用配置"""
    # 数据目录（config.json、user_profile 等敏感/个人数据）
    data_dir: Path = Path.home() / ".ipaper"
    
    # 服务配置
    host: str = "127.0.0.1"
    port: int = 3000
    
    # LLM 配置
    llm: LLMConfig = Field(default_factory=LLMConfig)
    
    # 画像分析配置（共用 llm 的 api_base 和 api_key）
    profile_analysis: ProfileAnalysisConfig = Field(default_factory=ProfileAnalysisConfig)
    
    # 幻觉翻译 Cookie（可选，仅未被翻译过的论文需要）
    hjfy_cookie: str = ""
    
    # 注册邀请码（未设置则拒绝所有注册）
    invite_code: str = ""
    
    # Electron 双向同步配置
    sync_url: str = ""      # 云端 API 地址，如 https://www.moshang.xyz/ipaper/api
    sync_token: str = ""    # 用于同步的 JWT token
    
    class Config:
        env_prefix = "IPAPER_"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ensure_dirs()
        self._load_config_file()
    
    def _ensure_dirs(self):
        """确保必要的目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_config_file(self):
        """从全局配置文件加载 LLM 等共享配置"""
        config_file = self.data_dir / "config.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "llm" in data:
                    for key, value in data["llm"].items():
                        if hasattr(self.llm, key):
                            setattr(self.llm, key, value)
                if "hjfy_cookie" in data:
                    self.hjfy_cookie = data["hjfy_cookie"]
                if "invite_code" in data:
                    self.invite_code = data["invite_code"]

    def load_user_config(self, user_id: str) -> dict:
        """加载用户私有配置（hjfy_cookie 等）"""
        config_file = self.get_user_data_dir(user_id) / "config.json"
        if not config_file.exists():
            return {}
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_user_config(self, user_id: str, data: dict) -> None:
        """保存用户私有配置"""
        user_dir = self.get_user_data_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        config_file = user_dir / "config.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def save_config(self):
        """保存全局配置到文件"""
        config_file = self.data_dir / "config.json"
        data = {
            "llm": {
                "api_base": self.llm.api_base,
                "api_key": self.llm.api_key,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "hjfy_cookie": self.hjfy_cookie,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_user_data_dir(self, user_id: str) -> Path:
        return self.data_dir / "data" / user_id

    def get_user_papers_dir(self, user_id: str) -> Path:
        d = self.get_user_data_dir(user_id) / "papers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_cross_paper_dir(self, user_id: str) -> Path:
        d = self.get_user_data_dir(user_id) / "cross-paper"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_user_profile_dir(self, user_id: str) -> Path:
        d = self.get_user_data_dir(user_id) / "user_profile"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # deprecated: use get_user_papers_dir(user_id) instead
    @property
    def papers_dir(self) -> Path:
        return PROJECT_ROOT / "papers"

    # deprecated: use get_user_profile_dir(user_id) instead
    @property
    def user_profile_dir(self) -> Path:
        return self.data_dir / "user_profile"

    def get_user_hjfy_cookie(self, user_id: str) -> str:
        """Per-user hjfy_cookie, falling back to global"""
        user_cfg = self.load_user_config(user_id)
        cookie = user_cfg.get("hjfy_cookie", "")
        return cookie if cookie else self.hjfy_cookie


# 全局配置实例
settings = Settings()

