cmake_minimum_required(VERSION 3.16)
project(mai_ir LANGUAGES CXX)

add_library(tokenizer_core src/tokenizer/tokenizer.cpp)
target_include_directories(tokenizer_core PUBLIC src/tokenizer)
target_compile_features(tokenizer_core PUBLIC cxx_std_17)
set_target_properties(tokenizer_core PROPERTIES CXX_EXTENSIONS OFF)

add_executable(tokenizer src/tokenizer/main.cpp)
target_link_libraries(tokenizer PRIVATE tokenizer_core)

include(CTest)
if(BUILD_TESTING)
    add_executable(tokenizer_tests tests/tokenizer/test_tokenizer.cpp)
    target_link_libraries(tokenizer_tests PRIVATE tokenizer_core)
    add_test(NAME tokenizer_tests COMMAND tokenizer_tests $<TARGET_FILE:tokenizer>)
    set_tests_properties(tokenizer_tests PROPERTIES TIMEOUT 60)
endif()
