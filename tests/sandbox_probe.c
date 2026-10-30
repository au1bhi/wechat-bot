#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 5) return 2;
    char hostname[128] = {0};
    gethostname(hostname, sizeof(hostname)-1);
    int canary = open(argv[1], O_RDONLY);
    int private_home = open(argv[2], O_RDONLY);
    char proc_path[128];
    snprintf(proc_path, sizeof(proc_path), "/proc/%s/cmdline", argv[3]);
    int host_process = open(proc_path, O_RDONLY);
    int shell = access("/bin/sh", F_OK) == 0;
    int docker = access("/var/run/docker.sock", F_OK) == 0;
    int bus = access("/run/user/1000/bus", F_OK) == 0;
    int fd = open("/proc/cpuinfo", O_RDONLY); char c;
    int cpu = fd >= 0 && read(fd,&c,1) > 0;
    int s = socket(AF_INET,SOCK_STREAM,0);
    struct sockaddr_in addr = {.sin_family=AF_INET,.sin_port=htons(atoi(argv[4]))};
    inet_pton(AF_INET,"127.0.0.1",&addr.sin_addr);
    errno=0;
    int connected = connect(s,(struct sockaddr*)&addr,sizeof(addr));
    int network_errno = errno;
    printf("{\"canary\":%s,\"private_home\":%s,\"host_process\":%s,"
           "\"shell\":%s,\"docker\":%s,\"dbus\":%s,\"cpu_info\":%s,"
           "\"leaked_env\":%s,\"hostname\":\"%s\",\"connected\":%s,\"network_errno\":%d}\n",
           canary>=0?"true":"false",private_home>=0?"true":"false",host_process>=0?"true":"false",
           shell?"true":"false",docker?"true":"false",bus?"true":"false",cpu?"true":"false",
           getenv("HOST_PRIVATE_CANARY")?"true":"false",hostname,connected==0?"true":"false",network_errno);
    return 0;
}
