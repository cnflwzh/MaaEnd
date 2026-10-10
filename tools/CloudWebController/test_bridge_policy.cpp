#include "bridge_policy.h"

#include <cstdlib>
#include <iostream>

namespace
{
int checks = 0;
void check(bool condition, const char* name)
{
    ++checks;
    if (!condition) {
        std::cerr << "FAIL: " << name << '\n';
        std::exit(1);
    }
}
} // namespace

int main()
{
    using namespace cloudweb;
    check(HttpsOrigin("https://Example.COM:443/game?a=b#c") == "https://example.com", "canonical origin");
    check(HttpsOrigin("https://a-b.example/game") == "https://a-b.example", "DNS label");
    for (const char* url : { "", "http://example.com", "file:///tmp/a", "javascript:alert(1)",
                            "https://user:pass@example.com", "https://example.com:80", "https://example.com:444",
                            "https://example.com@evil.test", "https://example.com\\@evil.test", "https://example.com\n.evil",
                            "https://%65xample.com", "https://[::1]", "https://example.com.", "https://a..b",
                            "https://-a.com", "https://a-.com", "https://.com", "https://", "https://a b.com" }) {
        check(!HttpsOrigin(url), url);
    }
    check(HttpsOrigin("https://example.com/path") != HttpsOrigin("https://example.com.evil/path"), "origin suffix attack");
    check(HttpsOrigin("https://example.com/path") == HttpsOrigin("https://example.com/other"), "same origin path");
    check(!HttpsOrigin("https://" + std::string(64, 'a') + ".com"), "oversized DNS label");
    check(IsInsideViewport(0, 0) && IsInsideViewport(1279, 719), "viewport edges");
    for (const auto& [x, y] : { std::pair { -1, 0 }, { 0, -1 }, { 1280, 0 }, { 0, 720 } }) {
        check(!MouseParameters(x, y, true), "reject out of bounds");
    }
    check(MouseParameters(100, 200, true)->find("\"buttons\":1") != std::string::npos, "mouse down");
    check(MouseParameters(100, 200, false)->find("\"buttons\":0") != std::string::npos, "mouse up");
    check(JsonString("a\"\\\n\t") == "\"a\\\"\\\\\\u000a\\u0009\"", "JSON escaping");
    check(JsonString("中文") == "\"中文\"", "UTF-8 text preserved");
    check(KeyParameters('W', true).has_value() && KeyParameters(0x25, false).has_value(), "supported keys");
    check(!KeyParameters(0x5B, true) && !KeyParameters(-1, true) && !KeyParameters(0x70, true), "unsupported keys");
    std::cout << checks << " bridge policy checks passed\n";
}
