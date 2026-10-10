#include "webview_host.h"

#include <atomic>
#include <chrono>
#include <filesystem>
#include <functional>
#include <mutex>
#include <thread>
#include <utility>

#define NOMINMAX
#include <windows.h>
#include <objbase.h>
#include <wrl.h>
#include <WebView2.h>

#include "async_result.h"
#include "bridge_policy.h"
#include "test_page.h"

namespace cloudweb
{
namespace
{
using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;
constexpr UINT kDispatchMessage = WM_APP + 1;
constexpr auto kCallTimeout = std::chrono::seconds(10);
constexpr auto kStartupTimeout = std::chrono::seconds(30);
constexpr std::size_t kMaxCaptureBytes = 32 * 1024 * 1024;

std::wstring to_wide(const std::string& value)
{
    if (value.empty()) {
        return {};
    }
    const int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (size <= 0) {
        return {};
    }
    std::wstring result(size, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(), static_cast<int>(value.size()), result.data(), size);
    return result;
}

std::string to_utf8(LPCWSTR value)
{
    if (!value || !*value) {
        return {};
    }
    const int size = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) {
        return {};
    }
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), size, nullptr, nullptr);
    result.pop_back();
    return result;
}

struct WindowState : std::enable_shared_from_this<WindowState>
{
    std::string url;
    std::string origin;
    UINT64 navigation_id = 0; // STA thread only; ignore superseded completions.
    std::atomic<HWND> hwnd { nullptr };
    std::atomic<bool> ready { false };
    std::atomic<bool> closing { false };
    std::atomic<bool> faulted { false };
    std::shared_ptr<AsyncResult> startup = std::make_shared<AsyncResult>();
    std::mutex mutex;
    std::vector<std::function<void()>> queue;
    std::vector<std::weak_ptr<AsyncResult>> requests;
    // COM pointers are accessed/released exclusively on the STA thread.
    ComPtr<ICoreWebView2Controller> controller;
    ComPtr<ICoreWebView2> webview;

    bool allowed(LPCWSTR uri) const
    {
        const auto candidate = to_utf8(uri);
        return url.empty() ? candidate == "about:blank" : HttpsOrigin(candidate) == origin;
    }

    void stop()
    {
        closing = true;
        ready = false;
        startup->finish(false);
        {
            std::lock_guard lock(mutex);
            queue.clear();
            for (auto& weak : requests) {
                if (auto request = weak.lock()) {
                    request->finish(false);
                }
            }
            requests.clear();
        }
        if (controller) {
            controller->Close();
        }
        webview.Reset();
        controller.Reset();
    }

