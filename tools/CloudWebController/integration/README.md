# MaaEnd 网页控制器集成

本目录用于构建原 MaaEnd 界面的开发版：右侧「连接设置 → 控制器」增加「云·终末地网页版」，继续使用原有任务列表、Tasker、Agent、实时截图和日志。`cloudweb-host` 是 MaaEnd 管理的内部网页窗口组件，不是另一个任务执行程序，也不是外部 Chrome。

## 配置边界

- MaaFramework 官方 Project Interface V2 不包含 `CloudWeb` 控制器类型；不修改 `assets/interface.json` 的标准类型，也不向任务声明写入未声明的控制器。
- `assets/mxu-cloudweb.json` 是此修改版 MXU 的独立客户端配置，不是 PI V2 扩展版本。`schema_version: 1`、固定的 `controller.name: CloudWeb` 和明确的 `compatible_tasks` / `compatible_options` 列表由客户端验证。
- 客户端加载配置后，在内存中增加网页控制器及对应的任务适用范围。标准 PI 文件仍可被原版工具读取。
- `compatible_tasks` 表示复用哪些已有的跨平台桌面任务入口，不表示这些任务已通过真实云游戏验证。Win32 专属的进程、注册表、账号切换等任务不自动开放。
- 不新增臆造的游戏识别节点、ROI、登录或排队 Pipeline。官方网站可用后，在连接面板填写 HTTPS 地址，手动完成登录、排队并进入游戏画面。

## 数据与生命周期

修改后的 MXU 通过 MaaFramework 官方 `Controller::new_custom` 创建控制器，原 `Tasker` 绑定原资源及该控制器。网页组件只负责截图和输入，不创建第二个 Tasker。

每个实例独立拥有网页会话。宿主使用仅父子进程可见的 stdin/stdout JSON 消息，包含请求 ID、长度限制及超时；不监听网络控制端口。截图是 1280×720 PNG，输入通过 Qt 原生网页视图事件投递。

网页无法调用 Tauri 命令或宿主 API。保留证书验证及 Chromium 沙箱，禁用调试端口、页面文件选择、下载、弹窗及未授权权限。网页控制器不以管理员身份运行。停止任务释放按键和鼠标状态；切换控制器、删除实例和退出程序回收子进程。

## 构建

完整 Windows 包在本地 Windows 构建；本实验分支已移除 push 自动构建触发。`.github/workflows/cloudweb-maaend.yml` 保留为构建步骤参考，不触发 GitHub Actions。交付入口为完整包内的 `MaaEnd.exe`。

MXU 基线固定为 `MistEO/MXU@9fa8cc51e8ff8cd89d99f3ea55fe3a7a82e6ede3`，`mxu.patch` 包含客户端修改。本地从相同 MaaEnd 源码构建 Go/C++ Agent、资源及内部网页组件，再组装 `MaaEnd.exe` 完整目录。

开发检查包括前端类型/构建、客户端配置验证、Go 控制器测试、内部宿主协议与原生输入测试，以及真实 Rust Tasker 与网页组件的集成测试。构建产物里的验证报告是具体运行结果；不能用编译通过代替游戏兼容性测试。

## 开发规范核对

实施前及提交前核对：

- MaaEnd `AGENTS.md`、`docs/zh_cn/developers/coding-standards.md`、`.agents/skills/go-service-guide/SKILL.md`
- MXU `AGENTS.md`、`README.md`、`docs/add-special-task.md`、权限声明和现有控制器/Tasker 实现
- MaaFramework 官方 [Project Interface V2](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/3.3-ProjectInterfaceV2.md) 及所锁定 Rust crate 的 `CustomControllerCallback`

保留标准 PI 文件；UI 文本放入语言包；Go 只做控制适配，不编排游戏流程；按仓库配置格式化 JSON/YAML 和 Go。没有改动 `tests/**`，不额外运行仓库禁止主动执行的全量 `pnpm check` / `pnpm test`，使用与本次修改对应的专项检查。

## 已知边界

登录、排队、DRM、云服务手柄映射、Pointer Lock、GPU/解码能力及网络延迟需要针对真实服务再验证。浏览器窗口隐藏或最小化时会拒绝截图和输入，不能声称最小化后台运行。离线页和本地 WebRTC 回环只能验证桥接链路。

## Windows 本地构建目录

本次开发检出位于 `G:\DevProject\MaaEnd`，隔离 Python 环境、Go 工具链、pnpm、SDK 和新增下载缓存位于 `G:\DevData\MaaEnd`。已有 Rust 工具链和注册表缓存继续使用 `G:\DevData\Rust`。仅对构建进程设置 PATH，不修改系统 PATH。

本地执行上述工作流中的命令体，分别生成 `build-cloudweb-inputs/mxu`、`build-cloudweb-inputs/maaend-runtime` 和 `build-cloudweb-inputs/qt-host`。按用户当前要求，仅构建并执行 `build_full_package.py assemble`、`build_full_package.py archive-unverified`，不运行验收，最终由用户自行测试。包内 `runtime-acceptance.json` 明确记录未验收状态。

界面验证使用临时的 `config/mxu-MaaEnd.json`。打包时恢复干净配置，不保留验证实例或浏览器缓存。主程序目录为 `build-cloudweb-full/MaaEnd-CloudWeb`，便携 ZIP 和校验值位于 `build-cloudweb-full/deliverables`。
