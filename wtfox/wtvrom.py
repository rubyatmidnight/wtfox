#!/usr/bin/env python3
"""Read War Thunder .vromfs.bin archives and decode binary BLK files to text.

Usage:
  wtvrom.py ls   <archive> [substring]          list files in an archive
  wtvrom.py cat  <archive> <path>               decode one file to stdout
  wtvrom.py dump <archive> <prefix> <outdir>    decode every file under prefix into outdir

<archive> is a name like "mis", "aces" (resolved under $WT_DIR, or the usual install locations)
or a path to any .vromfs.bin.

Format notes (verified against the September 2026 game builds):
  * VRFx container: 16-byte header + 8-byte ext header, payload is zstd with the first
    16 bytes and last aligned 16 bytes XOR-obfuscated with fixed keys.
  * Inside: name table + data table (offset/size pairs). A '*.dict' entry is a shared zstd
    dictionary; the '\\xff?nm' entry is a zstd-compressed shared name map.
  * BLK type byte: 1 FAT, 2 FAT_ZSTD, 3 SLIM, 4 SLIM_ZSTD, 5 SLIM_ZSTD_DICT.
    SLIM files take names from the shared nm map.
"""
import os, struct, sys
import zstandard

CONFIG = os.path.join(os.path.expanduser('~'), '.wtfox_path')


def _is_wt_dir(p):
    return bool(p) and os.path.isfile(os.path.join(p, 'aces.vromfs.bin'))


def _find_wt_dir():
    """$WT_DIR, else the remembered path (~/.wtfox_path), else a common install location."""
    if os.environ.get('WT_DIR'):
        return os.environ['WT_DIR']
    try:
        saved = open(CONFIG).read().strip()
        if _is_wt_dir(saved):
            return saved
    except OSError:
        pass
    for c in [r'C:\Program Files (x86)\Steam\steamapps\common\War Thunder',
              r'C:\Program Files\WarThunder', r'C:\Games\WarThunder',
              '/mnt/c/Program Files (x86)/Steam/steamapps/common/War Thunder', '/mnt/c/Program Files/WarThunder',
              os.path.expanduser('~/.local/share/Steam/steamapps/common/War Thunder'),
              os.path.expanduser('~/Games/WarThunder')]:
        if _is_wt_dir(c):
            return c
    return None


WT_DIR = _find_wt_dir()


def _need_wt_dir():
    """Return the game folder, asking for it (and remembering it) if it couldn't be found."""
    global WT_DIR
    if WT_DIR:
        return WT_DIR
    if not sys.stdin.isatty():
        sys.exit('War Thunder install not found: set WT_DIR to the game folder (the one containing aces.vromfs.bin)')
    while True:
        p = input('War Thunder folder (the one containing aces.vromfs.bin): ').strip().strip('"').strip("'")
        if _is_wt_dir(p):
            break
        print('  aces.vromfs.bin not found there, try again (Ctrl+C to quit)')
    try:
        open(CONFIG, 'w').write(p)
        print(f'  remembered in {CONFIG}')
    except OSError:
        pass
    WT_DIR = p
    return p
_K1 = struct.pack('<4I', 0xaa55aa55, 0xf00ff00f, 0xaa55aa55, 0x12481248)
_K2 = struct.pack('<4I', 0x12481248, 0xaa55aa55, 0xf00ff00f, 0xaa55aa55)
TYPE_SUFFIX = {1: 't', 2: 'i', 3: 'r', 4: 'p2', 5: 'p3', 6: 'p4', 7: 'ip2', 8: 'ip3', 9: 'b', 0xa: 'c', 0xb: 'm', 0xc: 'i64'}


def _uleb(b, p):
    r = s = 0
    while True:
        c = b[p]; p += 1
        r |= (c & 0x7f) << s; s += 7
        if not c & 0x80:
            return r, p


def _names(b, p):
    cnt, p = _uleb(b, p)
    sz, p = _uleb(b, p)
    lst = b[p:p + sz].split(b'\0')[:cnt]
    return [x.decode('utf8', 'replace') for x in lst], p + sz


_PLAIN_NAME = __import__('re').compile(r'^[A-Za-z_@#][\w@#.\-]*$')


def _name(n):
    """Param/block names with spaces etc. are legal in binary BLK but must be quoted in text BLK."""
    return n if _PLAIN_NAME.match(n) else '"%s"' % n.replace('~', '~~').replace('"', '~"')


def _num(x):
    r = '%.7g' % x
    return r if any(c in r for c in '.en') else r + '.0'


