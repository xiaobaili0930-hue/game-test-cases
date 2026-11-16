# MuMu 遗迹探险助手

通过 ADB 截图、OCR 识别和点击控制本机 MuMu，独立于仓库根目录的网页游戏。

## 规则与已支持页面

- 去探险、前进。前进文字漏识别时，使用底部中央绿色圆环与橙色火把的图像特征兜底；倍率、角色名和火把数量不参与判断。图像兜底仍需探险标题，并排除识别到的 Boss、结算和宝物弹窗提示，保留连续两帧确认。
- Boss：基础胜率达到 30% 战斗，低于 30% 撤离；忽略右侧加成，例如 `29% + 8%` 撤离，`30% + 5%` 战斗。
- 兼容“我方胜率”和数字分成两个 OCR 文本框的情况，核对它们的位置。
- 宝物展示：识别“点击任意位置继续”后点画面中央。
- 探险结束：核对标题后点击“收下”。
- 连续两次识别结果与按钮位置一致才点击。连续至少 12 次、且持续 25 秒无法识别则退出，并在当前工作文件夹保存 `unrecognized.png`、含置信度和归一化坐标的 `unrecognized.json`。

## Windows 使用

安装 Python（建议 3.11），在命令提示符执行：

```bat
py -m pip install rapidocr-onnxruntime pillow numpy
```

MuMu 中开启本地 ADB。使用 MuMu 自带 ADB 或 Google 官方 Platform Tools 内的 adb.exe。端口以 MuMu 设置为准，此例使用本次用户已连接成功的 16416。

将本目录的 `bot.py` 放到 `adb.exe` 所在文件夹，在该文件夹地址栏输入 `cmd` 并回车。打开游戏竖屏探险主页，先试识别：

```bat
py bot.py --adb ".\adb.exe" --serial 127.0.0.1:16416
```

默认只识别、不点击。确认输出正确后，按 Ctrl+C，再启动实际点击：

```bat
py bot.py --adb ".\adb.exe" --serial 127.0.0.1:16416 --run
```

Ctrl+C 停止。无法识别时，查看保存的截图和 JSON，手动处理页面后重新启动。不要同时运行多个脚本实例。

## 双击自动更新并启动（Windows）

首次下载同目录的 `update_and_start.bat`，保存到本机 `adb.exe` 所在文件夹（扩展名应为 `.bat`，不要保存成 `.bat.txt`）。

以后停止旧脚本，双击该文件，按提示按任意键即可。它会下载 GitHub main 分支最新版、校验 Python 语法、备份原 bot.py，然后启动实际点击模式，连接地址默认 `127.0.0.1:16416`。启动期间不要再打开另一个脚本实例。

这是启动时更新，运行期间不会自动替换代码。更新失败时不启动脚本。仅更新 bot.py，不更新 Python 依赖；需要新增依赖时另行安装。本批处理已检查命令结构，尚未在 Windows / MuMu 实机运行。

## 后续更新

停止正在运行的脚本并备份本地 `bot.py`。可以在 GitHub 打开本目录的 `bot.py`，使用 Download raw file 下载，覆盖原文件后重新运行。仅把代码上传仓库不会自动更新电脑上的脚本，云端也不能直接访问本机 MuMu。

如果仓库可匿名访问，也可以在 adb.exe 文件夹中执行下面命令下载最新代码（覆盖前自动备份；GitHub 不可访问或仓库私有时请使用网页登录下载）：

```bat
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; if(Test-Path bot.py){Copy-Item bot.py ('bot_backup_'+(Get-Date -Format yyyyMMdd_HHmmss_fffffff)+'.py')}; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/xiaobaili0930-hue/game-test-cases/main/mumu_relic/bot.py' -OutFile bot_update.tmp; Move-Item -Force bot_update.tmp bot.py"
```

## 验证与限制

在本目录运行 `py -m unittest -v`，安装 Pillow、NumPy 后即可验证判断逻辑，无需初始化 OCR 引擎。已覆盖 29/30 边界、忽略右侧加成、分段胜率、低置信度拒绝、主页/前进、结算和宝物弹窗。

阈值依据本次用户实际 OCR 日志校准；宝物和结算弹窗依据截图实现，仍需实机确认。字体、分辨率、布局或游戏更新可能导致识别失败。OCR 不能保证数字完全正确；未知页面会暂停。当前未连接用户 MuMu 做端到端验证。

### 前进图像识别验证

新增按钮文字缺失、无标题、Boss/宝物弹窗提示和暗色遮罩的回归检查，共 8 项测试通过。另使用用户之前上传的视频抽取 13 帧进行图像识别检查，正常前进按钮被识别，Boss/结算/暗色宝物弹窗未触发前进。最新版仍需用户 MuMu 实机验证；布局变化时可能继续暂停。

### 操作速度

识别轮次之间等待 0.5 秒；普通点击后等待 1.2 秒，战斗/撤离后等待 2.5 秒，替代原先点击后 5 秒加轮次 2 秒的固定等待。每次仍需连续两次识别结果与位置一致才点击。OCR、ADB 和游戏动画本身仍需时间；不是每 0.5 秒必定点击一次。加速后未知画面仍会等待至少 25 秒才暂停，避免动画被提前判定失败。已通过语法检查和既有 8 项判断测试，速度效果需在本机 MuMu 验证。
