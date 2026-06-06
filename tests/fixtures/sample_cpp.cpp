#include <stdio.h>
#include <string.h>

#define MAX 10
#define MIN 1

int global_counter = 0;

int add(int a, int b) {
    return a + b;
}

// Pre-existing comment for multiply.
int multiply(int a, int b) {
    int result = a * b;
    return result;
}

int main(void) {
    char buffer[8];
    strcpy(buffer, "this string is definitely too long for the buffer");
    printf("%d\n", add(2, 3));
    return 0;
}
