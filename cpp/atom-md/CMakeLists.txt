cmake_minimum_required(VERSION 3.16)
project(atom_md CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

add_executable(atom_md
  src/main.cpp
  src/simulation.cpp
)

target_include_directories(atom_md PRIVATE src)

# -O3 yes, -ffast-math no: reassociation would quietly wreck the energy
# conservation check that validates the integrator.
target_compile_options(atom_md PRIVATE -O3 -Wall -Wextra -Wpedantic)
