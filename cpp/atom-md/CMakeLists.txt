cmake_minimum_required(VERSION 3.16)
project(atom_md CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Single-config generators (Makefiles, Ninja) need a build type chosen here.
# Multi-config generators (Visual Studio, Xcode) pick it at build time instead,
# so leave them alone -- see the note below about --config Release.
get_property(is_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(NOT is_multi_config AND NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
  set_property(CACHE CMAKE_BUILD_TYPE PROPERTY STRINGS
               Debug Release RelWithDebInfo MinSizeRel)
endif()

add_executable(atom_md
  src/main.cpp
  src/simulation.cpp
)

target_include_directories(atom_md PRIVATE src)

# Optimise hard, but never enable fast-math: reassociating floating-point
# arithmetic would quietly wreck the energy-conservation check that validates
# the integrator. MSVC defaults to /fp:precise, which is what we want.
if(MSVC)
  target_compile_options(atom_md PRIVATE /W4 /permissive- /fp:precise
                         $<$<CONFIG:Release>:/O2>)
  # Silence MSVC's warnings about the portable std:: functions we use.
  target_compile_definitions(atom_md PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
  target_compile_options(atom_md PRIVATE -Wall -Wextra -Wpedantic
                         $<$<CONFIG:Release>:-O3>)
endif()
