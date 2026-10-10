#include "async_result.h"

#include <atomic>
#include <cstdlib>
#include <iostream>
#include <thread>

namespace
{
void check(bool condition, const char* message)
{
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}
} // namespace

int main()
{
    using namespace std::chrono_literals;
    cloudweb::AsyncResult completed;
    check(completed.finish(true, { 1, 2, 3 }, "ok"), "first completion");
    check(completed.wait(0ms), "completed wait");
    check(!completed.finish(false), "reject second completion");
    check(completed.bytes() == std::vector<unsigned char>({ 1, 2, 3 }) && completed.text() == "ok", "owned result data");

    cloudweb::AsyncResult timed_out;
    check(!timed_out.wait(1ms), "bounded wait");
    check(timed_out.finished() && !timed_out.finish(true, { 9 }), "ignore late callback");
    check(timed_out.bytes().empty(), "no stale capture after timeout");

    cloudweb::AsyncResult cancelled;
    std::thread waiter([&] { check(!cancelled.wait(5s), "cancelled waiter"); });
    check(cancelled.finish(false), "shutdown cancellation");
    waiter.join();

    for (int i = 0; i < 100; ++i) {
        cloudweb::AsyncResult raced;
        std::atomic<int> winners = 0;
        std::thread a([&] { winners += raced.finish(true); });
        std::thread b([&] { winners += raced.finish(false); });
        a.join();
        b.join();
        check(winners == 1 && raced.finished(), "racing callbacks complete once");
    }
    std::cout << "Async completion, timeout, cancellation and 100 race checks passed\n";
}
