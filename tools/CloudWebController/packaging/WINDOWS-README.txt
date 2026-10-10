MaaEnd CloudWeb Controller - Windows x64 portable experiment
云网页控制器实验版：Windows x64 便携包

使用方法
1. 将整个 ZIP 解压到可写的文件夹，不要在压缩包内直接运行。
2. 双击 Start-CloudWeb.cmd，或 MaaEnd-CloudWeb-Prototype.exe。
3. 首次选择「离线测试页」，点击「打开内嵌窗口」。
4. 关闭内嵌窗口后再关闭连接选择器。
5. 运行报告与测试截图保存在 cloudweb-results 文件夹。

这是免安装便携实验包，不是安装程序。无需另装 Python 或 WebView2。
请保留 _internal、licenses、source 和其他随附文件，不要只复制 EXE。
包没有代码签名；如果系统阻止运行，请先核对 SHA256、来源与源码，
不要关闭系统安全功能或绕过浏览器安全警告。

范围与限制
- 后端是 Qt WebEngine，不是 Windows 原生 WebView2，也不是外部 Chrome。
- 本工具只连接 Maa 控制器，不会运行 MaaEnd 游戏任务。
- 它不是已完成的云终末地客户端；登录、排队、DRM、Pointer Lock、
  游戏输入、现有任务、用户电脑上的 GPU/桌面兼容性都仍需验证。
- 默认离线页不连接云服务。自定义网页和免账号公开示例仅供手动预览。
- 请勿登录真实账号或付费。页面权限、下载与弹窗不会被自动批准。
- 不要以管理员身份运行，不要关闭 Chromium 沙箱或证书校验。
- CI 的离线测试通过只证明随附报告里的行为，不证明真实云游戏兼容。

命令行自检（CMD）
MaaEnd-CloudWeb-Prototype.exe --launcher-smoke --output cloudweb-results
MaaEnd-CloudWeb-Prototype.exe --worker --video-source webrtc --output webrtc-results

构建与诊断
build-info.json 包含源码提交与构建依赖版本。
validation 文件夹含 Windows 构建时的日志、截图和机器可读测试结果。
如果运行失败，请保留控制台信息和 cloudweb-results/report.json。
上传或分享诊断文件前请检查是否包含私人网页截图。

开源与替换依赖
LICENSE 是 MaaEnd 的 AGPL-3.0 许可证。source 包含此实验的源码和构建脚本。
licenses 包含各 Python 包的许可证/元数据、Qt 和 Chromium 的许可材料。
第三方库仍适用各自许可证，详见 THIRD-PARTY-NOTICES.txt。
这是 one-folder 动态链接构建；兼容的 Qt/Maa DLL 可以在 _internal 中替换。
可为调试合法修改而重新构建或替换这些开源库，不附加逆向工程限制。

English quick start
Extract the whole archive into a writable folder and run Start-CloudWeb.cmd.
Choose the offline fixture first. Keep every bundled directory alongside the EXE.
This is an unsigned portable prototype, not an installer or a supported MaaEnd
cloud-game release. No real account or payment is needed. The validation reports
describe only the checks actually run, not compatibility with a real cloud game.
