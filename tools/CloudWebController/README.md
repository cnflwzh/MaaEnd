# CloudWebController：三端嵌入网页控制器实验

当前交付目标是原 MaaEnd 界面的完整集成包，见 [集成构建与开发规范](integration/README.md)。下列独立入口保留为内部开发检查，不作为完整程序交付。官方网页入口与真实游戏画面尚未提供；登录、排队、DRM、Pointer Lock 和任务兼容性不能靠本地测试页推定。

## 当前结构

- `qt_launcher.py`：原生连接选择器，默认离线页，可选择明确的 HTTPS 地址或公开串流示例
- `qt_host.py`：共用 Qt WebEngine 内嵌窗口，Windows/macOS/Linux 使用同一接口；不是外部 Chrome
- `qt_controller.py`：MaaFramework Python `CustomController`，负责截图、点击、按键和文本桥接
- `service_adapters.py`：站点入口与状态层，与控制器分离；目前仅手动预览，不自动登录或跳过排队
- `qt_main.py`、`fixture.html`：端到端检查、诊断截图与命令行实验入口
- C++ 文件：先做的 Windows 原生 WebView2 实验后端，独立保留；尚未在 Windows 编译/运行

MaaEnd 的 GUI 来自发布时下载的外部 MXU，并不是本仓库内的 Tauri 应用。Project Interface V2 没有可直接交给 MXU 实例化的 `Custom`/`WebView2` 类型。集成版使用独立的 `mxu-cloudweb.json` 客户端配置及可重现的 MXU 补丁，不向 `assets/interface.json` 写入无效类型。

完整程序通过 MXU 原有连接选择器创建自定义控制器，再由原 Tasker/Agent 运行原任务。`mxu_host.py` 是包内浏览器组件；下文 `qt_main.py` 独立测试入口不运行游戏任务。

## 快速运行共用 Qt 入口

测试依赖为 Python 3.12、PySide6 6.12.0、MaaFramework 5.14.2。依赖仅安装到独立环境，不改变 MaaEnd 的默认依赖。

```sh
python -m venv .venv-cloudweb
# Linux/macOS
.venv-cloudweb/bin/python -m pip install -r tools/CloudWebController/requirements-qt.txt
.venv-cloudweb/bin/python tools/CloudWebController/qt_launcher.py

# Windows
.venv-cloudweb\Scripts\python -m pip install -r tools/CloudWebController/requirements-qt.txt
.venv-cloudweb\Scripts\python tools/CloudWebController/qt_launcher.py
```

这是源码运行方式，不是已制作完成的三端安装包。Windows/macOS 仍需安装相应平台依赖并实机验收；本次只在 Linux 执行环境运行了 Qt 离屏测试。

命令行也可直接使用：

```sh
# 默认：安全离线页。连接、截图、点击、W 键、文本和本地视频像素检查
python tools/CloudWebController/qt_main.py --output cloudweb-results

# 单独测试本地 WebRTC，不能与真实云串流等同
python tools/CloudWebController/qt_main.py --video-source webrtc --output cloudweb-webrtc-results

# 手动网页预览，不自动登录、排队或启动服务
python tools/CloudWebController/qt_main.py --connection embedded-webview --url https://example.com/ --keep-open

# 官方免账号 Unreal Pixel Streaming 示例，仍可能有容量队列
python tools/CloudWebController/qt_main.py --connection eagle-public-demo --keep-open
```

远程预览默认不保存截图、不发送自动输入。`--interactive` 是开发用 stdin JSON 命令入口，仅接受 capture/click/key/status/quit，没有网络端口或页面可调用的 API。`--allow-origin` 仅用于明确核实过的顶层跳转源；不要为登录失败随意放宽。需要当前执行环境已配置的 HTTP 代理时，可显式加 `--use-environment-proxy`；不接受代理账号密码、不修改系统代理、不绕过证书。

### 无桌面的 Linux 检查

```sh
QT_QPA_PLATFORM=offscreen QT_OPENGL=software QT_QUICK_BACKEND=software LIBGL_ALWAYS_SOFTWARE=1 \
  python tools/CloudWebController/qt_main.py --output cloudweb-results
```

离屏像素和原生 Qt 输入链路可测，**真实桌面的遮挡、焦点、最小化和 GPU 行为不可由此宣称通过**。请勿添加 `--no-sandbox` 或关闭证书校验；宿主拒绝继承关闭沙箱或启用远程调试的配置。

## 支持范围与边界

