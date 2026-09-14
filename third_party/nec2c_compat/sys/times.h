/*
 * Windows (MinGW) compatibility shim for building nec2c unmodified.
 *
 * nec2c includes <sys/times.h> and uses times(), sysconf(_SC_CLK_TCK),
 * and sigaction(), none of which exist on MinGW. nec2c.h includes <signal.h>
 * before this header, so the sigaction replacement can live here too.
 */
#ifndef ANTENNASIM_NEC2C_COMPAT_SYS_TIMES_H
#define ANTENNASIM_NEC2C_COMPAT_SYS_TIMES_H

#include <signal.h>
#include <time.h>

typedef long clock_t_compat;

struct tms {
  clock_t_compat tms_utime;
  clock_t_compat tms_stime;
  clock_t_compat tms_cutime;
  clock_t_compat tms_cstime;
};

static inline clock_t_compat times(struct tms *buf)
{
  clock_t c = clock();
  buf->tms_utime = (clock_t_compat)c;
  buf->tms_stime = 0;
  buf->tms_cutime = 0;
  buf->tms_cstime = 0;
  return (clock_t_compat)c;
}

#ifndef _SC_CLK_TCK
#define _SC_CLK_TCK 2
#endif

static inline long sysconf(int name)
{
  (void)name;
  return (long)CLOCKS_PER_SEC;
}

typedef int sigset_t_compat;

struct sigaction {
  void (*sa_handler)(int);
  sigset_t_compat sa_mask;
  int sa_flags;
};

static inline int sigemptyset(sigset_t_compat *set)
{
  *set = 0;
  return 0;
}

static inline int sigaction(int sig, const struct sigaction *act,
                            struct sigaction *oldact)
{
  void (*prev)(int) = signal(sig, act->sa_handler);
  if (oldact) {
    oldact->sa_handler = prev;
    oldact->sa_mask = 0;
    oldact->sa_flags = 0;
  }
  return 0;
}

#endif
