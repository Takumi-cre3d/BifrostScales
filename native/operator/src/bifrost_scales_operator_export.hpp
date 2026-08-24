#pragma once

#if defined(_WIN32)
#  if defined(BIFROST_SCALES_BUILD_NODEDEF_DLL)
#    define BIFROST_SCALES_NODEDEF_DECL __declspec(dllexport)
#  else
#    define BIFROST_SCALES_NODEDEF_DECL __declspec(dllimport)
#  endif
#else
#  define BIFROST_SCALES_NODEDEF_DECL __attribute__((visibility("default")))
#endif
