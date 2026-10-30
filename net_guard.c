/* Kernel-enforced transport boundary, inherited across exec by Codex.
 * Landlock ABI >= 6: TCP connect only to 443, no TCP bind, no cross-domain
 * abstract Unix sockets/signalling. Filesystem isolation is Bubblewrap's job.
 */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

struct ruleset { uint64_t fs, net, scoped; };
struct port_rule { uint64_t allowed_access, port; };

int main(int argc, char **argv) {
    if (argc < 2) return 120;
    long abi = syscall(444, NULL, 0, 1);
    if (abi < 6) { fputs("NETWORK_GUARD_UNSUPPORTED\n", stderr); return 121; }
    struct ruleset attr = {0, 3, 3};
    int fd = (int)syscall(444, &attr, sizeof(attr), 0);
    struct port_rule rule = {2, 443};
    if (fd < 0 || syscall(445, fd, 2, &rule, 0) < 0 ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
        syscall(446, fd, 0) < 0) {
        fputs("NETWORK_GUARD_FAILED\n", stderr); return 122;
    }
    close(fd);
    execv(argv[1], argv + 1);
    return 123;
}
