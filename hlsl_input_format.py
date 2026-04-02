from __future__ import annotations
from dataclasses import dataclass


HEADER_SIZE = 8


@dataclass
class Header:
    exec_mode: int = 0
    sub_mode: int = 0
    src_mode: int = 0
    bits0: int = 0
    bits1: int = 0
    bits2: int = 0
    reserved0: int = 0
    reserved1: int = 0


def clamp_u8(x: int) -> int:
    return x & 0xFF


def unpack_blob(data: bytes) -> tuple[Header, bytes]:
    if len(data) < HEADER_SIZE:
        data = data + b"\x00" * (HEADER_SIZE - len(data))
    h = Header(
        exec_mode=data[0],
        sub_mode=data[1],
        src_mode=data[2],
        bits0=data[3],
        bits1=data[4],
        bits2=data[5],
        reserved0=data[6],
        reserved1=data[7],
    )
    return h, data[HEADER_SIZE:]


def pack_blob(h: Header, source: bytes) -> bytes:
    return bytes([
        clamp_u8(h.exec_mode),
        clamp_u8(h.sub_mode),
        clamp_u8(h.src_mode),
        clamp_u8(h.bits0),
        clamp_u8(h.bits1),
        clamp_u8(h.bits2),
        clamp_u8(h.reserved0),
        clamp_u8(h.reserved1),
    ]) + source
