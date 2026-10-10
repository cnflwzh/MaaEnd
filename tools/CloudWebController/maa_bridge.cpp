#include "maa_bridge.h"

#include "bridge_policy.h"

namespace cloudweb
{

MaaBridge::MaaBridge(WebViewHost& host) : host_(host)
{
    callbacks_.connect = [](void* arg) -> MaaBool { return static_cast<MaaBridge*>(arg)->host_.connected(); };
    callbacks_.connected = callbacks_.connect;
    callbacks_.request_uuid = [](void*, MaaStringBuffer* output) -> MaaBool {
        return MaaStringBufferSet(output, "MaaEnd.CloudWebView2.Experimental");
    };
    callbacks_.get_features = [](void*) -> MaaControllerFeature { return MaaControllerFeature_None; };
    callbacks_.start_app = [](const char*, void*) -> MaaBool { return false; };
    callbacks_.stop_app = callbacks_.start_app;
    callbacks_.screencap = [](void* arg, MaaImageBuffer* output) -> MaaBool {
        if (!output || !MaaImageBufferClear(output)) {
            return false;
        }
        auto png = static_cast<MaaBridge*>(arg)->host_.capture();
        return !png.empty() && MaaImageBufferSetEncoded(output, png.data(), png.size())
            && !MaaImageBufferIsEmpty(output) && MaaImageBufferChannels(output) == 3
            && MaaImageBufferWidth(output) == kViewportWidth && MaaImageBufferHeight(output) == kViewportHeight;
    };
    callbacks_.click = [](int32_t x, int32_t y, void* arg) -> MaaBool {
        auto& host = static_cast<MaaBridge*>(arg)->host_;
        return host.mouse(x, y, true) && host.mouse(x, y, false);
    };
    callbacks_.swipe = [](int32_t, int32_t, int32_t, int32_t, int32_t, void*) -> MaaBool { return false; };
    callbacks_.touch_down = [](int32_t, int32_t, int32_t, int32_t, void*) -> MaaBool { return false; };
    callbacks_.touch_move = callbacks_.touch_down;
    callbacks_.touch_up = [](int32_t, void*) -> MaaBool { return false; };
    callbacks_.click_key = [](int32_t code, void* arg) -> MaaBool {
        auto* bridge = static_cast<MaaBridge*>(arg);
        return bridge->key(code, true) && bridge->key(code, false);
    };
    callbacks_.input_text = [](const char* text, void* arg) -> MaaBool {
        return text && static_cast<MaaBridge*>(arg)->host_.text(text);
    };
    callbacks_.key_down = [](int32_t code, void* arg) -> MaaBool { return static_cast<MaaBridge*>(arg)->key(code, true); };
    callbacks_.key_up = [](int32_t code, void* arg) -> MaaBool { return static_cast<MaaBridge*>(arg)->key(code, false); };
    callbacks_.scroll = [](int32_t, int32_t, void*) -> MaaBool { return false; };
    callbacks_.relative_move = callbacks_.scroll;
    callbacks_.shell = [](const char*, int64_t, void*, MaaStringBuffer*) -> MaaBool { return false; };
    callbacks_.inactive = [](void* arg) -> MaaBool { return static_cast<MaaBridge*>(arg)->inactive(); };
    callbacks_.get_info = [](void*, MaaStringBuffer* output) -> MaaBool {
        return MaaStringBufferSet(output, "{\"type\":\"Custom\",\"backend\":\"CloudWebView2\",\"experimental\":true}");
    };
    controller_ = MaaCustomControllerCreate(&callbacks_, this);
}

MaaBridge::~MaaBridge()
{
    if (controller_) {
        // The caller has finished posting jobs. Destroy joins Maa's worker.
        MaaControllerDestroy(controller_);
    }
    inactive();
}

bool MaaBridge::key(int code, bool down)
{
    if (!IsSupportedKey(code) || !host_.key(code, down)) {
        return false;
    }
    if (down) {
        held_keys_.insert(code);
    }
    else {
        held_keys_.erase(code);
    }
    return true;
}

bool MaaBridge::inactive()
{
    bool ok = true;
    for (int code : held_keys_) {
        ok = host_.key(code, false) && ok;
    }
    held_keys_.clear();
    return ok;
}

} // namespace cloudweb
