/* parse-only prelude for the Windows run of check_collisions.py: names the
 * redirect layer supplies on Windows (upstream never builds green threads there) */
#define F_GETFL 3
#define F_SETFL 4
#define O_NONBLOCK 04000
int fcntl(int fd, int cmd, ...);
int usleep(unsigned usec);
struct pollfd;
int poll(struct pollfd *fds, unsigned long n, int timeout);
