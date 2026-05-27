# Chrome 扩展

## 功能定位

`chrome-extension/` 是 iPaper 的 Chrome 导入助手，用于把浏览器中正在看的论文直接导入本机 iPaper。

支持入口：

- arXiv abs 页面：`https://arxiv.org/abs/...` 页面内注入「导入 iPaper」按钮。
- arXiv HTML 页面：`https://arxiv.org/html/...` 页面内注入「导入 iPaper」按钮。
- arXiv PDF 页面：通过扩展工具栏按钮或右键菜单导入，扩展会识别 arXiv ID，并按 arXiv 论文导入。
- 普通 PDF URL：通过扩展工具栏按钮或右键菜单导入，按普通 PDF URL 论文导入。

arXiv PDF 不按普通 PDF 处理，而是规范化为 `https://arxiv.org/abs/{id}` 传给后端。这样后端会得到 `source_type=arxiv`，后续仍能触发 hjfy 中文版查询与下载。

## 目录结构

```text
chrome-extension/
├── manifest.json
├── popup.html
├── src/
│   ├── background.js      # 导入逻辑、右键菜单、Native Messaging 调用
│   ├── content.js         # arXiv abs/html 页面按钮注入
│   ├── content.css
│   ├── popup.js           # 工具栏弹窗逻辑
│   └── popup.css
└── native-host/
    ├── ipaper_native_host.py       # Chrome Native Messaging host
    └── install_native_host.sh      # macOS 安装脚本
```

## 导入流程

1. 扩展识别当前 tab URL。
2. 如果是 arXiv `abs/html/pdf`，提取 arXiv ID 并规范化为 abs URL。
3. arXiv `abs/html` 页面会同时抓取页面标题、摘要和作者，作为 arXiv metadata API 被 429 限流时的兜底元信息。
4. 如果是普通 PDF URL，保留原始 URL。
5. 扩展先检查 `http://127.0.0.1:3000/`。
6. 后端已就绪时，直接 `POST http://127.0.0.1:3000/api/papers`。
7. 后端未就绪时，扩展调用 Native Messaging host 拉起 `iPaper.app`，等待健康检查通过后再导入。
8. 导入成功或点击「打开 iPaper」时，扩展 `POST /api/papers/open-request` 写入目标 `paper_id`，再通过 Native host 拉起/聚焦桌面端。
9. 前端轮询 `GET /api/papers/open-request`，消费到 `paper_id` 后刷新论文列表并选中对应论文。

后端复用现有 `POST /api/papers`，请求体：

```json
{
  "arxiv_input": "https://arxiv.org/abs/1706.03762",
  "title": "Attention Is All You Need",
  "summary": "The dominant sequence transduction models...",
  "authors": ["Ashish Vaswani", "Noam Shazeer"],
  "source_url": "https://arxiv.org/abs/1706.03762"
}
```

`title/summary/authors/source_url` 都是可选字段。后端只在本地 meta 仍是占位状态时使用这些字段；arXiv API 后台补齐成功后仍以官方 metadata 为准。

打开对应论文使用本地 pending request：

```json
{ "paper_id": "1706.03762" }
```

## 安装扩展

1. 打开 Chrome 扩展管理页：`chrome://extensions/`。
2. 开启「开发者模式」。
3. 点击「加载已解压的扩展程序」。
4. 选择仓库里的 `chrome-extension/` 目录。

`manifest.json` 内置了稳定 public key，扩展 ID 固定为：

```text
niopfodkcphjggappggakadlgkddlogf
```

## 安装本机启动桥接

扩展本身不能直接执行本地命令。自动启动 iPaper 依赖 Chrome Native Messaging host。

安装：

```bash
./chrome-extension/native-host/install_native_host.sh
```

如需调试非默认扩展 ID，也可以显式传入：

```bash
./chrome-extension/native-host/install_native_host.sh <Chrome 扩展 ID>
```

卸载：

```bash
./chrome-extension/native-host/install_native_host.sh --uninstall
```

安装脚本会把 host manifest 写入：

