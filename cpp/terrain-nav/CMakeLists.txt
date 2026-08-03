cmake_minimum_required(VERSION 3.16)
project(terrain_nav CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

get_property(is_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(NOT is_multi_config AND NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
  set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
               Debug Release RelWithDebInfo MinSizeRel)
endif()

add_executable(terrain_nav
  src/main.cpp
  src/dem.cpp
  src/navsim.cpp
  src/neural_map.cpp
  src/particle_filter.cpp
  src/perturbed_map.cpp
  src/render.cpp
)

target_include_directories(terrain_nav PRIVATE src)

if(MSVC)
  target_compile_options(terrain_nav PRIVATE /W4 /permissive- /fp:precise
                         $<$<CONFIG:Release>:/O2>)
  target_compile_definitions(terrain_nav PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
  target_compile_options(terrain_nav PRIVATE -Wall -Wextra -Wpedantic
                         $<$<CONFIG:Release>:-O3>)
endif()
