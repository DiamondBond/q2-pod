/* dbus-arch-deps.h for the Q2 (mipsel o32, glibc 2.28, the rootfs's libdbus 1.12): what libdbus's
 * configure writes on that target. The build host's copy (x86-64) would make dbus_int64_t a `long`.
 * Used only to compile patch/mpris.c: tools/build.py compile_helper places it as
 * dbus/dbus-arch-deps.h ahead of the host's libdbus-1-dev headers, which are otherwise
 * architecture-independent. */
#ifndef DBUS_ARCH_DEPS_H
#define DBUS_ARCH_DEPS_H
#include <dbus/dbus-macros.h>
DBUS_BEGIN_DECLS
#define DBUS_HAVE_INT64 1
_DBUS_GNUC_EXTENSION typedef long long dbus_int64_t;
_DBUS_GNUC_EXTENSION typedef unsigned long long dbus_uint64_t;
#define DBUS_INT64_CONSTANT(val) (_DBUS_GNUC_EXTENSION(val##LL))
#define DBUS_UINT64_CONSTANT(val) (_DBUS_GNUC_EXTENSION(val##ULL))
#define DBUS_INT64_PRINTF_MODIFIER "ll"
typedef int dbus_int32_t;
typedef unsigned int dbus_uint32_t;
typedef short dbus_int16_t;
typedef unsigned short dbus_uint16_t;
#define DBUS_MAJOR_VERSION 1
#define DBUS_MINOR_VERSION 12
#define DBUS_MICRO_VERSION 20
#define DBUS_VERSION_STRING "1.12.20"
#define DBUS_VERSION ((1 << 16) | (12 << 8) | (20))
DBUS_END_DECLS
#endif
