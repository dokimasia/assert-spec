/*
 * Bob Jenkins's small noncryptographic PRNG, the 64-bit three-rotate
 * variant, copied unchanged from
 * https://burtleburtle.net/bob/rand/smallprng.html, where its author
 * placed it in the public domain. main prints the first outputs for the
 * seeds the reference tests use, as JSON with decimal strings.
 *
 * Regenerate smallprng.json from this directory with:
 *
 *   cc -O2 -o /tmp/smallprng smallprng.c && /tmp/smallprng > smallprng.json
 */
#include <stdio.h>

typedef unsigned long long u8;
typedef struct ranctx { u8 a; u8 b; u8 c; u8 d; } ranctx;

#define rot(x,k) (((x)<<(k))|((x)>>(64-(k))))
u8 ranval( ranctx *x ) {
    u8 e = x->a - rot(x->b, 7);
    x->a = x->b ^ rot(x->c, 13);
    x->b = x->c + rot(x->d, 37);
    x->c = x->d + e;
    x->d = e + x->a;
    return x->d;
}

void raninit( ranctx *x, u8 seed ) {
    u8 i;
    x->a = 0xf1ea5eed, x->b = x->c = x->d = seed;
    for (i=0; i<20; ++i) {
        (void)ranval(x);
    }
}

int main(void) {
    static const u8 seeds[] = {
        0ULL, 1ULL, 42ULL, 0xffffffffffffffffULL, 0x0123456789abcdefULL,
    };
    const int count = sizeof seeds / sizeof seeds[0];
    const int outputs = 32;

    printf("{\n  \"generator\": \"jsf64, three rotations (7, 13, 37)\",\n");
    printf("  \"outputs\": {\n");
    for (int s = 0; s < count; ++s) {
        ranctx ctx;
        raninit(&ctx, seeds[s]);
        printf("    \"%llu\": [", seeds[s]);
        for (int i = 0; i < outputs; ++i) {
            printf("%s\"%llu\"", i == 0 ? "" : ", ", ranval(&ctx));
        }
        printf("]%s\n", s == count - 1 ? "" : ",");
    }
    printf("  }\n}\n");
    return 0;
}