    bool configure(ICoreWebView2Controller* created)
    {
        controller = created;
        if (FAILED(controller->get_CoreWebView2(&webview)) || !webview) {
            return false;
        }
        ComPtr<ICoreWebView2Controller3> controller3;
        ComPtr<ICoreWebView2Settings> settings;
        ComPtr<ICoreWebView2Settings2> settings2;
        ComPtr<ICoreWebView2Settings4> settings4;
        ComPtr<ICoreWebView2_4> webview4;
        if (FAILED(controller.As(&controller3)) || FAILED(webview.As(&webview4))
            || FAILED(webview->get_Settings(&settings)) || FAILED(settings.As(&settings2)) || FAILED(settings.As(&settings4))) {
            return false;
        }
        // Screenshots and CDP input share physical 1280x720 coordinates at any
        // host monitor DPI. Resizing/zoom controls are intentionally disabled.
        if (FAILED(controller3->put_ShouldDetectMonitorScaleChanges(FALSE))
            || FAILED(controller3->put_RasterizationScale(1.0))
            || FAILED(controller3->put_BoundsMode(COREWEBVIEW2_BOUNDS_MODE_USE_RAW_PIXELS))
            || FAILED(controller->put_ZoomFactor(1.0))
            || FAILED(controller->put_Bounds(RECT { 0, 0, kViewportWidth, kViewportHeight }))
            || FAILED(settings->put_IsZoomControlEnabled(FALSE))
            || FAILED(settings->put_AreHostObjectsAllowed(FALSE))
            || FAILED(settings->put_IsWebMessageEnabled(FALSE))
            || FAILED(settings->put_AreDevToolsEnabled(FALSE))
            || FAILED(settings->put_AreDefaultContextMenusEnabled(FALSE))
            || FAILED(settings->put_AreDefaultScriptDialogsEnabled(FALSE))
            || FAILED(settings4->put_IsPasswordAutosaveEnabled(FALSE))
            || FAILED(settings4->put_IsGeneralAutofillEnabled(FALSE))) {
            return false;
        }
        auto self = shared_from_this();
        EventRegistrationToken token {};
        if (FAILED(webview->add_NavigationStarting(
                Callback<ICoreWebView2NavigationStartingEventHandler>([self](auto*, auto* args) -> HRESULT {
                    self->ready = false;
                    args->get_NavigationId(&self->navigation_id);
                    LPWSTR uri = nullptr;
                    const bool ok = SUCCEEDED(args->get_Uri(&uri)) && self->allowed(uri);
                    CoTaskMemFree(uri);
                    if (!ok) {
                        args->put_Cancel(TRUE);
                        self->faulted = true;
                        self->startup->finish(false);
                    }
                    return S_OK;
                }).Get(), &token))
            || FAILED(webview->add_FrameNavigationStarting(
                Callback<ICoreWebView2NavigationStartingEventHandler>([self](auto*, auto* args) -> HRESULT {
                    LPWSTR uri = nullptr;
                    const bool ok = SUCCEEDED(args->get_Uri(&uri)) && self->allowed(uri);
                    CoTaskMemFree(uri);
                    return ok ? S_OK : args->put_Cancel(TRUE);
                }).Get(), &token))
            || FAILED(webview->add_NavigationCompleted(
                Callback<ICoreWebView2NavigationCompletedEventHandler>([self](auto*, auto* args) -> HRESULT {
                    UINT64 navigation_id = 0;
                    if (FAILED(args->get_NavigationId(&navigation_id)) || navigation_id != self->navigation_id) {
                        return S_OK;
                    }
                    BOOL success = FALSE;
                    args->get_IsSuccess(&success);
                    self->ready = success && !self->closing && !self->faulted;
                    self->startup->finish(self->ready);
                    return S_OK;
                }).Get(), &token))
            || FAILED(webview->add_NewWindowRequested(
                Callback<ICoreWebView2NewWindowRequestedEventHandler>([](auto*, auto* args) -> HRESULT {
                    return args->put_Handled(TRUE);
                }).Get(), &token))
            || FAILED(webview->add_PermissionRequested(
                Callback<ICoreWebView2PermissionRequestedEventHandler>([](auto*, auto* args) -> HRESULT {
                    return args->put_State(COREWEBVIEW2_PERMISSION_STATE_DENY);
                }).Get(), &token))
            || FAILED(webview4->add_DownloadStarting(
                Callback<ICoreWebView2DownloadStartingEventHandler>([](auto*, auto* args) -> HRESULT {
                    return args->put_Cancel(TRUE);
                }).Get(), &token))
            || FAILED(webview->add_ProcessFailed(
                Callback<ICoreWebView2ProcessFailedEventHandler>([self](auto*, auto*) -> HRESULT {
                    self->faulted = true;
                    self->ready = false;
                    self->startup->finish(false);
                    return S_OK;
                }).Get(), &token))) {
            return false;
        }
        return SUCCEEDED(url.empty() ? webview->NavigateToString(kTestPage) : webview->Navigate(to_wide(url).c_str()));
    }
};

LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    auto* state = reinterpret_cast<WindowState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        state = static_cast<WindowState*>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));
    }
    if (state && message == kDispatchMessage) {
        std::vector<std::function<void()>> queue;
        {
            std::lock_guard lock(state->mutex);
            queue.swap(state->queue);
        }
        for (auto& call : queue) {
            call();
        }
        return 0;
    }
    if (state && message == WM_CLOSE) {
        state->stop();
        DestroyWindow(hwnd);
        return 0;
    }
    if (state && message == WM_DESTROY) {
        state->hwnd = nullptr;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

void ui_main(const std::shared_ptr<WindowState>& state)
{
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) {
        state->startup->finish(false);
        return;
    }
    // Fail closed instead of inheriting flags that might expose a debug port.
    wchar_t inherited[2] {};
    wchar_t temp[MAX_PATH] {};
    wchar_t profile[MAX_PATH] {};
    if (GetEnvironmentVariableW(L"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", inherited, 2) != 0
        || !GetTempPathW(MAX_PATH, temp) || !GetTempFileNameW(temp, L"MCW", 0, profile)
        || !DeleteFileW(profile) || !CreateDirectoryW(profile, nullptr)
        || !SetEnvironmentVariableW(L"WEBVIEW2_USER_DATA_FOLDER", profile)) {
        state->startup->finish(false);
        CoUninitialize();
        return;
    }
    const auto instance = GetModuleHandleW(nullptr);
    WNDCLASSW wc {};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.lpszClassName = L"MaaEndCloudWebExperiment";
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    RegisterClassW(&wc);
    constexpr DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU;
    RECT rect { 0, 0, kViewportWidth, kViewportHeight };
    AdjustWindowRect(&rect, style, FALSE);
    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, L"MaaEnd - Embedded WebView2 (EXPERIMENTAL)", style,
        CW_USEDEFAULT, CW_USEDEFAULT, rect.right - rect.left, rect.bottom - rect.top,
        nullptr, nullptr, instance, state.get());
    state->hwnd = hwnd;
    if (!hwnd) {
        state->startup->finish(false);
        CoUninitialize();
        return;
    }
    if (state->closing) {
        state->stop();
        DestroyWindow(hwnd);
        CoUninitialize();
        return;
    }
    ShowWindow(hwnd, SW_SHOW);
    const HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(nullptr, profile, nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [state](HRESULT result, ICoreWebView2Environment* environment) -> HRESULT {
                if (FAILED(result) || !environment || state->closing) {
                    state->startup->finish(false);
                    return S_OK;
                }
                const HRESULT created = environment->CreateCoreWebView2Controller(state->hwnd,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [state](HRESULT result, ICoreWebView2Controller* controller) -> HRESULT {
                            if (state->closing) {
                                if (controller) {
                                    controller->Close();
                                }
                                return S_OK;
                            }
                            if (FAILED(result) || !controller || !state->configure(controller)) {
                                state->startup->finish(false);
                            }
                            return S_OK;
                        }).Get());
                if (FAILED(created)) {
                    state->startup->finish(false);
                }
                return S_OK;
            }).Get());
    if (FAILED(hr)) {
        state->startup->finish(false);
    }
    MSG message {};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    state->stop();
    CoUninitialize();
    // Only this fresh, generated temporary profile is eligible for cleanup.
    // Browser shutdown may retain a file briefly; never delete another profile.
    std::error_code error;
    std::filesystem::remove_all(std::filesystem::path(profile), error);
}
} // namespace

struct WebViewHost::Impl
{
    std::shared_ptr<WindowState> state = std::make_shared<WindowState>();
    std::thread ui;
    bool started = false;

    std::shared_ptr<AsyncResult> invoke(std::function<void(WindowState&, const std::shared_ptr<AsyncResult>&)> action)
    {
        auto result = std::make_shared<AsyncResult>();
        auto current = state;
        {
            std::lock_guard lock(current->mutex);
            if (!current->ready || current->closing || current->faulted || !current->hwnd) {
                result->finish(false);
                return result;
            }
            // Drop expired completion records, keeping memory bounded.
            std::erase_if(current->requests, [](const auto& weak) { return weak.expired(); });
            current->requests.push_back(result);
            current->queue.push_back([current, result, action = std::move(action)] {
                if (result->finished()) {
                    return;
                }
                if (!current->ready || current->closing || current->faulted || !current->webview) {
                    result->finish(false);
                    return;
                }
                action(*current, result);
            });
            if (!PostMessageW(current->hwnd, kDispatchMessage, 0, 0)) {
                result->finish(false);
            }
        }
        if (!result->wait(kCallTimeout)) {
            // No automatic retry: a failed/timed-out input may have taken effect.
            current->faulted = true;
        }
        return result;
    }

