#ifndef LIUQIN_R101_H
#define LIUQIN_R101_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void liuqin_r101_emit(int summary, const char *, ...) __attribute__((format(printf, 2, 3)));
void liuqin_r101_ipc(int, int, uint32_t, uint32_t, uint64_t, uint64_t, const void *, unsigned, unsigned);
void liuqin_r101_iokit(const char *, const char *, unsigned);
void liuqin_r101_scale(unsigned, unsigned, uint32_t, unsigned, uint64_t, uint64_t, uint64_t);
void liuqin_r101_storage_dump(void);
#ifdef __cplusplus
}
#endif
#endif
