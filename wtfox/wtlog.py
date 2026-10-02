#!/usr/bin/env python3
"""Decode War Thunder client logs (.game_logs/*.clog) and summarise mission sessions.

Usage:
  wtlog.py decode [clog] [out.log]   decode a .clog (default: newest) to text
  wtlog.py deaths [clog]             aircraft deaths per group: shot down vs crashed (no killer)
  wtlog.py missions [clog]           missions loaded/started, with difficulty
  wtlog.py splits [clog]             race runs: start, split-gate times (TRIG unitDamage on split_NN), crashes, result
  wtlog.py gates [clog] [out.json]   course-designer runs: gate positions dropped with flares/chaff -> json

A .clog is plain text XORed with a repeating 128-byte key. The key is recovered statistically
(the most common byte in each key column is a space), so no hardcoded key is needed.
"""
import collections, glob, os, re, sys

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


def newest():
    logs = sorted(glob.glob(os.path.join(_need_wt_dir(), '.game_logs', '*.clog')), key=os.path.getmtime)
    if not logs:
        sys.exit('no .clog files in ' + os.path.join(_need_wt_dir(), '.game_logs'))
    return logs[-1]


def decode(path, key_len=128):
    d = open(path, 'rb').read()
    key = bytes(collections.Counter(d[i::key_len][:50000]).most_common(1)[0][0] ^ 0x20 for i in range(key_len))
    return bytes(b ^ key[i % key_len] for i, b in enumerate(d)).decode('latin1')


def deaths(text):
    L = text.split('\n')
    c = collections.Counter()
    alts = collections.defaultdict(list)
    for i, l in enumerate(L):
        m = re.search(r'FMW  Aircraft (\S+) \(([^)]+)\) died.*reason = (\d+)', l)
        if not m:
            continue
        k = None
        for j in range(i + 1, min(i + 8, len(L))):
            k = re.search(r'killed by:(.*?)\(uid (\d+)\), at = \(([-\d.]+), ([-\d.]+), ([-\d.]+)\)', L[j])
            if k:
                break
        grp = re.sub(r'_\d+$', '', m.group(1))
        crash = bool(k and k.group(2) == '65535')
        c[(grp, m.group(2), 'CRASH (no killer)' if crash else 'shot down')] += 1
        if crash:
            alts[grp].append(round(float(k.group(4))))
    for key, v in sorted(c.items(), key=lambda x: -x[1]):
        print(v, *key)
    for g, a in alts.items():
        print(f'{g}: crash altitudes {sorted(a)}')


def splits(text):
    """Per race run: split gates (logged as 'TRIG unitDamage action for unit split_NN_0'), crashes, result."""
    run = None
    for l in text.split('\n'):
        m = re.match(r'\s*([\d.]+) .*MISSION (\S+) STARTED at difficulty (\w+)', l)
        if m:
            if run and run['splits']:
                _print_run(run)
            run = {'t0': float(m.group(1)), 'name': m.group(2), 'diff': m.group(3), 'splits': [], 'crashes': [], 'end': None}
            continue
        if not run:
            continue
        m = re.match(r'\s*([\d.]+) TRIG unitDamage action for unit (split_\d+)', l)
        if m:
            run['splits'].append((float(m.group(1)), m.group(2)))
        m = re.match(r'\s*([\d.]+) FMW  Aircraft player_wing_\d+ .* died', l)
        if m:
            run['crashes'].append(float(m.group(1)))
        m = re.match(r'\s*([\d.]+) .*AcesMission::setStatus MISSION_STATUS_RUNNING -> (MISSION_STATUS_\w+)', l)
        if m:
            run['end'] = (float(m.group(1)), m.group(2))
    if run and run['splits']:
        _print_run(run)


def gates(text, out):
    """Course-designer runs: 'RespawnAction: sending respawn to unit mission_name:flag_NNN_0' is followed by
    'UnitRespawn received ... pos:(x,y,z)' and a DBGSPAWN line whose tm gives the heading."""
    import json
    runs, cur, pending = [], None, None
    for l in text.split('\n'):
        m = re.match(r'\s*([\d.]+) .*MISSION (course_designer\S*) STARTED', l)
        if m:
            cur = {'mission': m.group(2), 't0': float(m.group(1)), 'gates': []}
            runs.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r'RespawnAction: sending respawn to unit mission_name:(flag_\d+)', l)
        if m:
            pending = {'flag': m.group(1), 't': float(l.split()[0])}
            continue
        if pending:
            m = re.search(r'UnitRespawn received .*pos:\(([-\d.]+),([-\d.]+),([-\d.]+)\)', l)
            if m and 'pos' not in pending:
                pending['pos'] = tuple(map(float, m.groups()))
                continue
            m = re.search(r'DBGSPAWN .*tm:\{\(([-\d.]+),([-\d.]+),([-\d.]+)\)', l)
            if m and 'pos' in pending:
                fx, _, fz = map(float, m.groups())
                pending['fwd'] = (fx, fz)
            if 'pos' in pending and ('fwd' in pending or 'UnitRespawn' not in l):
                cur['gates'].append(pending)
                pending = None
    runs = [r for r in runs if r['gates']]
    for r in runs:
        print(f"== {r['mission']}: {len(r['gates'])} gates")
        prev = None
        for g in r['gates']:
            x, y, z = g['pos']
            d = (((x - prev[0]) ** 2 + (z - prev[2]) ** 2) ** 0.5) if prev else 0.0
            print(f"  {g['flag']}  ({x:9.0f}, {y:6.0f}, {z:9.0f})  {'+%.0f m' % d if prev else ''}")
            prev = g['pos']
    if runs:
        json.dump(runs[-1], open(out, 'w'), indent=1)
        print(f'last run saved to {out}')


def _print_run(r):
    print(f"== {r['name']} ({r['diff']}), started {r['t0']:.2f}")
    prev = r['t0']
    for t, n in r['splits']:
        crash = sum(1 for c in r['crashes'] if prev < c <= t)
        print(f"  {n:10s} at +{t - r['t0']:8.2f}s  segment {t - prev:7.2f}s{'  (' + str(crash) + ' crash)' if crash else ''}")
        prev = t
    if r['end']:
        print(f"  end: {r['end'][1]} at +{r['end'][0] - r['t0']:.2f}s")


def main(a):
    cmd = a[1] if len(a) > 1 else 'missions'
    path = a[2] if len(a) > 2 else newest()
    text = decode(path)
    if cmd == 'decode':
        out = a[3] if len(a) > 3 else 'game.log'
        open(out, 'w', encoding='latin1').write(text)
        print(f'{path} -> {out}')
    elif cmd == 'deaths':
        deaths(text)
    elif cmd == 'gates':
        gates(text, a[3] if len(a) > 3 else 'gates.json')
    elif cmd == 'splits':
        splits(text)
    elif cmd == 'missions':
        for l in text.split('\n'):
            if re.search(r"MISSION \S+ STARTED|Load mission '", l):
                print(l.strip()[:200])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
