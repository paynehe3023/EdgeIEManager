# Edge IE 模式站点管理器

当前版本：**v1.1.0**

一个零依赖的 Windows 小工具，用来管理 Microsoft Edge 的 **IE 模式站点列表**。
把需要在 IE 模式下打开的网址登记一次，以后 Edge 就会按照这份列表自动用 IE 模式打开，
不必再每个月到 `edge://settings` 里手动添加上一次。

工具提供图形界面（tkinter）和命令行两种用法，只用 Python 标准库，不需要安装任何第三方包。
界面支持浅色 / 深色主题，内置“检查更新”，可直接从 GitHub 拉取并安装新版本。

## 这个工具解决什么问题

Edge 的 IE 模式依赖一份“企业模式站点列表（Enterprise Mode Site List）”，
再由一条系统策略把 Edge 指向这份列表。手动维护很麻烦，本工具负责：

- 用合适的格式（schema v.2）生成和维护 `sitelist.xml`；
- 每次保存自动递增修订号、自动备份旧文件；
- 一键把策略写入注册表（当前用户可免管理员）；
- 提供月度模板，点一下就能生成“本月/下月”的网址；
- 一键自检 + 打开检查页，核对策略是否真的生效；
- 浅色 / 深色主题，以及内置的“检查更新”，直接从 GitHub 升级到新版本。

> 重要提示：**如果每个月变化的只是网址里的日期路径、域名不变，其实只要加一次域名就够了。**
> 例如地址形如 `report.contoso.com/2026/10/index.html`，把域名 `report.contoso.com`
> 加进列表后，该域名下的所有月份页面都会自动用 IE 模式打开，不需要每月维护。

## 工作原理

一次配置后，Edge 的行为由两块内容决定：

1. **站点列表文件**：本工具生成的 `sitelist.xml`，里面是若干条 `<site>`，
   每条指定一个网址和打开方式（`IE11` / `MSEdge` / `None`）。
2. **注册表策略**：在 `SOFTWARE\Policies\Microsoft\Edge` 下写入
   - `InternetExplorerIntegrationLevel = 1`（启用 IE 模式）
   - `InternetExplorerIntegrationSiteList = <站点列表文件的地址>`

其中站点列表用 `file://` 本地路径即可，无需搭服务器。策略为
“需要重启浏览器生效”，所以写入后要重启一次 Edge。

关于用户级策略：`InternetExplorerIntegrationSiteList` 在微软官方 ADMX 模板里标记为
`class="Both"`，也就是同时支持“当前用户（HKCU）”和“整机（HKLM）”。本工具默认写入
HKCU，因此**在没有 IT 统一管控的普通电脑上，整过流程都不需要管理员权限**。

## 界面速览

主界面从上到下分几块，各按钮的作用如下：

| 位置 | 元素 | 作用 |
| --- | --- | --- |
| 顶部状态区 | 站点列表 / 策略 / Edge 三个彩色芯片 | 一眼看到列表是否正常、策略是否写入、Edge 是否在运行；悬停看完整说明 |
| 顶部按钮区 | 写入 / 更新策略 | 把当前范围（当前用户 / 整机）的策略写入注册表 |
| | 环境诊断 | 收集系统、Edge 版本、策略、权限等信息，输出到日志，便于排查 |
| | 刷新状态 | 重新读取列表 / 策略 / Edge 状态，刷新上面的芯片 |
| | 深色模式 | 切换浅色 / 深色主题，选择会被记住 |
| 月度模板行 | 本月 / 下月 / 下下月 | 选择要生成的月份 |
| | 生成到输入框 | 按模板算出网址，填到右侧“添加 / 修改”里，方便先看一眼再添加 |
| | 一键添加该月全部 | 把启用模板的当月网址一次性加进列表 |
| | 管理模板 | 新建 / 编辑 / 删除月度模板 |
| 左侧列表 | 筛选 + 清空 | 按关键字过滤网址 |
| | 添加 / 修改 / 删除 | 维护选中的条目（可多选删除） |
| | 批量粘贴 / 从剪贴板粘贴 | 一次加多条网址 |
| 右侧表单 | 网址 / 打开方式 / 备注 | 编辑单条记录；打开方式见下文“三种打开方式” |
| 底部操作栏 | 移除策略 | 删除本工具写入的策略值 |
| | 重启 Edge 生效 | 强制关闭并重新打开 Edge，让新策略立即生效 |
| | 打开检查页 | 先自检（列表、注册表、权限），给出结论，再打开 `edge://policy` 和 `edge://compat/enterprise` 供人工复核 |
| | 导出 .reg | 把策略导出成注册表文件，便于交给 IT 或手动导入 |
| | 更多 ▾ | 复制列表路径、打开数据文件夹 |
| | 关于 ▾ | 版本号、检查更新、打开下载页、联系作者；检测到新版时按钮右侧会亮红点 |
| 日志区 | 日志 | 默认高度已调高；可拖动上沿分隔条自由调整高度，右侧可清空日志、开关自动滚动 |

