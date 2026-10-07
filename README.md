# Edge IE 模式站点管理器

一个零依赖的 Windows 小工具，用来管理 Microsoft Edge 的 **IE 模式站点列表**。
把需要在 IE 模式下打开的网址登记一次，以后 Edge 就会按照这份列表自动用 IE 模式打开，
不必再每个月到 `edge://settings` 里手动添加上一次。

工具提供图形界面（tkinter）和命令行两种用法，只用 Python 标准库，不需要安装任何第三方包。

## 这个工具解决什么问题

Edge 的 IE 模式依赖一份“企业模式站点列表（Enterprise Mode Site List）”，
再由一条系统策略把 Edge 指向这份列表。手动维护很麻烦，本工具负责：

- 用合适的格式（schema v.2）生成和维护 `sitelist.xml`；
- 每次保存自动递增修订号、自动备份旧文件；
- 一键把策略写入注册表（当前用户可免管理员）；
- 提供月度模板，点一下就能生成“本月/下月”的网址；
- 打开诊断页核对策略是否生效。

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

点 **打开检查页**，会打开两个页面核对：

- `edge://policy`：搜索 `InternetExplorerIntegration`，应看到两条策略且值为已启用。
- `edge://compat/enterprise`：查看 Edge 实际加载到的站点列表内容。

然后访问目标网址，地址栏右侧应出现 IE 模式图标，或直接进入 IE 模式。

### 每月例行

如果同一个域名只在路径上按月变化，直接加一次域名即可，之后无需再动。

如果确实要按月份分别登记不同网址，用右侧的 **月度模板**：

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
    config.json          # 配置、模板、上次使用的策略范围
    sitelist.xml         # 站点列表（策略指向的文件）
    sitelist.xml.meta.json  # 备注等本地信息（保持 XML 干净合规）
    backups\             # 自动备份，最多保留 20 份
    gui-crash.log        # 仅在界面启动失败时生成
```

用 `--config <路径>` 启动时，站点列表默认放在该配置文件所在目录，便于便携使用。
界面底部有 **打开文件夹** 和 **复制列表路径** 两个按钮。

## 回滚 / 卸载

工具只动它自己写入的那几个注册表值，不会影响 IT 下发的其它策略。

- 界面里把“策略范围”切到对应范围，点策略卸载（整机范围需要管理员）；
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
- 命令行加 `--elevate` 即可：

  ```powershell
  py -3 run_cli.py policy install --elevate
  ```

- 也可以右键 `start_gui.bat` → “以管理员身份运行”，让整个界面在管理员权限下工作；
- 若当前账户本身没有管理员权限，可点 **导出 .reg** 生成注册表文件，
  交给 IT 或由具备管理员权限的人导入。

提权只是借用管理员权限去写同一份注册表位置，写入的仍然是当前用户的配置。
界面上还可以用 **移除策略** 按钮随时清理本工具写入的策略值。

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

生成的 exe 在 `dist\` 下。图形版为窗口程序，命令行版可配合参数使用。

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

## 开发与测试

项目只用 Python 标准库，测试用 `unittest`：

```powershell
py -3 -m unittest discover -s tests -t . -v
py -3 -c "from edge_ie_manager.gui import smoke_test; print(smoke_test())"
```

目录结构：

```
edge_ie_manager/     # 主程序包：模型、配置、站点列表、策略、诊断、CLI、GUI
tests/               # 单元测试
run_gui.py           # 图形界面入口
run_cli.py           # 命令行入口
start_gui.bat        # 双击启动图形界面
build_exe.ps1        # 可选：PyInstaller 打包脚本
```
