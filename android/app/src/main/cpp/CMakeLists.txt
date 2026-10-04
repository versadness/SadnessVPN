cmake_minimum_required(VERSION 3.22.1)
project(svpnlauncher C)

add_library(svpnlauncher SHARED launcher.c)
target_compile_options(svpnlauncher PRIVATE -Wall -Wextra -O2)
