#pragma once

#include <memory>
#include <string>
#include <vector>

namespace cloudweb
{

// Owns an isolated WebView2 window on a dedicated STA thread. Call from the Maa
// worker/main thread only. The host never exposes JS bindings or a network API.
class WebViewHost
{
public:
    explicit WebViewHost(std::string url = {});
    ~WebViewHost();
    WebViewHost(const WebViewHost&) = delete;
    WebViewHost& operator=(const WebViewHost&) = delete;

    bool start();
    bool connected() const;
    bool visible() const;
    std::vector<unsigned char> capture();
    bool mouse(int x, int y, bool down);
    bool key(int code, bool down);
    bool text(const std::string& text);
    std::string title();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace cloudweb
