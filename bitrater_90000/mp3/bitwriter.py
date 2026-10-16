class BitWriter:
    def __init__(self):
        self.data = bytearray()
        self._acc = 0
        self._count = 0
        self.length = 0

    def write(self, value: int, bits: int) -> None:
        if bits == 0:
            return
        self._acc = (self._acc << bits) | (value & ((1 << bits) - 1))
        self._count += bits
        self.length += bits
        while self._count >= 8:
            self._count -= 8
            self.data.append((self._acc >> self._count) & 0xFF)
        self._acc &= (1 << self._count) - 1

    def append(self, other: "BitWriter") -> None:
        for byte in other.data:
            self.write(byte, 8)
        self.write(other._acc, other._count)

    def to_bytes(self) -> bytes:
        if self._count == 0:
            return bytes(self.data)
        return bytes(self.data) + bytes([(self._acc << (8 - self._count)) & 0xFF])