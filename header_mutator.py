# header_mutator.py

from __future__ import annotations
import random

PRINTABLE = list(range(32, 127))  # ASCII printable


def _flip_bit(byte: int, rng: random.Random) -> int:
    return byte ^ (1 << rng.randrange(8))


def _mutate_byte(byte: int, rng: random.Random) -> int:
    op = rng.randrange(4)

    if op == 0:
        # small arithmetic tweak
        return (byte + rng.randint(-5, 5)) & 0xFF

    elif op == 1:
        # flip a bit
        return _flip_bit(byte, rng)

    elif op == 2:
        # replace with printable
        return rng.choice(PRINTABLE)

    else:
        # keep it (stability bias)
        return byte


def mutate_header_precise(header: bytes, rng: random.Random, max_mut: int = 16) -> bytes:
    """
    Carefully mutate header while preserving structure.

    Strategy:
    - Mutate only a few bytes
    - Bias toward printable characters
    - Avoid large-scale corruption
    """

    if not header:
        return header

    h = bytearray(header)

    # number of mutations (small!)
    num_mut = rng.randint(1, max_mut)

    for _ in range(num_mut):
        pos = rng.randrange(len(h))

        # Bias: avoid mutating first few bytes too often (sometimes metadata)
        if pos < 8 and rng.random() < 0.7:
            continue

        h[pos] = _mutate_byte(h[pos], rng)

    return bytes(h)
