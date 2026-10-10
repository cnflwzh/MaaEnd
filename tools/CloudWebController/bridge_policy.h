#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace cloudweb
{

constexpr int kViewportWidth = 1280;
constexpr int kViewportHeight = 720;

// Intentionally narrower than a browser URL parser: ASCII DNS names and HTTPS
// only. Reject ambiguous URLs rather than allowing an origin-policy bypass.
inline std::optional<std::string> HttpsOrigin(std::string_view url)
{
    constexpr std::string_view prefix = "https://";
    if (!url.starts_with(prefix)) {
        return std::nullopt;
    }
    for (unsigned char ch : url) {
        if (ch <= 32 || ch >= 127 || ch == '\\') {
            return std::nullopt;
        }
    }
    const auto authority_end = url.find_first_of("/?#", prefix.size());
    std::string host(url.substr(prefix.size(), authority_end == std::string_view::npos
                                                   ? url.size() - prefix.size()
                                                   : authority_end - prefix.size()));
    if (host.ends_with(":443")) {
        host.resize(host.size() - 4);
    }
    if (host.empty() || host.size() > 253 || host.front() == '.' || host.back() == '.') {
        return std::nullopt;
    }
    std::size_t label_start = 0;
    for (std::size_t i = 0; i <= host.size(); ++i) {
        if (i == host.size() || host[i] == '.') {
            const auto length = i - label_start;
            if (length == 0 || length > 63 || host[label_start] == '-' || host[i - 1] == '-') {
                return std::nullopt;
            }
            label_start = i + 1;
        }
        else {
            char& ch = host[i];
            if (ch >= 'A' && ch <= 'Z') {
                ch += 'a' - 'A';
            }
            if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-')) {
                return std::nullopt;
            }
        }
    }
    return "https://" + host;
}

inline bool IsInsideViewport(int x, int y)
{
    return x >= 0 && y >= 0 && x < kViewportWidth && y < kViewportHeight;
}

inline std::string JsonString(std::string_view input)
{
    constexpr char hex[] = "0123456789abcdef";
    std::string result = "\"";
    for (unsigned char ch : input) {
        if (ch == '"' || ch == '\\') {
            result += '\\';
            result += static_cast<char>(ch);
        }
        else if (ch < 32) {
            result += "\\u00";
            result += hex[ch >> 4];
            result += hex[ch & 15];
        }
        else {
            result += static_cast<char>(ch);
        }
    }
    result += '"';
    return result;
}

// Input coordinates are the same 1280x720 coordinate space as captured PNGs.
inline std::optional<std::string> MouseParameters(int x, int y, bool down)
{
    if (!IsInsideViewport(x, y)) {
        return std::nullopt;
    }
    return "{\"type\":\"" + std::string(down ? "mousePressed" : "mouseReleased")
        + "\",\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y)
        + ",\"button\":\"left\",\"buttons\":" + (down ? "1" : "0") + ",\"clickCount\":1}";
}

// The prototype deliberately accepts only basic game/navigation virtual keys.
// No platform shortcuts, arbitrary CDP methods, or OS-wide input are exposed.
inline bool IsSupportedKey(int key)
{
    return (key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9')
        || (key >= 0x25 && key <= 0x28) || key == 0x20 || key == 0x0D || key == 0x1B;
}

inline std::optional<std::string> KeyParameters(int key, bool down)
{
    if (!IsSupportedKey(key)) {
        return std::nullopt;
    }
    std::string code;
    std::string value;
    if (key >= 'A' && key <= 'Z') {
        code = "Key" + std::string(1, static_cast<char>(key));
        value = std::string(1, static_cast<char>(key + ('a' - 'A')));
    }
    else if (key >= '0' && key <= '9') {
        code = "Digit" + std::string(1, static_cast<char>(key));
        value = std::string(1, static_cast<char>(key));
    }
    else {
        switch (key) {
        case 0x25: code = value = "ArrowLeft"; break;
        case 0x26: code = value = "ArrowUp"; break;
        case 0x27: code = value = "ArrowRight"; break;
        case 0x28: code = value = "ArrowDown"; break;
        case 0x20: code = "Space"; value = " "; break;
        case 0x0D: code = value = "Enter"; break;
        case 0x1B: code = value = "Escape"; break;
        }
    }
    return "{\"type\":\"" + std::string(down ? "rawKeyDown" : "keyUp")
        + "\",\"windowsVirtualKeyCode\":" + std::to_string(key)
        + ",\"code\":" + JsonString(code) + ",\"key\":" + JsonString(value) + "}";
}

} // namespace cloudweb
