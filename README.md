# iPaper - 论文阅读助手

一个基于 AI 的学术论文阅读工具，支持从 arXiv 下载论文，并提供 LLM 辅助阅读功能。

## 功能特性

- 📥 **论文下载**：支持 arXiv ID 或 URL 直接下载论文
- 📖 **PDF 阅读**：内置 PDF 阅读器，支持目录导航、搜索、缩放
- 🤖 **AI 对话**：基于 Gemini 的智能论文问答
- 📚 **论文管理**：论文库管理，支持导出

## 技术栈

- **前端**: React 18 + TypeScript + Tailwind CSS
- **后端**: Python FastAPI
- **桌面端**: Electron
- **LLM**: Gemini 3 Pro (via NewAPI)

## 项目结构

```
iPaper/
├── backend/           # Python 后端
│   ├── main.py        # FastAPI 入口
│   ├── config.py      # 配置管理
│   ├── routers/       # API 路由
│   ├── services/      # 业务逻辑
│   └── models/        # 数据模型
├── frontend/          # React 前端
│   ├── src/
│   │   ├── components/  # UI 组件
│   │   ├── stores/      # 状态管理
│   │   └── services/    # API 调用
│   └── ...
├── electron/          # Electron 主进程
│   ├── main.js        # 主进程入口
│   └── preload.js     # 预加载脚本
└── docs/              # 文档
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- pnpm (推荐) 或 npm

### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
pnpm install
```

### 3. 配置 API Key

首次运行时，需要配置 LLM API Key。在 `~/.ipaper/config.json` 中添加：

```json
{
  "llm": {
    "api_key": "your-api-key-here"
  }
}
```

### 4. 启动开发服务器

**后端**:
```bash
cd backend
python main.py
```

**前端**:
```bash
cd frontend
pnpm dev
```

**Electron** (可选):
```bash
cd electron
npm install
npm run dev
```

然后访问 http://localhost:5173

## 配置说明

配置文件位于 `~/.ipaper/config.json`：

```json
{
  "llm": {
    "api_base": "https://api3.xhub.chat/v1",
    "api_key": "your-api-key",
    "model": "gemini-3-pro-preview-thinking",
    "temperature": 0.7,
    "max_tokens": 8192
  }
}
```

## API 文档

启动后端后，访问 http://localhost:3000/docs 查看交互式 API 文档。

## License

MIT

