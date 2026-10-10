cmake_minimum_required(VERSION 3.24)
project(maaend-cloud-web-experiment LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Deliberately independent of MaaEnd's release/package builds and MXU.
option(MAAEND_BUILD_CLOUD_WEB_HOST "Build experimental Windows WebView2 host" OFF)
include(CTest)
if(BUILD_TESTING)
    find_package(Threads REQUIRED)
    add_executable(cloudweb-policy-test test_bridge_policy.cpp)
    add_executable(cloudweb-async-test test_async_result.cpp)
    target_link_libraries(cloudweb-async-test PRIVATE Threads::Threads)
    add_test(NAME cloudweb-policy COMMAND cloudweb-policy-test)
    add_test(NAME cloudweb-async COMMAND cloudweb-async-test)
endif()

if(MAAEND_BUILD_CLOUD_WEB_HOST)
    if(NOT WIN32)
        message(FATAL_ERROR "The experimental host requires Windows. Portable tests can run without this option.")
    endif()
    set(MAAFW_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../deps" CACHE PATH "MaaFramework 5.14.2 SDK root")
    find_package(MaaFramework CONFIG REQUIRED
        PATHS "${MAAFW_SDK_DIR}/share/cmake/MaaFramework" NO_DEFAULT_PATH)
    # Reuse the repo's existing, architecture-aware WebView2 SDK discovery.
    include("${CMAKE_CURRENT_SOURCE_DIR}/../../agent/cpp-algo/cmake/WebView2.cmake")
    add_executable(maaend-cloud-web main.cpp maa_bridge.cpp webview_host.cpp)
    target_link_libraries(maaend-cloud-web PRIVATE MaaFramework::MaaFramework WebView2::WebView2 ole32 user32)
    target_compile_definitions(maaend-cloud-web PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN)
    if(MSVC)
        target_compile_options(maaend-cloud-web PRIVATE /W4 /utf-8 /permissive-)
    endif()
    # MaaCustomControlUnit is loaded at runtime; copying just MaaFramework.dll
    # is insufficient. Use the complete matching SDK bin directory.
    add_custom_command(TARGET maaend-cloud-web POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            "${MAAFW_SDK_DIR}/bin" "$<TARGET_FILE_DIR:maaend-cloud-web>"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:WebView2::WebView2>" "$<TARGET_FILE_DIR:maaend-cloud-web>"
        VERBATIM)
endif()
