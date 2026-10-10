#pragma once

#include <set>

#include <MaaFramework/MaaAPI.h>

#include "webview_host.h"

namespace cloudweb
{

// The callback table and host outlive MaaControllerDestroy (Maa retains both
// pointers). The browser's STA thread remains alive throughout destruction.
class MaaBridge
{
public:
    explicit MaaBridge(WebViewHost& host);
    ~MaaBridge();
    MaaBridge(const MaaBridge&) = delete;
    MaaBridge& operator=(const MaaBridge&) = delete;
    MaaController* get() const { return controller_; }

private:
    bool key(int code, bool down);
    bool inactive();

    WebViewHost& host_;
    MaaCustomControllerCallbacks callbacks_ {};
    MaaController* controller_ = nullptr;
    // Used only on the serialized Maa callback worker, then after it is joined.
    std::set<int> held_keys_;
};

} // namespace cloudweb
