#pragma once

#include <chrono>
#include <condition_variable>
#include <mutex>
#include <string>
#include <vector>

namespace cloudweb
{

// Heap-owned completion state: late COM callbacks cannot access expired stack
// variables, complete twice, or turn a timed-out operation into a later success.
struct AsyncResult
{
    bool finish(bool success, std::vector<unsigned char> bytes = {}, std::string text = {})
    {
        std::lock_guard lock(mutex_);
        if (finished_) {
            return false;
        }
        success_ = success;
        bytes_ = std::move(bytes);
        text_ = std::move(text);
        finished_ = true;
        cv_.notify_all();
        return true;
    }

    bool wait(std::chrono::milliseconds timeout)
    {
        std::unique_lock lock(mutex_);
        if (!cv_.wait_for(lock, timeout, [this] { return finished_; })) {
            finished_ = true;
            success_ = false;
        }
        return success_;
    }

    bool finished()
    {
        std::lock_guard lock(mutex_);
        return finished_;
    }

    std::vector<unsigned char> bytes()
    {
        std::lock_guard lock(mutex_);
        return bytes_;
    }

    std::string text()
    {
        std::lock_guard lock(mutex_);
        return text_;
    }

private:
    std::mutex mutex_;
    std::condition_variable cv_;
    bool finished_ = false;
    bool success_ = false;
    std::vector<unsigned char> bytes_;
    std::string text_;
};

} // namespace cloudweb
