cmake_minimum_required(VERSION 3.22.1)
project(aletheia_viz_bridge C)

# The one native artefact. Unity resolves the same symbols at runtime via
# System.loadLibrary is NOT needed — under Unity as a Library the plugin's .so
# is already loaded in-process, so Unity's [DllImport("aletheia_viz_bridge")]
# binds directly.
add_library(aletheia_viz_bridge SHARED
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../shared/aletheia_viz_bridge.c
    ${CMAKE_CURRENT_SOURCE_DIR}/av_jni.c)

target_include_directories(aletheia_viz_bridge PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../shared)

find_library(log-lib log)
target_link_libraries(aletheia_viz_bridge ${log-lib})

set_target_properties(aletheia_viz_bridge PROPERTIES
    C_STANDARD 11
    C_VISIBILITY_PRESET default)