## 快速开始

### 1. 运行

需要 Windows 上已安装 Python 3.9 及以上（含 tkinter，官方安装包默认自带）。

- 双击 `start_gui.bat`；或
- 在命令行执行：

  ```powershell
  py -3 run_gui.py
  ```

> 如果 `python` 命令不可用，请改用 `py -3`。`start_gui.bat` 会依次尝试
> `pyw`、`py`、`python`。

### 2. 添加要自动用 IE 打开的网址

在右侧“添加 / 修改”里填入网址，打开方式默认“强制 IE 模式”，点“添加”。

网址写法：**直接写域名和路径，不要带 `http://`**。

- 建议：`report.contoso.com` 或 `report.contoso.com/2026/10`
- 工具会自动把误填的 `http(s)://` 前缀去掉，因为不带协议时能同时匹配 http 与 https。

一次要加很多条时，用“批量粘贴（每行一个网址）”，或点“从剪贴板粘贴”后“批量添加”。

### 3. 写入策略

点底部的 **写入 / 更新策略**。默认范围是“当前用户 (免管理员)”。
写入后点 **重启 Edge 生效**（会强制关闭所有 Edge 窗口后重新打开）。

### 4. 验证

点 **打开检查页**。它会先自检并给出结论，再打开两个页面核对：

- `edge://policy`：搜索 `InternetExplorerIntegration`，应看到两条策略且值为已启用。
- `edge://compat/enterprise`：查看 Edge 实际加载到的站点列表内容。

然后访问目标网址，地址栏右侧应出现 IE 模式图标，或直接进入 IE 模式。

### 每月例行

如果同一个域名只在路径上按月变化，直接加一次域名即可，之后无需再动。

如果确实要按月份分别登记不同网址，用上方的 **月度模板**：

1. 点 **管理模板** 新建一条模板，例如
   `report.contoso.com/{yyyy}{MM}/index.html`；
2. 勾选“纳入一键添加该月全部”，保存；
3. 回到主界面，选择“本月 / 下月 / 下下月”，点 **一键添加该月全部**；
4. 点 **写入 / 更新策略**，再重启 Edge。

可用占位符：`{yyyy}` `{yy}` `{MM}` `{M}` `{QQ}` `{Q}` `{dd}`。

## 三种打开方式

| 选项 | 写入值 | 适用场景 |
| --- | --- | --- |
| 中性(跟随来源) | `None` | 从哪个浏览器进入就用哪个引擎，最安全，适合 SSO / 单点登录域名 |
| 强制 IE 模式 | `IE11` | 必须使用 IE 内核的老系统 |
| 强制 Edge | `MSEdge` | 需要把登录域名排除在 IE 之外的场景 |

> 只配“中性”的域名不会自动切到 IE，需要手动点“在 IE 模式下重新加载”。
> 想让页面**自动**用 IE 模式打开，请用“强制 IE 模式”。

