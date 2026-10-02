"""Generate a closed race circuit (race_wp_NNN gates + spawn points) for any flat-enough map.

Used by gen_race.py --course. The circuit is a smooth star-shaped loop
    P(t) = C + rho(t) * (cos t, sin t),  rho(t) = R0 * (1 + sum a_k cos(k t + p_k))
which can't self-intersect. Random harmonics (seeded) are rejected until every turn's radius of
curvature is >= rmin, then R0 is scaled to the target length. Altitude rolls smoothly between
alt_lo..alt_hi with the climb grade capped.

Gate orientation follows Gaijin's race_wp convention (verified against phiphi_race):
    row0 = up * s,  row1 = (-fz, 0, fx) * s,  row2 = forward * s   (row2 = row0 x row1)
"""
import math, random

# Known-safe envelopes (centre x,z in metres; max half-extent) from Gaijin's own missions.
MAPS = {
    'air_denmark': {'centre': (-15000.0, 10000.0), 'half': 40000.0, 'max_ground': 120.0},
}


def _curve(params, R0, centre, t):
    rho = R0 * (1.0 + sum(a * math.cos(k * t + p) for k, a, p in params))
    return centre[0] + rho * math.cos(t), centre[1] + rho * math.sin(t)


def _sample(params, R0, centre, n=4000):
    return [_curve(params, R0, centre, 2 * math.pi * i / n) for i in range(n)]


def _length(pts):
    return sum(math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))


def _min_radius(pts, step=8):
    n, r = len(pts), 1e12
    for i in range(0, n, 1):
        A, B, C = pts[(i - step) % n], pts[i], pts[(i + step) % n]
        a, b, c = math.dist(B, C), math.dist(A, C), math.dist(A, B)
        area = abs((B[0] - A[0]) * (C[1] - A[1]) - (C[0] - A[0]) * (B[1] - A[1])) / 2
        if area > 1e-6:
            r = min(r, a * b * c / (4 * area))
    return r


