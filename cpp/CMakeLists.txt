# magarray: the board's host side in C++ (decision 0003). Linux.
#
# As a dependency: add_subdirectory(<magarray>/cpp) and link magarray::magarray.
# Standalone:      cmake -S cpp -B build && cmake --build build && ctest --test-dir build
cmake_minimum_required(VERSION 3.25)
project(magarray VERSION 0.2.0 LANGUAGES CXX)

option(MAGARRAY_TESTS "Build the tests (GoogleTest)" ${PROJECT_IS_TOP_LEVEL})
option(MAGARRAY_TOOLS "Build magarray_dump" ${PROJECT_IS_TOP_LEVEL})

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
find_package(Threads REQUIRED)

add_library(magarray STATIC
    src/wire.cpp
    src/recording.cpp
    src/board.cpp
    src/serial_posix.cpp)
add_library(magarray::magarray ALIAS magarray)
target_include_directories(magarray PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_link_libraries(magarray PUBLIC Threads::Threads)
target_compile_options(magarray PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall -Wextra -Wpedantic -Wconversion>)

if(MAGARRAY_TOOLS)
    add_executable(magarray_dump tools/magarray_dump.cpp)
    target_link_libraries(magarray_dump PRIVATE magarray::magarray)
endif()

if(MAGARRAY_TESTS)
    enable_testing()
    find_package(GTest REQUIRED)
    add_executable(magarray_tests tests/test_wire.cpp tests/test_recording.cpp tests/test_board.cpp)
    target_link_libraries(magarray_tests PRIVATE magarray::magarray GTest::gtest_main)
    target_compile_definitions(magarray_tests PRIVATE MAGARRAY_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/../python/tests/data")
    include(GoogleTest)
    gtest_discover_tests(magarray_tests)
endif()