## 深色模式

顶部按钮区的 **深色模式** 复选框可以随时切换主题，选择会写入 `config.json`
并在下次启动时沿用。浅色 / 深色两套配色都经过对比度检查，日志里的
普通 / 成功 / 警告 / 错误行在两种主题下都清晰可辨。

## 自动更新（检查更新）

界面 **关于 ▾ → 检查更新** 会联网比对 GitHub 上的最新版本：

- 有新版本时，**关于**按钮右侧会亮起一个红点提醒，并弹出更新说明；
- 确认后开始下载，日志区上方显示**下载进度条**，可以随时点 **取消下载**；
- 下载完成后校验 SHA-256，通过才替换当前 exe 并自动重启，不通过会丢弃并报错；
- 已是最新版本时给出提示，不弹红点。

更新源默认是本项目的 GitHub 仓库（`paynehe3023/EdgeIEManager`），
版本信息来自仓库 `main` 分支的 `version.json`，安装包来自
`releases/latest/download/EdgeIEManager.exe`。可以在 `config.json` 里改
`update_repo`（格式 `owner/repo`）指向自己的仓库，`update_auto_check`
控制启动后是否静默检查一次。不想自动检查时，把 `update_auto_check` 设为 `false`。

> 更新只替换程序本体，`%LOCALAPPDATA%\EdgeIEManager\` 下的配置和站点列表不受影响。
> 想本地验证更新流程（不碰线上），见 [docs/update-testing.md](docs/update-testing.md)。

## 命令行用法

适合放进脚本或计划任务。入口是 `run_cli.py`：

```powershell
py -3 run_cli.py list                         # 列出站点列表
py -3 run_cli.py add report.contoso.com       # 添加一条（默认强制 IE）
py -3 run_cli.py add report.contoso.com --mode neutral --note 登录
py -3 run_cli.py remove report.contoso.com    # 删除一条
py -3 run_cli.py add-month --month-offset 0   # 按模板添加本月网址
py -3 run_cli.py add-month --month-offset 1   # 添加下月
py -3 run_cli.py check                        # 检查网址是否符合规范
py -3 run_cli.py diagnose                     # 输出环境诊断
py -3 run_cli.py restart-edge                 # 重启 Edge
py -3 run_cli.py policy install               # 写入策略
py -3 run_cli.py policy install --elevate     # 权限不足时直接弹 UAC 提权重试
py -3 run_cli.py policy status                # 查看策略状态
py -3 run_cli.py policy uninstall             # 删除本工具写入的策略
py -3 run_cli.py policy export-reg            # 导出 .reg 文件
```

`policy install` 还支持 `--refresh <分钟>` 设置站点列表自动刷新间隔。

所有命令都支持 `--config <路径>` 指定配置文件，方便做便携 / 多份配置；
`--site-list <路径>` 可以临时指定站点列表文件。

## 文件位置

默认工作目录：

```
%LOCALAPPDATA%\EdgeIEManager\
    config.json          # 配置、模板、主题、更新源、上次使用的策略范围
    sitelist.xml         # 站点列表（策略指向的文件）
    sitelist.xml.meta.json  # 备注等本地信息（保持 XML 干净合规）
    backups\             # 自动备份，最多保留 20 份
    gui-crash.log        # 仅在界面启动失败时生成
