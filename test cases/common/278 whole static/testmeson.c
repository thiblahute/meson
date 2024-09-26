#include <stdio.h>

#define PROJECT_NAME "testmeson"

extern int two(void);

int main(int argc, char **argv) {
    if(argc != 1) {
        printf("%s takes no arguments.\n", argv[0]);
        return 1;
    }
    printf("This is project %s is %d\n", PROJECT_NAME, two());
    return 0;
}