    bool cdp(const wchar_t* method, const std::string& params)
    {
        const auto wide = to_wide(params);
        if (wide.empty()) {
            return false;
        }
        auto result = invoke([method, wide](auto& state, const auto& result) {
            const HRESULT hr = state.webview->CallDevToolsProtocolMethod(method, wide.c_str(),
                Callback<ICoreWebView2CallDevToolsProtocolMethodCompletedHandler>(
                    [result](HRESULT error, LPCWSTR) -> HRESULT {
                        result->finish(SUCCEEDED(error));
                        return S_OK;
                    }).Get());
            if (FAILED(hr)) {
                result->finish(false);
            }
        });
        return result->wait(std::chrono::milliseconds(0));
    }
};

WebViewHost::WebViewHost(std::string url) : impl_(std::make_unique<Impl>())
{
    impl_->state->url = std::move(url);
    impl_->state->origin = HttpsOrigin(impl_->state->url).value_or("");
}

WebViewHost::~WebViewHost()
{
    impl_->state->closing = true;
    if (const auto hwnd = impl_->state->hwnd.load()) {
        PostMessageW(hwnd, WM_CLOSE, 0, 0);
    }
    if (impl_->ui.joinable()) {
        impl_->ui.join();
    }
}

bool WebViewHost::start()
{
    if (impl_->started || (!impl_->state->url.empty() && impl_->state->origin.empty())) {
        return false;
    }
    impl_->started = true;
    impl_->ui = std::thread(ui_main, impl_->state);
    return impl_->state->startup->wait(kStartupTimeout) && connected();
}

bool WebViewHost::connected() const
{
    return impl_->state->ready && !impl_->state->closing && !impl_->state->faulted;
}

bool WebViewHost::visible() const
{
    return impl_->state->hwnd != nullptr && !impl_->state->closing;
}

std::vector<unsigned char> WebViewHost::capture()
{
    auto result = impl_->invoke([](auto& state, const auto& result) {
        ComPtr<IStream> stream;
        if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, &stream))) {
            result->finish(false);
            return;
        }
        const HRESULT hr = state.webview->CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG, stream.Get(),
            Callback<ICoreWebView2CapturePreviewCompletedHandler>([result, stream](HRESULT error) -> HRESULT {
                STATSTG stat {};
                LARGE_INTEGER start {};
                if (FAILED(error) || FAILED(stream->Stat(&stat, STATFLAG_NONAME)) || stat.cbSize.QuadPart == 0
                    || stat.cbSize.QuadPart > kMaxCaptureBytes || FAILED(stream->Seek(start, STREAM_SEEK_SET, nullptr))) {
                    result->finish(false);
                    return S_OK;
                }
                std::vector<unsigned char> bytes(static_cast<std::size_t>(stat.cbSize.QuadPart));
                ULONG read = 0;
                const bool ok = SUCCEEDED(stream->Read(bytes.data(), static_cast<ULONG>(bytes.size()), &read)) && read == bytes.size();
                result->finish(ok, ok ? std::move(bytes) : std::vector<unsigned char>());
                return S_OK;
            }).Get());
        if (FAILED(hr)) {
            result->finish(false);
        }
    });
    return result->bytes();
}

bool WebViewHost::mouse(int x, int y, bool down)
{
    auto params = MouseParameters(x, y, down);
    return params && impl_->cdp(L"Input.dispatchMouseEvent", *params);
}

bool WebViewHost::key(int code, bool down)
{
    auto params = KeyParameters(code, down);
    return params && impl_->cdp(L"Input.dispatchKeyEvent", *params);
}

bool WebViewHost::text(const std::string& text)
{
    return text.size() <= 4096 && impl_->cdp(L"Input.insertText", "{\"text\":" + JsonString(text) + "}");
}

std::string WebViewHost::title()
{
    auto result = impl_->invoke([](auto& state, const auto& result) {
        LPWSTR title = nullptr;
        const HRESULT hr = state.webview->get_DocumentTitle(&title);
        const auto text = to_utf8(title);
        CoTaskMemFree(title);
        result->finish(SUCCEEDED(hr), {}, text);
    });
    return result->text();
}

} // namespace cloudweb
