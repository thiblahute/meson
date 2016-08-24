#!/usr/bin/env python3
import sys

with open(sys.argv[1], "w") as out:
    out.write("#ifndef B_H\n#define B_H\n#include <stdio.h>\n"
              "void hello(void);\n#endif")