```

用 `--config <路径>` 启动时，站点列表默认放在该配置文件所在目录，便于便携使用。
界面底部的 **更多 ▾** 菜单里有 **复制列表路径** 和 **打开数据文件夹**。

打包版里还有一个 **EdgeIEManager-Clean** 便携版：它不读写默认的用户目录，
所有数据都放在 exe 同级的 `EdgeIEManager-Clean-Data\` 下，适合放在 U 盘或
不想留下痕迹的场景。

## 回滚 / 卸载

工具只动它自己写入的那几个注册表值，不会影响 IT 下发的其它策略。

- 界面里把“策略范围”切到对应范围，点 **移除策略**（整机范围需要管理员）；
- 或命令行：

  ```powershell
  py -3 run_cli.py policy uninstall
  ```

- 也可用 **导出 .reg** 生成注册表文件，交给 IT 或手动导入。

删除策略值并重启 Edge 后，IE 模式配置即回退到系统原有状态。

## 管理员权限与策略范围

- **当前用户 (HKCU)**：默认选项，免管理员，只影响当前登录用户，适合个人电脑。
- **整机 (HKLM)**：影响所有用户，需要管理员权限。选择后写入会弹出 UAC；
  也可以导出 `.reg`，右键“以管理员身份”导入。

机器策略优先级高于用户策略。若所在电脑由 IT 统一管理，已有机器级策略可能覆盖本工具，
用 **环境诊断**（界面“环境诊断”按钮或 `diagnose` 命令）可以看到实际生效的策略地址。

### 单位管控电脑上的“拒绝访问”（WinError 5）

有些单位会把 `HKCU\SOFTWARE\Policies` 的权限收紧：所有者是 `SYSTEM`，普通账户只有
只读权限，只有 `SYSTEM` 和 `Administrators` 能写入。这种情况下即使是“当前用户”策略，
也会写入失败并提示 **拒绝访问（WinError 5）**。

本工具会自动识别这种失败：

- 图形界面会提示“需要管理员权限”，确认后弹出 UAC，以管理员身份重试；
  提权后会显式把策略写回**当前账号自己的注册表 hive**（`HKEY_USERS\<你的 SID>`），
  保证“当前用户”范围真正对自己生效；
- 命令行加 `--elevate` 即可：

  ```powershell
  py -3 run_cli.py policy install --elevate
  ```

- 也可以右键 `start_gui.bat` → “以管理员身份运行”，让整个界面在管理员权限下工作；
- 若当前账户本身没有管理员权限，可点 **导出 .reg** 生成注册表文件，
  交给 IT 或由具备管理员权限的人导入。

> 在这种被锁成只读的环境里，**每次写入/删除策略都会弹一次管理员确认**；
> 写完之后，日常新增站点不会再弹。日志里对应的提示会以红色显示，提醒你这一次需要提权。

## 打包成独立 exe（可选）

想发给没有 Python 的同事时，可用 PyInstaller 打包。仓库里附带
`build_exe.ps1`，它会先检查 PyInstaller 是否已安装：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

若提示未安装，先执行：

```powershell
py -3 -m pip install pyinstaller
```

默认会一次生成三个 exe（都在 `dist\` 下）：

| 文件 | 说明 |
| --- | --- |
| `EdgeIEManager.exe` | 主程序（无控制台窗口），发给普通用户，也是自动更新要下载的那个文件 |
| `EdgeIEManager-Clean.exe` | 便携版，数据只写在自身目录，不碰默认用户目录 |
| `EdgeIEManager-CLI.exe` | 命令行版，配合参数使用，适合脚本 / 计划任务 |

图标取自 `image\appIcon.ico`（exe 图标）和 `image\appIcon.png`（窗口图标，会打包进去）。

## 发布新版本（维护者）

版本号只有一个来源：`edge_ie_manager\version.py` 里的 `__version__`。
发布流程：

1. 修改 `edge_ie_manager\version.py` 的 `__version__`（例如 `1.1.0`）；
2. 运行打包脚本（它会自动同步版本号和校验值）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
   ```

   脚本会先调用 `tools\sync_version.py`，把版本号写进
   `packaging\version_*.txt` 和 `version.json`；打包结束后再把
   `dist\EdgeIEManager.exe` 的 `sha256` 和文件大小写回 `version.json`，
   用于更新包完整性校验；
3. 提交并推送 `main`（`version.json` 必须在 `main`，更新器从
   `raw.githubusercontent.com` 读取）；
