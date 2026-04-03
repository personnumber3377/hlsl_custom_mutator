#!/bin/sh

find /path/to/source -type f -name "*.hlsl" -exec sh -c 'cp "$1" /path/to/flat/$(basename "$1")_$(sha1sum "$1" | cut -c1-8).hlsl' _ {} \;