- 固定 1280 × 720 逻辑坐标；高 DPI 图像归一化为 Maa 的 BGR8 像素
- Maa Post/Wait 接口真实驱动截图、左键点击、字母/数字/方向键/空格/回车/Esc；Qt 还支持 Tab/退格和文本输入
- 所有 Qt 操作投递到 UI 线程；Maa 回调在自己的工作线程等待
- 超时后禁用输入，忽略尚未执行的过期请求；关闭会取消等待。已发送的输入不能撤销，也不盲目重试
- 隐藏/最小化时明确失败，避免把白屏或旧图冒充成功截图
- 滑动、多点触控、滚轮、相对鼠标/Pointer Lock、Shell、启动/停止 App 尚不支持

未来新增游戏站点时，登录/排队应放在独立适配层，但**不能保证只改登录和排队就能兼容**：输入映射、焦点、坐标、视频编码、延迟、DRM 和后台渲染都需要实测。

## 安全边界

Qt 入口使用隔离的 off-the-record profile、内存缓存、非持久 Cookie；不注入 JS 主机对象、不提供网页到本地的 IPC/HTTP/WebSocket，不启动远程调试端口。

只接受明确的 HTTPS/默认 443 URL；拒绝凭据、歧义地址及非 ASCII 主机。顶层导航限于已配置来源。远程 HTTPS 子框架、CDN 和 WSS 媒体资源可以使用，但不能访问本地文件或启动外部协议；这是浏览器宿主边界，不是完全网络沙箱。

下载、弹窗、文件选择、证书例外、设备权限、系统凭据、WebAuthn、网页访问文件系统和外部协议注册均不自动允许。当前原型请勿登录真实账号或付费。Windows 原生 WebView2 后端采用独立临时 profile，清理尽力而为；浏览器未释放文件时可能留在系统临时目录。

## 验证

详见 [VALIDATION.md](VALIDATION.md)，包含已通过的 13 项 Maa 端到端检查和 13 项生命周期检查，以及证书/网络限制下未通过的真实串流测试。

```sh
python -m unittest discover -s tools/CloudWebController -p test_qt_policy.py
QT_QPA_PLATFORM=offscreen python tools/CloudWebController/test_qt_lifecycle.py

# 两个独立 C++20 核心测试；不需要 Windows SDK
cmake -S tools/CloudWebController -B build-cloudweb-tests
cmake --build build-cloudweb-tests
ctest --test-dir build-cloudweb-tests --output-on-failure
```

本次没有改动 `assets/**`、`tests/**` 或 schema，遵循仓库说明没有运行全量 `pnpm check`/`pnpm test`。

## 可选 Windows 原生 WebView2 后端（未编译验证）

需要 VS 2022 C++ 工具链、CMake、WebView2 Evergreen Runtime、相同架构的 MaaFramework 5.14.2 SDK，以及 Microsoft.Web.WebView2 1.0.2210.55 SDK。后者可复用仓库已有 `python -m tools.setup.dep_3rdparty --webview2` 或官方 NuGet 包。

```powershell
cmake -S tools/CloudWebController -B build-cloudweb -A x64 `
  -DMAAEND_BUILD_CLOUD_WEB_HOST=ON `
  -DMAAFW_SDK_DIR=C:/SDK/MaaFramework `
  -DWEBVIEW2_SDK_DIR=C:/SDK/Microsoft.Web.WebView2
cmake --build build-cloudweb --config Release
./build-cloudweb/Release/maaend-cloud-web.exe
```

此构建复制完整 SDK `bin`（包括 `MaaCustomControlUnit.dll`）及 WebView2Loader。它不替代三端共用 Qt 入口，也不参与正式打包。其离线测试使用自己的静态测试页；视频与 Qt 生命周期检查不能算作 WebView2 检查。

## 参考

- [MaaFramework 5.14.2 自定义控制器](https://github.com/MaaXYZ/MaaFramework/blob/v5.14.2/include/MaaFramework/Instance/MaaCustomController.h)
- [Project Interface V2](https://github.com/MaaXYZ/MaaFramework/blob/v5.14.2/docs/en_us/3.3-ProjectInterfaceV2.md)
- [Qt WebEngineView](https://doc.qt.io/qtforpython-6/PySide6/QtWebEngineWidgets/QWebEngineView.html)
- [Eagle 3D 官方免账号 iframe 示例说明](https://learn.eagle3dstreaming.com/wiki/iframe-demo-manual)
- [WebView2 安全实践](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security)
