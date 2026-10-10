#pragma once

namespace cloudweb
{
// Bundled, offline test surface. No remote resources and no host bindings.
inline constexpr wchar_t kTestPage[] = LR"html(<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'">
<title>MaaEnd bridge: ready</title>
<style>
*{box-sizing:border-box}body{margin:0;width:1280px;height:720px;overflow:hidden;background:#111827;color:#e5e7eb;font:24px sans-serif}
header{padding:40px}h1{color:#67e8f9;font-size:36px}p{max-width:1100px}
button{position:absolute;left:200px;top:280px;width:240px;height:160px;border:2px solid #67e8f9;border-radius:14px;background:#164e63;color:white;font:28px sans-serif}
#status{position:absolute;left:520px;top:320px;color:#a7f3d0}
footer{position:absolute;bottom:40px;left:40px;font-size:18px;color:#9ca3af}
</style></head><body>
<header><h1>MaaEnd · 嵌入网页控制器实验</h1><p>这是离线测试页，不是云终末地。固定画面 1280 × 720；用于验证截图、点击和键盘桥接。</p></header>
<button id="target">点击测试</button><div id="status">等待桥接输入…</div>
<footer>没有网页主机 API、外部浏览器、远程调试端口或游戏自动化任务</footer>
<script>
let clicks=0;
document.getElementById('target').onclick=()=>{clicks++;document.title='MaaEnd bridge: clicked '+clicks;document.getElementById('status').textContent='点击成功 '+clicks};
document.onkeydown=e=>{if(e.code==='KeyW'){document.title='MaaEnd bridge: key W';document.getElementById('status').textContent='键盘 W 成功'}};
</script></body></html>)html";
} // namespace cloudweb
