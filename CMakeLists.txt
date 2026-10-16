cmake_minimum_required(VERSION 3.20)
project(PartnerModelsOFX LANGUAGES CXX)

# Build facts from LTX Alpha Gen OFX: C++14 (OFX 1.4 Support uses throw() specs and auto_ptr);
# build on Rocky 9 with its GCC 11 (newer glibc/libstdc++ won't load in Flame); libstdc++ dynamic;
# export only the two OFX entry points.
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# Release version (also the OFX plugin version major.minor and the package name).
# 0.1.0 = first release (2026-10-16): Krea 3 + Nano Banana Pro, Linux (Rocky 9) + macOS (arm64).
set(CPO_VERSION "0.1.0")
string(REPLACE "." ";" CPO_VERSION_PARTS "${CPO_VERSION}")
list(GET CPO_VERSION_PARTS 0 CPO_VERSION_MAJOR)
list(GET CPO_VERSION_PARTS 1 CPO_VERSION_MINOR)
if(NOT CPO_GIT)
  execute_process(COMMAND git -C ${CMAKE_SOURCE_DIR} rev-parse --short HEAD
    OUTPUT_VARIABLE CPO_GIT OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
endif()
if(NOT CPO_GIT)
  set(CPO_GIT "nogit")
endif()
set(OFX_DIR ${CMAKE_SOURCE_DIR}/third_party/openfx)
set(BUNDLE_NAME PartnerModels)
set(BUNDLE_DIR ${CMAKE_BINARY_DIR}/${BUNDLE_NAME}.ofx.bundle)

add_library(ofx_support STATIC
  ${OFX_DIR}/Support/Library/ofxsCore.cpp
  ${OFX_DIR}/Support/Library/ofxsImageEffect.cpp
  ${OFX_DIR}/Support/Library/ofxsInteract.cpp
  ${OFX_DIR}/Support/Library/ofxsLog.cpp
  ${OFX_DIR}/Support/Library/ofxsMultiThread.cpp
  ${OFX_DIR}/Support/Library/ofxsParams.cpp
  ${OFX_DIR}/Support/Library/ofxsProperty.cpp
  ${OFX_DIR}/Support/Library/ofxsPropertyValidation.cpp)
target_include_directories(ofx_support PUBLIC ${OFX_DIR}/include ${OFX_DIR}/Support/include)
target_compile_options(ofx_support PRIVATE -w -fvisibility=hidden)

# OS-specific sources behind ofx/src/core/platform.h (LTX decision 64) and the bundle's binary
# folder (OFX: Linux-x86-64; MacOS, as the installed Mac plugins use).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  set(CPO_PLATFORM_SOURCE ofx/src/core/platform_linux.cpp)
  set(CPO_ARCH_DIR Linux-x86-64)
elseif(APPLE)
  set(CPO_PLATFORM_SOURCE ofx/src/core/platform_macos.cpp)
  set(CPO_ARCH_DIR MacOS)
else()
  message(FATAL_ERROR "No platform layer for ${CMAKE_SYSTEM_NAME} (ofx/src/core/platform.h)")
endif()

# Generic core, shared with the unit tests.
add_library(cpo_core STATIC ofx/src/core/cache.cpp ofx/src/core/log.cpp ofx/src/core/user_config.cpp
  ofx/src/core/process.cpp ofx/src/core/marker.cpp ${CPO_PLATFORM_SOURCE})
target_include_directories(cpo_core PUBLIC ofx/src/core)
target_compile_options(cpo_core PRIVATE -Wall -Wextra -fvisibility=hidden)
target_compile_features(cpo_core PUBLIC cxx_std_14)

# The model tables (decision 2): one file per model + the registry.
add_library(cpo_models STATIC ofx/src/models/registry.cpp ofx/src/models/krea3.cpp ofx/src/models/nano_banana_pro.cpp)
target_include_directories(cpo_models PUBLIC ofx/src/core)
target_compile_options(cpo_models PRIVATE -Wall -Wextra -fvisibility=hidden)

add_library(${BUNDLE_NAME} MODULE ofx/src/plugin.cpp ofx/src/core/partner_effect.cpp)
target_link_libraries(${BUNDLE_NAME} PRIVATE ofx_support cpo_core cpo_models pthread)
target_compile_definitions(${BUNDLE_NAME} PRIVATE CPO_VERSION="${CPO_VERSION}" CPO_GIT="${CPO_GIT}"
  CPO_VERSION_MAJOR=${CPO_VERSION_MAJOR} CPO_VERSION_MINOR=${CPO_VERSION_MINOR})
target_compile_options(${BUNDLE_NAME} PRIVATE -Wall -Wextra -Wno-deprecated-declarations -Wno-deprecated
  -fvisibility=hidden)
# Export only the two OFX entry points (as LTX: Linux version script; macOS the vendored osxSymbols
# list, and ld's default for undefined symbols is already "error"), plus a minimal Info.plist.
if(APPLE)
  target_link_options(${BUNDLE_NAME} PRIVATE -Wl,-exported_symbols_list,${OFX_DIR}/Support/include/osxSymbols)
  file(WRITE ${BUNDLE_DIR}/Contents/Info.plist
"<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>CFBundleExecutable</key><string>${BUNDLE_NAME}.ofx</string>
  <key>CFBundleIdentifier</key><string>com.janklier.partnermodels</string>
  <key>CFBundleName</key><string>Partner Models</string>
  <key>CFBundlePackageType</key><string>BNDL</string>
  <key>CFBundleVersion</key><string>${CPO_VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${CPO_VERSION}</string>
</dict>
</plist>
")
else()
  target_link_options(${BUNDLE_NAME} PRIVATE
    -Wl,--version-script=${OFX_DIR}/Support/include/linuxSymbols -Wl,--no-undefined)
endif()
set_target_properties(${BUNDLE_NAME} PROPERTIES PREFIX "" SUFFIX ".ofx"
  LIBRARY_OUTPUT_DIRECTORY ${BUNDLE_DIR}/Contents/${CPO_ARCH_DIR})

# Python job, helper and Flame hook go into the bundle's Resources (refreshed on every build).
add_custom_target(bundle_resources ALL
  COMMAND ${CMAKE_COMMAND} -E rm -rf ${BUNDLE_DIR}/Contents/Resources
  COMMAND ${CMAKE_COMMAND} -E make_directory ${BUNDLE_DIR}/Contents/Resources/worker
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/worker/cpo ${BUNDLE_DIR}/Contents/Resources/worker/cpo
  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/worker/job.py ${CMAKE_SOURCE_DIR}/worker/edit_text.py
          ${BUNDLE_DIR}/Contents/Resources/worker/
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/helper ${BUNDLE_DIR}/Contents/Resources/helper
  COMMAND ${CMAKE_COMMAND} -E copy_directory ${CMAKE_SOURCE_DIR}/flame_hook ${BUNDLE_DIR}/Contents/Resources/flame_hook
  # MPL 2.0 text and the notices (OpenFX BSD: binary redistributions must carry its notice).
  COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_SOURCE_DIR}/LICENSE ${CMAKE_SOURCE_DIR}/NOTICE ${BUNDLE_DIR}/Contents/Resources/
  DEPENDS ${BUNDLE_NAME})

enable_testing()
# Python for the worker tests (numpy + Pillow importable under -I; OpenColorIO optional).
set(WORKER_TEST_PYTHON /usr/bin/python3 CACHE FILEPATH "Python for worker tests")
add_executable(test_cache ofx/tests/test_cache.cpp)
target_link_libraries(test_cache PRIVATE cpo_core)
add_test(NAME cache COMMAND test_cache)
add_executable(test_model_spec ofx/tests/test_model_spec.cpp)
target_link_libraries(test_model_spec PRIVATE cpo_models)
add_test(NAME model_spec COMMAND test_model_spec ${CMAKE_SOURCE_DIR})
# The Python suite gets the C++ model tables as JSON for its contract test.
add_executable(dump_model_specs ofx/tests/dump_model_specs.cpp)
target_link_libraries(dump_model_specs PRIVATE cpo_models)
add_test(NAME worker_python COMMAND sh -c
  "$<TARGET_FILE:dump_model_specs> > ${CMAKE_BINARY_DIR}/model_specs.json && CPO_MODEL_SPECS=${CMAKE_BINARY_DIR}/model_specs.json ${WORKER_TEST_PYTHON} -B -m unittest discover -s ${CMAKE_SOURCE_DIR}/worker/tests -t ${CMAKE_SOURCE_DIR}/worker")
add_executable(test_load_bundle ofx/tests/test_load_bundle.cpp)
target_include_directories(test_load_bundle PRIVATE ${OFX_DIR}/include)
target_link_libraries(test_load_bundle PRIVATE cpo_models ${CMAKE_DL_LIBS})
add_dependencies(test_load_bundle ${BUNDLE_NAME})
add_test(NAME load_bundle COMMAND test_load_bundle ${BUNDLE_DIR}/Contents/${CPO_ARCH_DIR}/${BUNDLE_NAME}.ofx)
