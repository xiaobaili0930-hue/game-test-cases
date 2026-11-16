# 游戏项目

本仓库包含两个独立项目。

| 文件夹 | 项目 | 入口 |
| --- | --- | --- |
| [dragon_island](dragon_island/) | 蛋蛋龙 · 浮岛日记，浏览器养龙游戏 | 打开 `dragon_island/index.html` |
| [mumu_relic](mumu_relic/) | MuMu 遗迹探险自动操作脚本 | 本机 Python + ADB，运行 `mumu_relic/bot.py` |

## 养龙网页游戏

全部网页源码、说明、参考资料和测试已归入 `dragon_island/`。可直接打开其中的 `index.html`，或在该文件夹执行：

```sh
python -m http.server 8000 --bind 127.0.0.1
```

然后访问 `http://127.0.0.1:8000/`。如果从仓库根目录启动服务器，则访问 `/dragon_island/`。原游戏代码和静态资源保持原样；详细玩法和测试说明见 [养龙游戏说明](dragon_island/README.md)。

## MuMu 探险脚本

[安装、试运行、自动点击及更新说明](mumu_relic/README.md)。

基础胜率 ≥30% 战斗，低于 30% 撤离，不计右侧加成。包含主页、前进、分段胜率识别、结算“收下”和宝物弹窗处理。默认只识别，添加 `--run` 才会点击；Ctrl+C 停止。

代码更新到云仓库后，仍需下载到电脑并重启脚本；云仓库不能直接控制本机 MuMu。

本次新增脚本已通过本地判断逻辑测试，尚未在用户 MuMu 上验证完整流程。
