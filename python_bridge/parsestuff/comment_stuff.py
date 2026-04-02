#!/bin/sh

fh = open("source.c", "r")

lines = fh.readlines()

fh.close()


for line in lines:
  # First strip out the existing comments.
  if "//" in line:
    line = line[:line.index("//")]
  if len(line) == 0:

    print("// "+line)
  else:
    print("// "+str(line),end="")

