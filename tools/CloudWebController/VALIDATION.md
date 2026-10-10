# 本次验证记录

基线：`cnflwzh/MaaEnd` 的 `v2`，提交 `c7b53eba43d29192f9af878fc1e364176763832a`。所有改动仅位于 `tools/CloudWebController/`；交付到 fork 的独立实验分支，不创建上游 PR 或发布。

## 环境

Linux x86_64 / Debian 13，Python 3.12.14，GCC 14.2，CMake 4.4.4，PySide6 6.12.0，Qt WebEngine 6.12.0.140，MaaFramework 5.14.2。Qt 使用官方 offscreen 平台，未关闭 Chromium 沙箱。没有操作已有浏览器会话。

Windows/macOS 只有共用代码与依赖方案，未编译/运行当地安装包；Windows 原生 C++ WebView2 宿主同样未编译/运行。

## 通过：真实 Maa + 内嵌 Qt 的 13 项离屏检查

1. Maa 自定义控制器连接
2. 等待可见内容首次绘制（不是只等 loadFinished）
3. Maa 点击任务返回成功
4. 页面按钮确实收到点击
5. Maa 按键任务返回成功
6. 页面确实收到 W 键
7. 原生点击使文本框获得焦点
8. Maa 文本任务返回成功
9. 页面收到完整文本
10. 本地 canvas→video 产生视频帧
11. 视频解码帧计数继续增加
12. 两次 Maa 截图的视频区域像素确实变化
13. inactive 正常完成

截图经 Maa 返回，尺寸为 1280×720、三通道 BGR。连续三次独立启动、运行上述检查、退出均成功（每次退出码 0）。

**这段通过的视频是本地 canvas→video，没有网络，也没有云服务器。** 页面本身明确标注。它验证嵌入浏览器视频画面的截图链路，不验证 WebRTC 或真实云游戏。

## 通过：13 项 Qt 生命周期检查

就绪、首次绘制、图像深拷贝、越界输入拒绝、隐藏拒绝、最小化拒绝、恢复截图、第二宿主启动、超时报告、过期回调不执行、超时后禁止输入、关闭取消等待中的截图、关闭后拒绝输入。

这些是在离屏平台验证的状态/像素行为；不代表真实桌面遮挡、系统焦点或后台窗口已经通过。

另外，原生连接选择器的默认安全模式、三种选项、输入框启用状态和非法 URL 拒绝检查通过。

## 通过：纯逻辑/构建检查

- CMake 配置和 GCC 编译成功，CTest 两项全部通过
- C++ URL/坐标/JSON/按键策略：35 项断言
- C++ 异步完成/超时/取消：含 100 次竞争完成检查
- Python Qt 策略：7 个测试，包括敏感 URL 日志脱敏、禁用沙箱与远程调试配置拒绝
- Python 模块语法编译通过

## 未通过与未验证

### 本地 WebRTC 回环

显式 `--video-source webrtc` 的输入检查通过，视频帧检查失败。执行环境日志显示 mDNS responder 无法启动，网络相关 socket 能力受限。没有为此降低隐私或关闭沙箱。此结果独立保存，不与 canvas→video 的通过结果混用。

### 真实公开串流

尝试的是 Eagle 3D 官方公开 Unreal Pixel Streaming 示例，不需账号或付费：

`https://connector.eagle3dstreaming.com/v5/demo/EpicPixelStreamingSample/E3DS-Iframe-Demo`

页面普通加载先出现 `ERR_EMPTY_RESPONSE`；按执行环境已有 HTTP 代理配置正常请求后，出现 `CertificateErrorDomain / -202 / ERR_CERT_AUTHORITY_INVALID`。保留证书校验并停止，没有继续绕过。因此真实云端画面、输入往返延迟、队列、编码、DRM 和 Pointer Lock 均未验证。

### 真实桌面与发布

命令执行环境没有可用 DISPLAY，私有 Xvfb 的本地显示 socket 启动失败；受支持的提权重试也未成功。使用不需 X 显示 socket 的 Qt offscreen 完成了上述有限检查。这不等于其他桌面工具或整台云电脑都没有图形能力。

需要后续验证：Windows/macOS 实机、Linux 桌面 X11/Wayland、125%/150% DPI、遮挡/失焦、GPU 视频路径、断网/重连、真实云服务。隐藏/最小化目前按“不支持”明确失败。

## 正式接入前仍需做

- 与外部 MXU GUI 协调自定义控制器工厂、连接列表和生命周期
- 绑定 Tasker/资源及 Agent，验证原有任务对控制器类型和图像的假设
- 按真实画面实现具体站点的登录/排队状态，不猜测 ROI 或游戏流程
- 扩充实际需要的鼠标相对移动、Pointer Lock、滚轮等操作
- 三端打包、许可证/依赖检查和原生运行验证

登录/排队与底层桥接已分离，但未来兼容新游戏不能保证只改两个页面。