```text
~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.ipaper.native_host.json
~/Library/Application Support/Google/Chrome for Testing/NativeMessagingHosts/com.ipaper.native_host.json
~/Library/Application Support/Chromium/NativeMessagingHosts/com.ipaper.native_host.json
```

Native host 不是常驻进程。扩展需要自动启动 iPaper 时，Chrome 临时启动 `ipaper_native_host.py`，host 收到一条 JSON 消息后执行白名单动作并退出。

当前白名单动作：

- `healthcheck`：检查本地后端是否就绪。
- `start_ipaper`：调用 `open iPaper.app`，等待本地后端健康检查通过。
- `open_ipaper`：调用 `open iPaper.app` 拉起或聚焦桌面端，供「打开 iPaper」按钮使用。

## 安全边界

- Native host 不接受任意 shell 命令。
- host manifest 通过 `allowed_origins` 限制只有指定扩展 ID 可以调用。
- 扩展只请求本地 API：`http://127.0.0.1:3000/api`。
- 本地后端沿用现有本地模式认证逻辑，仅回环地址免登录。

## 验证

基础验证：

```bash
python -m py_compile chrome-extension/native-host/ipaper_native_host.py
python -m json.tool chrome-extension/manifest.json
node --check chrome-extension/src/background.js
node --check chrome-extension/src/content.js
node --check chrome-extension/src/popup.js
```

已自动验证过的内容：

- Playwright Chromium 加载 unpacked extension 后，扩展 ID 为 `niopfodkcphjggappggakadlgkddlogf`。
- arXiv abs 页面可出现「导入 iPaper」按钮。
- 点击按钮可通过本地后端导入 `1706.03762`，页面显示「已导入：1706.03762」。
- arXiv PDF URL 会规范化为 `https://arxiv.org/abs/{id}`；普通 PDF URL 保留原始 URL。
- `/api/papers/open-request` 可写入并被前端消费，导入后会自动打开对应论文。
- arXiv metadata API 返回 429 时，abs/html 页面抓取的标题/摘要/作者会先写入本地 meta，后台任务延迟重试官方 metadata。

## 开发与验收 checklist

Chrome 扩展改动必须区分三层状态：

- 源码状态：`chrome-extension/` 文件是否真的落盘，最终回复前要重新读关键文件确认。
- 扩展加载状态：`chrome://extensions` 里加载的是哪个目录、哪个扩展 ID；刷新网页不会刷新 background service worker。
- 运行时状态：content script、background service worker、Native host、Electron 主进程是否都是新版。

每次改扩展都必须检查：

1. `manifest.json` 内置 key 是否仍对应固定 ID `niopfodkcphjggappggakadlgkddlogf`。
2. Native host manifest 的 `allowed_origins` 是否包含当前扩展 ID。
3. 改 `background.js` / `manifest.json` 后，必须在 `chrome://extensions` 点扩展卡片刷新按钮，再刷新 arXiv 页面。
4. 改 `ipaper_native_host.py` 后，必须重新运行 `install_native_host.sh`，并用 stdio 协议测试 `healthcheck`、`start_ipaper`、`open_ipaper`。
5. 改 `electron/main.js` 后，必须完整重启 `iPaper.app`，只聚焦已有窗口不会替换常驻主进程。
6. 验证“打开 iPaper”时，不能只看是否打开应用，还要确认前端选中了对应 `paper_id`。
7. 验证 arXiv abs/html 导入时，必须确认标题不是 `arXiv {id}` 占位标题；如果 arXiv API 429，也应使用页面 fallback 标题。
8. 如果使用 Playwright 临时 profile 验证，汇报时必须明确它不是用户日常 Chrome profile；用户日常 Chrome 是否生效要看 `chrome://extensions` 实际加载状态。

手动验证：

1. 加载扩展并安装 Native host。
2. 关闭 iPaper，打开 arXiv abs 页面，点击「导入 iPaper」。
3. 确认 iPaper 自动启动，论文进入论文库，并自动选中刚导入的论文。
4. 打开 arXiv PDF 页面，点击扩展工具栏导入，确认导入后 `source_type=arxiv`。
5. 打开普通 PDF URL，点击扩展工具栏导入，确认导入后 `source_type=pdf_url`。
