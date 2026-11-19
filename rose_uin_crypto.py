#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
玫瑰小镇(meigui)好友 uin 加解密 —— 逆向自客户端
Rose.Models.UserDataUitls.EncryptUin / DecryptUin
文件来源: assets/main/index.57d00.js (UserData 模块, cc._RF 名 "UserData")

算法概述:
  明文 = uin 的 4 字节大端 (writeUint32)
  密钥 = 16 字节, 即 4 个 uint32: 1919906661,825438516,1835626089,1734438245
         = ASCII "rosa" "1094" "megi" "gahe"  (即 b"rosa1094megigahe")
  分组 = 修改版 TEA (16 轮, delta=0x9E3779B9), 8 字节分组
  模式 = 自定义 CBC/PCBC 混合 (见 wrapper), 输出 8 字节对齐
  结果 = 大写/小写十六进制字符串, 4 字节明文 -> 16 字节 -> 32 个 hex 字符 (随机化)
"""
import random

MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9
KEY_WORDS = [1919906661, 825438516, 1835626089, 1734438245]  # "rosa1094megigahe"
KEY_ANSI = b"rosa1094megigahe"


class BB:
    """最小复刻 Milkytea.ByteBuffer (只实现加解密用到的部分, 大端)"""
    def __init__(self, size=1024):
        if isinstance(size, int):
            self.buf = bytearray(size)
            self._length = 0
        else:  # bytes/bytearray -> 固定内容 buffer
            self.buf = bytearray(size)
            self._length = len(size)
        self.off = 0

    @property
    def length(self):
        return self._length

    def write_u8(self, v):
        self.buf[self.off] = v & 0xFF
        self.off += 1
        self._length += 1

    write_i8 = write_u8

    def read_u8(self):
        v = self.buf[self.off]
        self.off += 1
        return v

    read_i8 = read_u8  # xor 场景下与有符号读等价

    def write_u32(self, v):
        v &= MASK
        self.buf[self.off:self.off + 4] = v.to_bytes(4, "big")
        self.off += 4
        self._length += 4

    def read_u32(self):
        v = int.from_bytes(self.buf[self.off:self.off + 4], "big")
        self.off += 4
        return v

    def write_bytes(self, src):
        for i in range(src.length):
            self.write_u8(src.buf[i])

    def read_bytes(self, k):
        nb = BB(bytearray(self.buf[self.off:self.off + k]))
        self.off += k
        return nb


def _key_bb():
    k = BB(64)
    for w in KEY_WORDS:
        k.write_u32(w)
    k.off = 0
    return k


def _rnd():
    return random.randint(0, 255)


def _tea_enc_block(blk, key):
    # 对应 function u(e,t)
    blk.off = 0
    v0 = blk.read_u32()
    v1 = blk.read_u32()
    key.off = 0
    k = [key.read_u32() for _ in range(4)]
    s = 0
    for _ in range(16):
        s = (s + DELTA) & MASK
        v0 = (v0 + (((((v1 << 4) & MASK) + k[0]) & MASK) ^ ((v1 + s) & MASK) ^ (((v1 >> 5) + k[1]) & MASK))) & MASK
        v1 = (v1 + (((((v0 << 4) & MASK) + k[2]) & MASK) ^ ((v0 + s) & MASK) ^ (((v0 >> 5) + k[3]) & MASK))) & MASK
    out = BB(64)
    out.write_u32(v0)
    out.write_u32(v1)
    out.off = 0
    return out


def _tea_dec_block(blk, key):
    # 对应 function c(e,t)
    blk.off = 0
    v0 = blk.read_u32()
    v1 = blk.read_u32()
    key.off = 0
    k = [key.read_u32() for _ in range(4)]
    s = 3816266640  # = 16*delta mod 2^32
    for _ in range(16):
        v1 = (v1 - (((((v0 << 4) & MASK) + k[2]) & MASK) ^ ((v0 + s) & MASK) ^ (((v0 >> 5) + k[3]) & MASK))) & MASK
        v0 = (v0 - (((((v1 << 4) & MASK) + k[0]) & MASK) ^ ((v1 + s) & MASK) ^ (((v1 >> 5) + k[1]) & MASK))) & MASK
        s = (s - DELTA) & MASK
    out = BB(64)
    out.write_u32(v0)
    out.write_u32(v1)
    out.off = 0
    return out


def _encrypt_wrap(e, t):
    # 对应 function t(e,t)
    e.off = 0
    t.off = 0
    n = e.length
    a = (n + 1 + 2 + 7) % 8
    if a > 0:
        a = 8 - a
    s = BB(4096)
    l = BB(64)
    l.write_i8((248 & _rnd()) | a)
    while a > 0:
        l.write_i8(_rnd())
        a -= 1
    c = BB(64)
    for _ in range(8):
        c.write_i8(0)
    y = c

    def _emit():
        for i in range(8):
            l.buf[i] ^= y.buf[i]
        p = _tea_enc_block(l, t)
        for i in range(8):
            p.buf[i] ^= c.buf[i]
        for i in range(8):
            c.buf[i] = l.buf[i]
        l.off = 0
        s.write_bytes(p)
        return p

    r = 1
    while r <= 2:
        if l.off < 8:
            l.write_i8(_rnd())
            r += 1
        if l.off == 8:
            y = _emit()
    while n > 0:
        if l.off < 8:
            l.write_i8(e.read_i8())
            n -= 1
        if l.off == 8:
            y = _emit()
    r = 1
    while r <= 7:
        if l.off < 8:
            l.write_i8(0)
            r += 1
        if l.off == 8:
            # 注意: 源码末块为 c[i]=l[i] 的 no-op bug, 此处忠实保留(不影响输出)
            for i in range(8):
                l.buf[i] ^= y.buf[i]
            p = _tea_enc_block(l, t)
            for i in range(8):
                p.buf[i] ^= c.buf[i]
            l.off = 0
            s.write_bytes(p)
            y = p
    s.off = 0
    return s


def _decrypt_wrap(e, t):
    # 对应 function r(e,t)
    e.off = 0
    t.off = 0
    o = e.length
    if o < 16 or o % 8 != 0:
        raise ValueError("解密错误")
    nbuf = BB(4096)
    a = e.read_bytes(8)
    s = _tea_dec_block(a, t)
    l = 7 & s.buf[0]
    r = o - 1 - l - 2 - 7
    if r < 0:
        raise ValueError("解密错误")
    p = r
    u = BB(64)
    for _ in range(8):
        u.write_u8(0)
    y = u
    s.off = 1 + l
    r = 1
    while r <= 2:
        if s.off < 8:
            s.off += 1
            r += 1
        elif s.off == 8:
            y = a
            a = e.read_bytes(8)
            for i in range(8):
                s.buf[i] ^= a.buf[i]
            s = _tea_dec_block(s, t)
            s.off = 0
    y.off = s.off
    while p > 0:
        if s.off < 8:
            nbuf.write_u8(s.read_u8() ^ y.read_u8())
            p -= 1
        elif s.off == 8:
            y = a
            a = e.read_bytes(8)
            for i in range(8):
                s.buf[i] ^= a.buf[i]
            s = _tea_dec_block(s, t)
            s.off = 0
            y.off = 0
    r = 1
    while r <= 7:
        if s.off < 8:
            if (s.read_u8() ^ y.read_u8()) != 0:
                raise ValueError("解密错误")
            r += 1
        elif s.off == 8:
            y = a
            e.off = 0
            a = e.read_bytes(8)
            for i in range(8):
                s.buf[i] ^= a.buf[i]
            s = _tea_dec_block(s, t)
            s.off = 0
            y.off = 0
    nbuf.off = 0
    return nbuf


def _bytes_to_hex(bb):
    return "".join("%02x" % bb.buf[i] for i in range(bb.length))


def _hex_to_bytes(h):
    h = h.upper()
    out = BB(4096)
    i = 0
    hexd = "0123456789ABCDEF"
    while i < len(h):
        if h[i] in " \t\r\n":
            i += 1
            continue
        if i == len(h) - 1:
            raise ValueError("bad hex")
        out.write_u8((hexd.index(h[i]) << 4) + hexd.index(h[i + 1]))
        i += 2
    out.off = 0
    return out


def EncryptUin(uin):
    """明文 QQ 号 -> 小写十六进制密文串 (随机化, 每次不同但对同一 uin 均可解)"""
    key = _key_bb()
    pb = BB(64)
    pb.write_u32(int(uin))
    enc = _encrypt_wrap(pb, key)
    return _bytes_to_hex(enc)


def DecryptUin(hexstr):
    """十六进制密文串 -> 明文 QQ 号 (int)"""
    key = _key_bb()
    plain = _decrypt_wrap(_hex_to_bytes(hexstr), key)
    return plain.read_u32()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "dec":
        print(DecryptUin(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "enc":
        print(EncryptUin(int(sys.argv[2])))
    else:
        for u in [0, 1, 42, 10001, 123456789, 2147483647, 4000000000]:
            c = EncryptUin(u)
            d = DecryptUin(c)
            print(f"uin={u} enc={c} dec={d} ok={d==u}")