4. 在 GitHub 新建 **Release**，tag 用 `vX.Y.Z`（如 `v1.1.0`），
   **资源名必须叫 `EdgeIEManager.exe`**，上传的就是刚打出来的
   `dist\EdgeIEManager.exe`（这样 `version.json` 里的 sha256 才对得上）；
   可选一并上传 `EdgeIEManager-CLI.exe`；
5. 建议把该 Release 设为 latest，更新器默认从
   `releases/latest/download/EdgeIEManager.exe` 下载。

> 顺序提醒：`version.json` 一旦推送到 `main`，老版本就会看到新版本号。
> 如果此时对应的 Release / 资源还没建好，点下载会拿不到文件或校验失败。
> 稳妥的做法是先建好 Release（含 `EdgeIEManager.exe`），再推 `version.json`，
> 或两者尽量同时完成。

`version.json` 字段：`version`（版本号）、`notes`（更新说明，弹窗里展示）、
`download`（下载地址，留空则用默认 Releases 地址）、`sha256`、`size`。

## 常见问题

**改了站点列表，Edge 没反应？**
策略和站点列表都是启动时读取的，重启一次 Edge。必要时在 `edge://compat/enterprise`
确认列表已加载、修订号已更新。

**`edge://policy` 里看不到策略？**
确认写入的范围（当前用户 / 整机）和查看的账户一致；整机策略要管理员权限；
写入后必须重启 Edge。

**加了域名，为什么浏览器仍提示要手动在 IE 模式打开？**
多半是这条记录的打开方式设成了“中性”。改成“强制 IE 模式”即可自动切换。

**会不会覆盖公司下发的策略？**
不会。本工具只新增 / 删除自己管理的几个值；机器策略存在时仍以机器策略为准。

**检查更新一直停在“正在检查更新…”？**
多半是本机访问 GitHub（`raw.githubusercontent.com` / `api.github.com`）受限或很慢。
可以点 **关于 ▾ → 打开下载页** 手动下载，或到“设置 → 网络”排查代理。
想在本机验证更新逻辑，见 [docs/update-testing.md](docs/update-testing.md)。

**更新过程中能取消吗？会影响我的数据吗？**
下载时可以点 **取消下载**；取消只会丢弃临时文件，不会改动现有程序和数据。
更新只替换 exe，配置与站点列表都保留。

## 开发与测试

项目只用 Python 标准库，测试用 `unittest`：

```powershell
py -3 -m unittest discover -s tests -t . -v
py -3 -c "from edge_ie_manager.gui import smoke_test; print(smoke_test())"
```

目录结构：

```
edge_ie_manager/     # 主程序包
    app.py           # 不依赖界面的高层操作，CLI 与 GUI 共用
    model.py         # 站点列表数据模型
    config.py        # 配置与本地文件位置
    sitelist.py      # 站点列表读写、备份、修订号
    templates.py     # 月度模板与占位符
    policy.py        # 注册表策略读写、.reg 导出、提权
    diagnostics.py   # 环境诊断、Edge 启动 / 重启
    update.py        # 检查更新、下载、校验、自替换
    theme.py         # 浅色 / 深色主题
    runtime_env.py   # 清理 PyInstaller 引导变量，保证自重启正常
    cli.py           # 命令行接口
    gui.py           # tkinter 图形界面
    version.py       # 版本号唯一来源
tests/               # 单元测试
docs/                # 补充文档（如自动更新测试方法）
tools/               # sync_version.py、本地假更新源等开发工具
packaging/           # PyInstaller 版本资源模板
image/               # 图标资源
run_gui.py           # 图形界面入口
run_gui_clean.py     # 便携版图形界面入口
run_cli.py           # 命令行入口
start_gui.bat        # 双击启动图形界面
build_exe.ps1        # PyInstaller 打包脚本
version.json         # 发布清单（版本号、更新说明、sha256、大小）
```
