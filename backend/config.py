"""
iPaper 配置管理
"""
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class LLMConfig(BaseSettings):
    """LLM 配置"""
    api_base: str = "https://api3.xhub.chat/v1"
    api_key: str = ""
    model: str = "gemini-3-pro-preview-thinking"
    temperature: float = 0.7
    max_tokens: int = 8192


class ProfileAnalysisConfig(BaseSettings):
    """画像分析专用模型配置（使用 Claude，指令跟随更好）"""
    model: str = "cu-claude-opus-4-6"
    temperature: float = 0.2
    max_tokens: int = 4096


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
    
    class Config:
        env_prefix = "IPAPER_"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ensure_dirs()
        self._load_config_file()
    
    def _ensure_dirs(self):
        """确保必要的目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.papers_dir.mkdir(exist_ok=True)
        (self.data_dir / "user_profile").mkdir(exist_ok=True)
    
    def _load_config_file(self):
        """从配置文件加载配置"""
        config_file = self.data_dir / "config.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "llm" in data:
                    for key, value in data["llm"].items():
                        if hasattr(self.llm, key):
                            setattr(self.llm, key, value)
    
    def save_config(self):
        """保存配置到文件"""
        config_file = self.data_dir / "config.json"
        data = {
            "llm": {
                "api_base": self.llm.api_base,
                "api_key": self.llm.api_key,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            }
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @property
    def papers_dir(self) -> Path:
        """论文存储目录（项目内部，Cursor 可直接访问）"""
        return PROJECT_ROOT / "papers"
    
    @property
    def user_profile_dir(self) -> Path:
        """用户画像目录"""
        return self.data_dir / "user_profile"


# 全局配置实例
settings = Settings()

