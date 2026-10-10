MaaEnd 云网页连接实验：完整 Windows x64 便携包

这是完整 MaaEnd 界面的实验构建。入口是根目录的 MaaEnd.exe。
保留原有任务列表、配置和资源，在连接区域增加云网页实验入口。
cloudweb-host 是应用内部使用的浏览器子进程，不是主程序。

1. 将整个 ZIP 解压到一个新的可写文件夹，不要覆盖现有 MaaEnd 安装。
2. 双击 MaaEnd.exe。首次验证请选择本地测试页。
3. 正式网页需要明确 HTTPS 地址。登录、排队和启动服务都由用户手动处理。
4. 不要只复制 EXE；maafw、agent、resource、tasks、cloudweb-host 都必须保留。

本包是便携 ZIP，不是安装程序，未做代码签名。
版本标记为 cloudweb-dev；实验版停用自动更新。更新请重新下载完整实验包，
不要使用正式版更新包覆盖本目录，否则实验控制器可能被替换。
MaaEnd 的 Tauri 主界面使用 Microsoft Edge WebView2；云网页视图使用随包 Qt WebEngine。
如果电脑缺少 WebView2，请使用微软官方网站的安装方式。
不要关闭系统安全功能、Chromium 沙箱或证书校验。

本地测试不代表真实云终末地或所有既有任务已兼容。
实时串流编码、DRM、输入锁定、延迟、站点登录/排队均需实际验收。
不要在此次实验中登录真实账号或付费。

cloudweb-build-info.json 记录源码提交、MXU 基线及补丁、原生运行库版本和文件校验值。
validation 包含实际执行的验证报告和完整主界面截图。
分享 debug 或截图前请检查私人网页、账号和其他个人信息。
LICENSE、licenses 和 cloudweb-host/licenses 包含开源许可材料。
源码见记录的仓库与提交，MXU 改动补丁附在 source/CloudWebIntegration。
mxu-formatted.patch 是 CI 使用预装 rustfmt 格式化后实际参与构建的完整补丁；
对应工具版本保存在验证日志中，可从记录的 MXU 基线提交复现源码。
