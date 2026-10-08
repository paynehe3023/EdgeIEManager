# 自动更新功能测试方法

分三层测，从快到慢、从假到真。日常改代码只跑第一层就够。

## 一、本地假更新源（最快，不碰 GitHub）

原理：更新器支持一个只用于测试的环境变量 `EDGEIE_UPDATE_BASE_URL`，
设置后它会从这个地址读 `version.json` 和安装包，不再访问 GitHub。
程序本身的行为（进度条、取消、替换、重启）完全一样。

两个窗口：

```powershell
# 窗口 1：起本地假更新源，版本号随便填个比当前高的
py -3 tools\local_update_server.py --exe dist\EdgeIEManager.exe --version 9.9.9 --kbps 800
```

```powershell
# 窗口 2：让程序从本地源检查更新
$env:EDGEIE_UPDATE_BASE_URL = "http://127.0.0.1:8765"
.\dist\EdgeIEManager.exe
```

然后在界面里点 **关于 → 检查更新**。要点：

- `--kbps 800` 限速，进度条才走得慢，方便看清百分比、也方便点“取消下载”；
- 加 `--connect-delay 10` 可以复现“连接阶段卡住”的场景，验证界面是不是
  老老实实显示“正在连接下载服务器…”，而不是卡在“准备下载…”；
- 测自动替换建议先把 exe 复制到空目录再运行，避免污染 `dist`：

```powershell
New-Item -ItemType Directory -Force -Path D:\tmp\edgeie-test | Out-Null
Copy-Item .\dist\EdgeIEManager.exe D:\tmp\edgeie-test\ -Force
$env:EDGEIE_UPDATE_BASE_URL = "http://127.0.0.1:8765"
D:\tmp\edgeie-test\EdgeIEManager.exe
```

自动化版本：`py -3 -m unittest tests.test_update_local_server -v`
（覆盖清单读取、下载内容一致、sha256 校验失败丢弃、取消中断不留残留）。

## 二、影子仓库（真实链路，但零风险）

想验证真的走 GitHub 而不影响现有用户时，开一个测试仓库，
例如 `你的账号/EdgeIEManager-Test`，放入 `version.json` 并建一个 Release，
资源名必须是 `EdgeIEManager.exe`。然后在**测试机**上改配置：

```json
{
  "update_repo": "你的账号/EdgeIEManager-Test"
}
```

`config.json` 位于 `%LOCALAPPDATA%\EdgeIEManager\config.json`。
这样这台机器就只跟测试仓库打交道，正式用户不受影响。

## 三、真实发布验收（上线前做一次）

1. 在正式仓库建 Release（tag 形如 `v1.0.4`），上传 `EdgeIEManager.exe`，文件名不能改。
2. 确认 `main` 分支的 `version.json` 里 `version` 是新版本号。
3. 用**上一个正式版**装一次，点 关于 → 检查更新，走完整流程。

### 老版本能不能升级到新版

能。1.0.1～1.0.3 的“缺陷”是体验问题，不是功能失效：

- 1.0.2 及更早：下载过程只在日志里按 20% 打印，没有进度条；
- 1.0.3：有进度条，但在收到第一个数据块之前一直显示“准备下载…”，
  而且不能取消；GitHub 下载要先重定向，国内网络这一步可能卡很久。

下载本身走的是同一套 `urllib` 流式写入，只要网络能通就会完成。
验证老版本时，可以盯着程序目录下有没有 `EdgeIEManager.exe.new` 在变大，
这比看界面更可靠。等不及就直接让用户走“打开发布页”手动下载。

## 常见坑

- **release 资源名必须是 `EdgeIEManager.exe`**：更新器只认这个名字，
  上传成 `EdgeIEManager (1).exe` 或 `EdgeIEManager-1.0.4.exe` 都找不到；
- **程序文件不能改名**：自动替换要求自身文件名是 `EdgeIEManager.exe`。
  改名成 `EdgeIEManager-old.exe` 之类的会被判定为“便携版”，
  只能手动下载；同理 `EdgeIEManager-Clean.exe` 刻意不参与自动替换；
- **raw.githubusercontent.com 有 CDN 缓存**：刚推完 `version.json` 可能几分钟内
  还读到旧内容，等一会儿再试，不要急着改代码；
- **GitHub API 限流**：`version.json` 走 raw 不会限流，是 API 兜底路径才可能
  撞 60 次/小时限制。
