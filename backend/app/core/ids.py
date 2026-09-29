"""Time-ordered UUIDs (RFC 9562 version 7) for primary keys."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    # 48-bit unix ms | 4-bit version | 12 random bits | 2-bit variant | 62 random bits
    unix_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0xFFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)
