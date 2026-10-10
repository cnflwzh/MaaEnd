# MaaEnd 内嵌网页控制器

用户入口只有完整程序 `MaaEnd.exe`。在原界面右侧「连接设置 → 控制器」选择「云·终末地网页版」，填写 HTTPS 地址后连接。原任务列表、Rust Tasker 和 Agent 保持原流程。

`host_main.py` / `mxu_host.py` / `qt_host.py` 是主程序管理的私有网页组件。`CloudWebHost.exe` 仅接受主程序的私有 stdio 调用，不提供独立选择器或演示启动入口。

完整构建方法见 [集成说明](integration/README.md)。仅交付完整 MaaEnd 便携包，不单独交付网页组件。

按用户要求，最终版本完成实现和编译后由用户自行测试；不宣称官方云终末地或 macOS 已通过实机验证。既有后台检查代码保留，但不作为用户程序运行。
