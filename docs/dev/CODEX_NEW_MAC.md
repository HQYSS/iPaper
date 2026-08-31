# 新 Mac 上用 Codex 安装本地 iPaper

这份文档给 **新电脑上的 Codex** 用。目标：克隆 GitHub、装好开发环境、连上现有云端账号 `muxi`，把论文同步下来。不要拷 `~/.ipaper` 论文目录。

密钥不在仓库里。它们在独立文件 `new-mac.secrets.json`（由交接包提供）。

## 给人类的一句话

把交接目录 `ipaper-new-mac-handoff/` 交给新 Mac 的 Codex，只发：

> 阅读并严格执行这个目录里的 `CODEX_DO_THIS.md`，不要问我任何问题。

## 给 Codex 的强制约定

1. 不要提问，不要等待确认，不要部署云端，不要 `git push`，不要改 Nginx/Xray。
2. 默认安装到 `$HOME/workspace/iPaper`。
3. 本机角色必须是 `sync_role=client`。云端是唯一的 `server`。
4. 先读仓库根目录 `AGENTS.md`，再执行安装。
5. 失败就自己修，再跑，直到本地后端健康检查通过。

## 执行顺序

```bash
# 1. 确保本机有 GitHub 权限（SSH 或 gh）
# 2. 运行交接包或仓库里的安装脚本
bash /path/to/iPaper/scripts/bootstrap-new-mac.sh /path/to/new-mac.secrets.json
```

脚本会：

1. 安装 Node 18+ 和 Python 3.10+（优先 Homebrew，否则用户目录 Miniconda / 官方 Node 包）
2. `git clone git@github.com:HQYSS/iPaper.git` 到 `$HOME/workspace/iPaper`（已有仓库则 `ff-only` 拉 `main`）
3. 安装 `backend`、`frontend`、`electron` 依赖
4. 把 `new-mac.secrets.json` 写成 `~/.ipaper/config.json`（权限 `600`）
5. 安装 Chrome Native Messaging host
6. `open iPaper.app`
7. 等待 `http://127.0.0.1:3000/` 就绪，并检查论文列表是否从云端下来

`iPaper.sh` 会按 `.app` 位置解析仓库根目录，并在常见路径里找 `python` / `npm`，不再写死 `/Users/admin/...`。

## 成功标准

- `curl http://127.0.0.1:3000/api/health/runtime` 返回 `sync_role=client`
- `curl http://127.0.0.1:3000/api/papers` 能看到云端 `muxi` 的论文（当前约 5 篇）
- 双击 `iPaper.app` 能打开窗口
- 日志：`$HOME/ipaper-new-mac-bootstrap.log` 末尾有 `BOOTSTRAP_COMPLETE=yes`

## 不要做的事

- 不要复用旧电脑的整份 `~/.ipaper/data`（2GB+）；论文走云端同步
- 不要把 `new-mac.secrets.json` 提交进 Git
- 不要在新电脑上把 `sync_role` 设成 `server`
- 不要吊销旧电脑的设备 `iPaper local muxi`；新电脑用的是独立设备 `muxi-new-mac`

## 可选：Chrome 扩展

```bash
# Chrome → chrome://extensions → 开发者模式 → 加载已解压扩展
# 选 $HOME/workspace/iPaper/chrome-extension/
./chrome-extension/native-host/install_native_host.sh
```

扩展加载这一步如果当前 Codex 没有 GUI 控制权，可以跳过；桌面端和同步不依赖它。