class Archive:
    def __init__(self, path):
        if not path.endswith('.bin'):
            path = os.path.join(_need_wt_dir(), path + '.vromfs.bin')
        self.path = path
        self.raw = self._unpack(open(path, 'rb').read())
        no, nc = struct.unpack_from('<II', self.raw, 0)
        do, _ = struct.unpack_from('<II', self.raw, 16)
        self.files = {}
        for i in range(nc):
            o = struct.unpack_from('<Q', self.raw, no + 8 * i)[0]
            name = self.raw[o:self.raw.index(b'\0', o)].decode('latin1')
            off, sz = struct.unpack_from('<II', self.raw, do + 16 * i)
            self.files[name] = (off, sz)
        self._dict = self._nm = None

    @staticmethod
    def _unpack(raw):
        magic, _plat, size, packed = struct.unpack_from('<4s4sII', raw, 0)
        psize, off = packed & 0x3ffffff, 16
        if magic == b'VRFx':
            off += 8
        if psize == 0:                       # stored uncompressed
            return raw[off:off + size]
        data = bytearray(raw[off:off + psize])
        n = len(data)
        for i in range(min(16, n)):
            data[i] ^= _K1[i]
        if n >= 32:
            e = n & ~3
            for i in range(16):
                data[e - 16 + i] ^= _K2[i]
        return zstandard.ZstdDecompressor().decompress(bytes(data), max_output_size=size)

    def get(self, name):
        off, sz = self.files[name]
        return self.raw[off:off + sz]

    @property
    def zdict(self):
        if self._dict is None:
            d = [n for n in self.files if n.endswith('.dict')]
            self._dict = zstandard.ZstdCompressionDict(self.get(d[0])) if d else False
        return self._dict

    @property
    def nm(self):
        if self._nm is None:
            raw = self.get('\xff?nm') if '\xff?nm' in self.files else None
            if raw:
                data = zstandard.ZstdDecompressor().decompress(raw[40:], max_output_size=256 << 20)
                self._nm = _names(data, 0)[0]
            else:
                self._nm = []
        return self._nm

    def text(self, name):
        """Return a file as text: decoded BLK, or the raw bytes decoded if it's plain text."""
        b = self.get(name)
        if name.endswith('.blk') and b and b[0] in (1, 2, 3, 4, 5):
            return decode_blk(b, self)
        return b.decode('utf8', 'replace')


def decode_blk(b, arc):
    t = b[0]
    zd = zstandard.ZstdDecompressor
    if t == 5:
        b = zd(dict_data=arc.zdict).decompress(b[1:], max_output_size=256 << 20)
    elif t in (2, 4):
        b = zd().decompress(b[1:], max_output_size=256 << 20)
    else:
        b = b[1:]
    ncnt, p = _uleb(b, 0)
    if ncnt:
        names, p = _names(b, 0)
    else:
        names = arc.nm
    bcnt, p = _uleb(b, p)
    pcnt, p = _uleb(b, p)
    psz, p = _uleb(b, p)
    pdata = b[p:p + psz]; p += psz
    params = []
    for _ in range(pcnt):
        a, d = struct.unpack_from('<II', b, p)
        params.append((a & 0xffffff, a >> 24, d, b[p + 4:p + 8])); p += 8
    blocks = []
    for _ in range(bcnt):
        nid, p = _uleb(b, p); pc, p = _uleb(b, p); bc, p = _uleb(b, p); fb = None
        if bc:
            fb, p = _uleb(b, p)
        blocks.append((nid, pc, bc, fb))

    def val(t, d, rd):
        if t == 1:
            if d & 0x80000000:
                s = names[d & 0x7fffffff]
            else:
                s = pdata[d:pdata.index(b'\0', d)].decode('utf8', 'replace')
            # Dagor text BLK escapes with '~' and also accepts single-quoted strings
            s = s.replace('~', '~~').replace('\n', '~n').replace('\t', '~t')
            if '"' in s and "'" not in s:
                return "'%s'" % s
            return '"%s"' % s.replace('"', '~"')
        if t == 2: return str(struct.unpack('<i', rd)[0])
        if t == 3: return _num(struct.unpack('<f', rd)[0])
        if t in (4, 5, 6): return ', '.join(_num(x) for x in struct.unpack_from('<%df' % (t - 2), pdata, d))
        if t in (7, 8): return ', '.join(map(str, struct.unpack_from('<%di' % (t - 5), pdata, d)))
        if t == 9: return 'yes' if d else 'no'
        if t == 0xa: return ', '.join(map(str, (rd[2], rd[1], rd[0], rd[3])))
        if t == 0xb:
            return '[' + ' '.join('[%s]' % ', '.join(_num(x) for x in struct.unpack_from('<3f', pdata, d + 12 * k)) for k in range(4)) + ']'
        if t == 0xc: return str(struct.unpack_from('<q', pdata, d)[0])
        raise ValueError('unknown BLK param type %d' % t)

    starts, acc = [], 0
    for bl in blocks:
        starts.append(acc); acc += bl[1]
    out = []

    def emit(bi, ind):
        _nid, pc, bc, fb = blocks[bi]
        for k in range(pc):
            n, t, d, rd = params[starts[bi] + k]
            out.append('  ' * ind + '%s:%s=%s' % (_name(names[n]), TYPE_SUFFIX[t], val(t, d, rd)))
        for c in range(bc):
            cb = fb + c
            out.append('  ' * ind + _name(names[blocks[cb][0] - 1]) + '{')
            emit(cb, ind + 1)
            out.append('  ' * ind + '}')
    emit(0, 0)
    return '\n'.join(out) + '\n'


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd, arc = argv[1], Archive(argv[2])
    if cmd == 'ls':
        sub = argv[3] if len(argv) > 3 else ''
        for n in arc.files:
            if sub in n:
                print(n)
    elif cmd == 'cat':
        sys.stdout.write(arc.text(argv[3]))
    elif cmd == 'dump':
        prefix, outdir = argv[3], argv[4]
        ok = bad = 0
        for n in arc.files:
            if n.startswith(prefix):
                dst = os.path.join(outdir, n[len(prefix):].lstrip('/'))
                os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
                try:
                    open(dst, 'w').write(arc.text(n)); ok += 1
                except Exception as e:
                    print('failed:', n, e, file=sys.stderr); bad += 1
        print(f'{ok} files written, {bad} failed', file=sys.stderr)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
