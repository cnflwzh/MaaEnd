#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>

#define NOMINMAX
#include <windows.h>

#include "bridge_policy.h"
#include "maa_bridge.h"

namespace
{
bool wait_success(MaaController* controller, MaaCtrlId id)
{
    return id != MaaInvalidId && MaaControllerWait(controller, id) == MaaStatus_Succeeded;
}

bool verify_title(cloudweb::WebViewHost& host, const std::string& expected)
{
    // Wait for an observed DOM event, not an assumed animation delay. No input
    // is retried while Chromium completes delivery of the one posted event.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (host.connected() && std::chrono::steady_clock::now() < deadline) {
        if (host.title() == expected) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    return false;
}

bool screenshot(MaaController* controller, const std::filesystem::path& path)
{
    if (!wait_success(controller, MaaControllerPostScreencap(controller))) {
        return false;
    }
    std::unique_ptr<MaaImageBuffer, decltype(&MaaImageBufferDestroy)> image(MaaImageBufferCreate(), MaaImageBufferDestroy);
    if (!image || !MaaControllerCachedImage(controller, image.get()) || MaaImageBufferIsEmpty(image.get())
        || MaaImageBufferWidth(image.get()) != cloudweb::kViewportWidth
        || MaaImageBufferHeight(image.get()) != cloudweb::kViewportHeight || MaaImageBufferChannels(image.get()) != 3) {
        return false;
    }
    const auto data = MaaImageBufferGetEncoded(image.get());
    const auto size = MaaImageBufferGetEncodedSize(image.get());
    if (!data || !size) {
        return false;
    }
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(data), static_cast<std::streamsize>(size));
    return output.good();
}
} // namespace

int main(int argc, char** argv)
{
    // Connection selector belongs to this experimental host; MXU's existing
    // controller selector cannot instantiate a Custom controller through PI V2.
    std::string connection = "test-page";
    std::string url;
    bool keep_open = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--connection" && i + 1 < argc) {
            connection = argv[++i];
        }
        else if (arg == "--url" && i + 1 < argc) {
            url = argv[++i];
        }
        else if (arg == "--keep-open") {
            keep_open = true;
        }
        else {
            std::cerr << "Usage: maaend-cloud-web [--connection test-page|embedded-webview] [--url HTTPS_URL] [--keep-open]\n";
            return 2;
        }
    }
    const bool test_page = connection == "test-page";
    if ((!test_page && connection != "embedded-webview") || (test_page && !url.empty())
        || (!test_page && !cloudweb::HttpsOrigin(url))) {
        std::cerr << "Invalid connection. Remote mode requires an explicit HTTPS URL; only default port 443 is supported.\n";
        return 2;
    }
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    std::cout << "EXPERIMENTAL: standalone embedded WebView2. Cloud game compatibility has NOT been verified.\n";
    cloudweb::WebViewHost host(url);
    if (!host.start()) {
        std::cerr << "WebView2 startup/navigation failed. Check Runtime, allowed origin, inherited browser flags, and network.\n";
        return 1;
    }
    bool ok = true;
    {
        cloudweb::MaaBridge bridge(host);
        auto* controller = bridge.get();
        ok = controller && wait_success(controller, MaaControllerPostConnection(controller)) && MaaControllerConnected(controller);
        if (ok && test_page) {
            ok = screenshot(controller, L"cloudweb-before.png")
                && wait_success(controller, MaaControllerPostClick(controller, 320, 360))
                && verify_title(host, "MaaEnd bridge: clicked 1")
                && wait_success(controller, MaaControllerPostClickKey(controller, 'W'))
                && verify_title(host, "MaaEnd bridge: key W")
                && screenshot(controller, L"cloudweb-after.png")
                && wait_success(controller, MaaControllerPostInactive(controller));
            std::cout << (ok ? "PASS: Maa connection, 1280x720 BGR screenshot, click and keyboard delivery.\n"
                             : "FAIL: bridge smoke test; inspect Runtime/DPI/input behavior.\n");
        }
        else if (ok) {
            std::cout << "Remote page connected. No screenshots saved or automated inputs sent in remote preview mode.\n";
            keep_open = true;
        }
        // Keep the Maa/controller context alive while the embedded page is open.
        while (ok && keep_open && host.visible()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
    return ok ? 0 : 1;
}
