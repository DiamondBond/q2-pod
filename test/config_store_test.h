#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int cfg_test_open(const char *, int, ...);
ssize_t cfg_test_read(int, void *, size_t);
ssize_t cfg_test_write(int, const void *, size_t);
int cfg_test_close(int);
int cfg_test_fsync(int);
int cfg_test_rename(const char *, const char *);
int cfg_test_unlink(const char *);
int stock_config_store_trampoline(const char *, const char *, const char *, const char *);
#define open cfg_test_open
#define read cfg_test_read
#define write cfg_test_write
#define close cfg_test_close
#define fsync cfg_test_fsync
#define rename cfg_test_rename
#define unlink cfg_test_unlink
