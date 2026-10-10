"""Native connection selector for the independent experiment, not MXU."""

from pathlib import Path
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton, QWidget

from qt_policy import https_origin


class Launcher(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MaaEnd · 云网页控制器实验")
        self.setMinimumWidth(580)
        layout = QFormLayout(self)
        warning = QLabel("三端共用 Qt 宿主原型\n不代表云终末地或现有自动化任务已经兼容")
        warning.setWordWrap(True)
        layout.addRow(warning)
        self.connection = QComboBox()
        self.connection.addItem("离线测试页（安全默认）", "test-page")
        self.connection.addItem("自定义 HTTPS 网页（实验）", "embedded-webview")
        self.connection.addItem("Eagle 3D 公开串流示例（免账号）", "eagle-public-demo")
        layout.addRow("连接方式", self.connection)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://… 不内置猜测的云终末地入口")
        self.url.setEnabled(False)
        layout.addRow("网页地址", self.url)
        self.connection.currentIndexChanged.connect(lambda: self.url.setEnabled(self.connection.currentData() == "embedded-webview"))
        self.start = QPushButton("打开内嵌窗口")
        self.start.clicked.connect(self.launch)
        layout.addRow(self.start)
        self.status = QLabel("首次测试请选择离线页面。Windows/macOS 尚待实机验收。")
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(lambda error: self.finished(-1))

    def launch(self):
        mode = self.connection.currentData()
        args = [str(Path(__file__).with_name("qt_main.py")), "--connection", mode, "--keep-open"]
        if mode == "embedded-webview":
            try:
                https_origin(self.url.text())
            except ValueError as error:
                self.status.setText(str(error))
                return
            args += ["--url", self.url.text()]
        self.start.setEnabled(False)
        self.status.setText("正在打开独立内嵌窗口；请勿登录真实账号或付费。关闭内嵌窗口即可结束。")
        self.process.start(sys.executable, args)

    def finished(self, code, *_):
        self.start.setEnabled(True)
        self.status.setText("实验窗口已结束" if code == 0 else "启动或验证失败，请查看控制台与 cloudweb-results/report.json")

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            # Do not destroy QProcess while its browser child is running.
            self.status.setText("请先关闭内嵌实验窗口，再关闭连接选择器")
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = Launcher()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