def make_course(map_name='air_denmark', seed=1, km=90.0, rmin=2000.0, gate=300.0,
                alt=(400.0, 2500.0), spacing=2500.0, max_grade=0.12):
    m = MAPS[map_name]
    rng = random.Random(seed)
    target = km * 1000.0
    # Pick the candidate whose tightest turn is closest above rmin (inside the map): gentle loops
    # with 5+ km turns are valid but boring.
    best = None
    # Short loops can't fit big wiggles under rmin: retry with progressively gentler shapes
    # (scale 0 = a plain circle, which passes whenever its radius L/2pi >= rmin).
    for _attempt in range(6000):
        scale = [1.0, 0.6, 0.35, 0.2, 0.1, 0.0][min(5, _attempt // 1000)]
        if best is not None and _attempt % 1000 == 0:
            break
        params = [(k, scale * rng.uniform(0.05, 0.45) / (k ** 0.5), rng.uniform(0, 2 * math.pi))
                  for k in rng.sample([2, 3, 4, 5, 6], 3)]
        unit = _sample(params, 1.0, (0.0, 0.0), 1500)
        if min(math.hypot(p[0], p[1]) for p in unit) < 0.25:
            continue
        R0 = target / _length(unit)
        cand = _sample(params, R0, m['centre'], 2000)
        if max(max(abs(p[0] - m['centre'][0]), abs(p[1] - m['centre'][1])) for p in cand) > m['half']:
            continue
        r = _min_radius(cand, step=4)
        if r < rmin:
            continue
        if best is None or r < best[0]:
            best = (r, params, R0)
        if r < rmin * 1.25:
            break
    if best is None:
        raise RuntimeError('no course satisfied the constraints; lower rmin or km')
    _, params, R0 = best
    pts = _sample(params, R0, m['centre'])
    # arc-length parametrisation
    cum = [0.0]
    for i in range(len(pts)):
        cum.append(cum[-1] + math.dist(pts[i], pts[(i + 1) % len(pts)]))
    L = cum[-1]

    def at(s):
        s %= L
        lo, hi = 0, len(pts)
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if cum[mid] <= s else (lo, mid)
        f = (s - cum[lo]) / max(1e-9, cum[lo + 1] - cum[lo])
        A, B = pts[lo], pts[(lo + 1) % len(pts)]
        return A[0] + f * (B[0] - A[0]), A[1] + f * (B[1] - A[1])

    lo_a, hi_a = alt
    mid, amp = (lo_a + hi_a) / 2, (hi_a - lo_a) / 2
    waves = rng.choice([2, 3])
    phase = rng.uniform(0, 2 * math.pi)
    # cap grade: d(alt)/ds = amp * 2*pi*waves/L
    amp = min(amp, max_grade * L / (2 * math.pi * waves))
    alt_at = lambda s: mid + amp * math.sin(2 * math.pi * waves * s / L + phase)

    n = max(8, round(L / spacing))
    gates = []
    for i in range(n):
        s = L * i / n
        x, z = at(s)
        x2, z2 = at(s + 50.0)
        fx, fz = x2 - x, z2 - z
        d = math.hypot(fx, fz) or 1.0
        gates.append({'name': f'race_wp_{i + 1:03d}', 'pos': (x, alt_at(s), z), 'fwd': (fx / d, fz / d)})

    # spawns: just before gate 1 along the course, staggered sideways
    sx, sz = at(L - 3000.0)
    tx, tz = gates[0]['pos'][0], gates[0]['pos'][2]   # aim straight at gate 1
    hx, hz = tx - sx, tz - sz
    d = math.hypot(hx, hz) or 1.0
    hx, hz = hx / d, hz / d
    spawns = []
    for k in range(32):
        side = _side(k % 4)
        back = (k // 4) * 150.0
        spawns.append({'name': f'spawn{k + 1:02d}',
                       'pos': (sx - hz * side - hx * back, alt_at(L - 3000.0), sz + hx * side - hz * back),
                       'fwd': (hx, hz)})
    info = {'map': map_name, 'seed': seed, 'length_km': L / 1000, 'gates': n, 'min_turn_radius_m': _min_radius(pts),
            'alt_range_m': (mid - amp, mid + amp), 'gate_radius_m': gate, 'max_grade': amp * 2 * math.pi * waves / L}
    return gates, spawns, info


def from_points(points, spawn_back=2500.0, loop=None):
    """Gates from designer points [(x,y,z), ...] in flight order (wtlog.py gates). Each gate faces the next
    point (the last faces the first, closing the loop); spawns sit spawn_back metres before gate 1."""
    n = len(points)
    hd = lambda a, b: math.hypot(b[0] - a[0], b[2] - a[2])
    spacing = sorted(hd(points[i], points[i + 1]) for i in range(n - 1))[(n - 1) // 2]
    if loop is None:   # auto: a loop if the last gate is about one gate-gap away from the first
        loop = hd(points[-1], points[0]) <= 2.5 * spacing
    gates = []
    for i, p in enumerate(points):
        q = points[(i + 1) % n] if (loop or i < n - 1) else (2 * p[0] - points[i - 1][0], p[1], 2 * p[2] - points[i - 1][2])
        fx, fz = q[0] - p[0], q[2] - p[2]
        d = math.hypot(fx, fz) or 1.0
        gates.append({'name': f'race_wp_{i + 1:03d}', 'pos': tuple(p), 'fwd': (fx / d, fz / d)})
    p0 = points[0]
    p_prev = points[-1] if loop else (2 * p0[0] - points[1][0], p0[1], 2 * p0[2] - points[1][2])
    hx, hz = p0[0] - p_prev[0], p0[2] - p_prev[2]
    d = math.hypot(hx, hz) or 1.0
    hx, hz = hx / d, hz / d
    # straight run-up into gate 1 along the gate1->gate2 line (independent of how short the first leg is)
    if not loop:
        q = points[1]; hx, hz = q[0] - p0[0], q[2] - p0[2]; d = math.hypot(hx, hz) or 1.0; hx, hz = hx / d, hz / d
    back = spawn_back
    sx, sz = p0[0] - hx * back, p0[2] - hz * back
    spawns = []
    for k in range(32):
        side, b2 = _side(k % 4), (k // 4) * 150.0
        spawns.append({'name': f'spawn{k + 1:02d}', 'pos': (sx - hz * side - hx * b2, p0[1], sz + hx * side - hz * b2), 'fwd': (hx, hz)})
    L = sum(hd(points[i], points[i + 1]) for i in range(n - 1)) + (hd(points[-1], points[0]) if loop else 0.0)
    alts = [p[1] for p in points]
    info = {'map': None, 'seed': 0, 'length_km': L / 1000, 'gates': n, 'min_turn_radius_m': float('nan'),
            'alt_range_m': (min(alts), max(alts)), 'gate_radius_m': None, 'max_grade': float('nan'), 'loop': loop}
    return gates, spawns, info


def _side(k, step=120.0):
    """Lateral offset for spawn slot k: slot 0 is centred (the single-mission player uses it), then alternate sides."""
    return 0.0 if k == 0 else (1 if k % 2 else -1) * step * ((k + 1) // 2)


def _f(v):
    r = '%.7g' % v
    return r if ('.' in r or 'e' in r) else r + '.0'


def gate_area(g, size):
    fx, fz = g['fwd']
    rows = [(0.0, size, 0.0), (-fz * size, 0.0, fx * size), (fx * size, 0.0, fz * size), g['pos']]
    tm = 'tm:m=[' + ' '.join('[%s]' % ', '.join(_f(c) for c in r) for r in rows) + ']'
    return f'''  {g['name']}{{
    type:t="Sphere"
    {tm}
    objLayer:i=0
    props{{
    }}
  }}'''


def spawn_area(sp, size=20.0):
    hx, hz = sp['fwd']
    rows = [(hx * size, 0.0, hz * size), (0.0, size, 0.0), (-hz * size, 0.0, hx * size), sp['pos']]
    tm = 'tm:m=[' + ' '.join('[%s]' % ', '.join(_f(c) for c in r) for r in rows) + ']'
    return f'''  {sp['name']}{{
    type:t="Sphere"
    {tm}
    objLayer:i=0
    props{{
    }}
  }}'''


if __name__ == '__main__':
    g, s, info = make_course()
    print(info)
