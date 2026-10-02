"""Generate a War Thunder time-trial race mission (.blk) for any aircraft and course.

Usage:
  python3 gen_race.py [every_n] --single <aircraft> <preset> [--norace] [--course <spec>]

  every_n            log a split time every N gates (default 5)
  --single           singleMission with a fixed player aircraft (the playable form on PC; the
                     player must own the aircraft). Without it a multiplayer-type race is written.
  --norace           no engine race mode: plain checkpoint triggers only
  --course <spec>    replace the default Phi Phi Islands course, comma-separated key=value:
                       generated loop:   map=air_denmark,seed=3[,km=90,rmin=2000,gate=300,alt=400:2500,spacing=2500]
                       designed course:  map=air_denmark,gates=gates.json,name=my_course[,loop=0|1]
                     (gates.json comes from `wtlog.py gates` after flying gen_course_designer.py)

Examples:
  python3 gen_race.py 5 --single i-16_type28 I16_type28_default
  python3 gen_race.py 2 --single mig_29_9_12 mig_29_9_12_default --course map=air_denmark,seed=7,km=20,spacing=2000
  python3 gen_race.py 3 --single mig_29_9_12 mig_29_9_12_default --course map=air_denmark,gates=gates.json,name=my_course

How it's built:
  * Reads Gaijin's Phi Phi race from your own install (mis.vromfs.bin) and flattens its import chain
      cta/ffa_race/phiphi_race/phiphi_race_v1_race_straight.blk -> cta/ffa_race/phiphi_race.blk
        -> templates/air_race_basic_template.blk
    so the engine's race mode (beginRaceMode, race_wp_NNN checkpoints in order) drives the race.
  * Single missions: one player slot with the chosen aircraft, all modifications and a fully trained
    crew (single missions don't use the player's hangar upgrades), spawned on a straight run-up to gate 1.
  * Split times: every Nth gate fires a trigger whose action the client log records as
    "TRIG unitDamage action for unit split_NN_0"; `wtlog.py splits` reads them.
  * Finish: race mode removes the finisher and a single mission would then count as failed, so a
    trigger armed by the last split completes the mission on entering the finish gate.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wtvrom import Archive

args = sys.argv[1:]
SINGLE = '--single' in args
NORACE = '--norace' in args
if SINGLE:
    i = args.index('--single'); PLANE, PRESET = args[i + 1], args[i + 2]; del args[i:i + 3]
args = [a for a in args if a != '--norace']
# --course map=air_denmark,seed=1,km=90,rmin=2000,gate=300,alt=400:2500,spacing=2500
#   replaces the Phi Phi course with a generated circuit (race_course.py) on another map.
COURSE = None
if '--course' in args:
    i = args.index('--course'); spec = args[i + 1]; del args[i:i + 2]
    COURSE = {'map': 'air_denmark', 'seed': 1, 'km': 90.0, 'rmin': 2000.0, 'gate': 300.0, 'alt': (400.0, 2500.0), 'spacing': 2500.0}
    for kv in spec.split(','):
        k, v = kv.split('=')
        COURSE[k] = tuple(map(float, v.split(':'))) if k == 'alt' else (v if k in ('map', 'gates', 'name') else (int(v) if k == 'seed' else float(v)))
EVERY_N = int(args[0]) if args else 5
# Mission names (and file names) must be plain identifiers: unit names like "mig-15" contain '-',
# which the game rejects ("invalid symbol name"), so sanitize.
_safe = lambda x: re.sub(r'[^A-Za-z0-9_]', '_', x)
OUT = (f'race_phiphi_{_safe(PLANE)}{"_norace" if NORACE else ""}.blk' if SINGLE else 'race_phiphi_trial.blk')
if COURSE:
    _stem = f"race_{COURSE['map'].replace('air_', '')}_" + (_safe(COURSE.get('name', 'custom')) if COURSE.get('gates') else f"s{COURSE['seed']}")
    OUT = f'{_stem}_{_safe(PLANE)}{"_norace" if NORACE else ""}.blk' if SINGLE else f'{_stem}.blk'
BASE = 'gamedata/missions/cta/ffa_race/'
mis = Archive('mis')
variant = mis.text(BASE + 'phiphi_race/phiphi_race_v1_race_straight.blk')
base = mis.text(BASE + 'phiphi_race.blk')
template = mis.text('gamedata/missions/templates/air_race_basic_template.blk')

SECTIONS = ['mission_settings', 'imports', 'triggers', 'mission_objectives', 'variables', 'dialogs',
            'airfields', 'effects', 'units', 'areas', 'objLayers', 'wayPoints']


def section(T, name):
    m = re.search(r'^%s\{\n(.*?)^\}' % name, T, re.S | re.M)
    return m.group(1) if m else ''


def children(body, indent=2):
    pad = ' ' * indent
    return [(m.group(1), m.group(0)) for m in
            re.finditer(r'^%s(\w+)\{\n.*?^%s\}\n?' % (pad, pad), body, re.S | re.M)]


def header_lines(body, indent=2):
    """Plain key:type=value lines directly inside a section (e.g. isCategory)."""
    return [l for l in body.split('\n') if re.match(r'^ {%d}\w+:\w+=' % indent, l)]


def merge(name, *texts, by_unit_name=False):
    """Merge one section from several files; later files win on name clashes."""
    order, blocks, head = [], {}, []
    for T in texts:
        body = section(T, name)
        for l in header_lines(body):
            if l not in head:
                head.append(l)
        for key, block in children(body):
            if by_unit_name:
                m = re.search(r'name:t="([^"]*)"', block)
                key = (key, m.group(1) if m else len(order))
            if key not in blocks:
                order.append(key)
            blocks[key] = block.rstrip('\n')
    return head, [blocks[k] for k in order]


# ---- flatten (template < base < variant)
trig_head, triggers = merge('triggers', template, base, variant)
_, units = merge('units', template, base, variant, by_unit_name=True)
_, areas = merge('areas', template, base, variant)
obj_head, objectives = merge('mission_objectives', template, base, variant)
_, variables = merge('variables', template, base, variant)

# Only the straight variant: drop the trigger that would run the inverted course.
triggers = [t for t in triggers if not t.lstrip().startswith('start_mission_inverted{')]
# missionNamePostfix gates the start trigger on the official variant suffix; remove the condition.
triggers = [re.sub(r'\n      missionNamePostfix\{.*?\n      \}', '', t, flags=re.S) for t in triggers]
# ...and the straight start trigger's action that disables the (now removed) inverted one.
triggers = [re.sub(r'\n      triggerDisable\{\n        target:t="start_mission_inverted"\n      \}', '', t) for t in triggers]

# Spawns: the template marks respawn points with team:t="Both", which the engine creates as a
# team-0 base. That only works in Gaijin's free-for-all race events; in a custom battle players are
# on team 1/2 and the respawn screen filters bases by team ("no available respawn bases").
# Split each "Both" action into an A copy and a B copy, like normal multiplayer missions.
def _split_both(t):
    def dup(m):
        blk = m.group(0)
        # Aircraft spawns need an explicit air:b=yes tag (Gaijin's race events grant it via event config).
        if 'air:b=yes' not in blk:
            blk = blk.replace('        tags{\n', '        tags{\n          air:b=yes\n', 1)
        return blk.replace('team:t="Both"', 'team:t="A"') + '\n' + blk.replace('team:t="Both"', 'team:t="B"')
    return re.sub(r'      missionMarkAsRespawnPoint\{\n(?:(?!\n      \}).)*?team:t="Both"(?:(?!\n      \}).)*?\n      \}', dup, t, flags=re.S)


triggers = [_split_both(t) for t in triggers]

if COURSE:
    import race_course
    if COURSE.get('gates'):
        # designer course: points dropped in flight (gen_course_designer.py), read by `wtlog.py gates`
        import json
        _pts = [g['pos'] for g in json.load(open(COURSE['gates']))['gates']]
        _loop = None if 'loop' not in COURSE else bool(COURSE['loop'])
        c_gates, c_spawns, COURSE_INFO = race_course.from_points(_pts, loop=_loop)
        COURSE_INFO.update(map=COURSE['map'], gate_radius_m=COURSE['gate'])
    else:
        c_gates, c_spawns, COURSE_INFO = race_course.make_course(
            COURSE['map'], COURSE['seed'], COURSE['km'], COURSE['rmin'], COURSE['gate'], COURSE['alt'], COURSE['spacing'])
    _is = lambda a, pre: re.match(r'\s*' + pre, a)
    areas = [a for a in areas if not (_is(a, r'race_wp_\d+\{') or _is(a, r'spawn\d+\{'))]
    areas += [race_course.gate_area(g, COURSE['gate']) for g in c_gates] + [race_course.spawn_area(sp) for sp in c_spawns]
    # Phi Phi scenery (background tanks) doesn't belong on another map: drop it and its trigger.
    units = [u for u in units if not u.lstrip().startswith('tankModels{')]
    triggers = [t for t in triggers if not t.lstrip().startswith('start_mission_environment{')]
    _alive = {re.search(r'name:t="([^"]*)"', u).group(1) for u in units}
    units = [re.sub(r'\n\s+squad_members:t="([^"]+)"', lambda m: m.group(0) if m.group(1) in _alive else '', u) for u in units]
    print('course:', {k: (round(v, 2) if isinstance(v, float) else v) for k, v in COURSE_INFO.items()})

# ---- course checkpoints (the engine uses race_wp_NNN in order)
gate_names = sorted(g['name'] for g in c_gates) if COURSE else sorted({k for k, _ in children(section(variant, 'areas')) if k.startswith('race_wp_')} |
                    {re.match(r'\s*(\w+)\{', a).group(1) for a in areas if a.lstrip().startswith('race_wp_')})
gates = gate_names[EVERY_N - 1::EVERY_N]
if gate_names[-1] not in gates:
    gates.append(gate_names[-1])


def pos_of(area_name):
    for a in areas:
        if a.lstrip().startswith(area_name + '{'):
            m = re.search(r'tm:m=\[.*?\[([-\d.e]+), ([-\d.e]+), ([-\d.e]+)\]\]', a)
            return tuple(map(float, m.groups()))


# ---- split markers: hidden AI aircraft parked far outside the course, one per split gate
MARKER_ORIGIN = (60000.0, 9000.0, 60000.0)
if COURSE:
    _m = race_course.MAPS[COURSE['map']]
    MARKER_ORIGIN = (_m['centre'][0] - _m['half'] + 2000.0, 3000.0, _m['centre'][1] - _m['half'] + 2000.0)
for i, g in enumerate(gates, 1):
    x, y, z = MARKER_ORIGIN[0] + i * 3000.0, MARKER_ORIGIN[1], MARKER_ORIGIN[2]
    units.append(f'''  armada{{
    name:t="split_{i:02d}"
    tm:m=[[1.0, 0.0, 0.0] [0.0, 1.0, 0.0] [0.0, 0.0, 1.0] [{x}, {y}, {z}]]
    unit_class:t="po-2"
    objLayer:i=0
    closed_waypoints:b=yes
    isShipSpline:b=no
    shipTurnRadius:r=100.0
    weapons:t=""
    bullets0:t=""
    bullets1:t=""
    bullets2:t=""
    bullets3:t=""
    bulletsCount0:i=0
    bulletsCount1:i=0
    bulletsCount2:i=0
    bulletsCount3:i=0
    crewSkillK:r=0.0
    applyAllMods:b=no
    props{{
      army:i=1
      count:i=1
      free_distance:r=70.0
      floating_distance:r=50.0
      minimum_distance_to_earth:r=500.0
      altLimit:r=12000.0
      attack_type:t="hold_fire"
      skill:i=1
      plane{{
        wing_formation:t="Diamond"
        row_distances:r=3.0
        col_distances:r=3.0
        super_formation:t="Diamond"
        super_row_distances:r=1.5
        super_col_distances:r=1.5
        ai_skill:t="NORMAL"
        task:t="FLY_WAYPOINT"
      }}
    }}
    way{{
      split_{i:02d}_wp_01{{
        type:t="normal"
        tm:m=[[1.0, 0.0, 0.0] [0.0, 1.0, 0.0] [0.0, 0.0, 1.0] [{x + 2000.0}, {y}, {z}]]
        props{{
          speed:r=300.0
          moveType:t="MOVETO_STRAIGHT"
        }}
      }}
      split_{i:02d}_wp_02{{
        type:t="normal"
        tm:m=[[1.0, 0.0, 0.0] [0.0, 1.0, 0.0] [0.0, 0.0, 1.0] [{x + 2000.0}, {y}, {z + 2000.0}]]
        props{{
          speed:r=300.0
          moveType:t="MOVETO_STRAIGHT"
        }}
      }}
    }}
  }}''')


def gate_condition(gate):
    if SINGLE:
        return f'''      unitWhenInArea{{
        math:t="3D"
        object_type:t="isAlive"
        object_marking:i=0
        check_objects:t="any"
        object_var_name:t=""
        object_var_comp_op:t="equal"
        object:t="player_wing"
        target:t="{gate}"
      }}'''
    return f'''      playersWhenInArea{{
        math:t="3D"
        players:t="isAlive"
        check_players:t="any"
        object_marking:i=0
        object_var_name:t=""
        object_var_comp_op:t="equal"
        object_var_value:i=0
        target_type:t="isAlive"
        check_period:r=0.1
        target:t="{gate}"
      }}'''


def split_trigger(i, gate, next_name):
    enable_next = f'''
      triggerEnable{{
        target:t="{next_name}"
      }}''' if next_name else ''
    return f'''  split_gate_{i:02d}{{
    is_enabled:b={'yes' if i == 1 else 'no'}
    comments:t="Destroys marker split_{i:02d} when a player reaches {gate}; the log death line is the split time."
    props{{
      actionsType:t="PERFORM_ONE_BY_ONE"
      conditionsType:t="ALL"
      enableAfterComplete:b=no
    }}
    events{{
      periodicEvent{{
        time:r=0.1
      }}
    }}
    conditions{{
{gate_condition(gate)}
    }}
    actions{{
      unitDamage{{
        part:i=0
        power:r=1.0
        useEffect:b=no
        countEffects:i=1
        delay:p2=0.0, 0.0
        offset:p3=0.0, 0.0, 0.0
        radiusOffset:p2=0.0, 0.0
        target:t="split_{i:02d}"
      }}{enable_next}
    }}
    else_actions{{
    }}
  }}'''


for i, g in enumerate(gates, 1):
    nxt = f'split_gate_{i + 1:02d}' if i < len(gates) else ('race_finished' if SINGLE else None)
    triggers.append(split_trigger(i, g, nxt))

# Single missions need an explicit win: after the finish line, race mode removes the finisher from
# the world (unit becomes "delayed"); with no missionCompleted the game then marks the mission FAILED.
# Armed only after the last split gate, so a crash mid-course can't count as finishing.
if SINGLE:
    triggers.append(f'''  race_finished{{
    is_enabled:b=no
    comments:t="Armed after the last split. Completes on entering the finish gate (the loop closes through race_wp_001), BEFORE race mode removes the finisher: the game fails the mission in the same frame as that removal, so isDelayed alone is too late. isDelayed kept as a backup."
    props{{
      actionsType:t="PERFORM_ONE_BY_ONE"
      conditionsType:t="ANY"
      enableAfterComplete:b=no
    }}
    events{{
      periodicEvent{{
        time:r=0.05
      }}
    }}
    conditions{{
      unitWhenInArea{{
        math:t="3D"
        object_type:t="isAlive"
        object_marking:i=0
        check_objects:t="any"
        object_var_name:t=""
        object_var_comp_op:t="equal"
        object:t="player_wing"
        target:t="{gate_names[0] if (COURSE_INFO.get('loop', True) if COURSE else True) else gate_names[-1]}"
      }}
      unitWhenStatus{{
        object_type:t="isDelayed"
        object_marking:i=0
        check_objects:t="any"
        target_type:t="isAlive"
        check_period:r=0.05
        object_var_name:t=""
        object_var_comp_op:t="equal"
        object_var_value:i=0
        object:t="player_wing"
      }}
    }}
    actions{{
      missionCompleted{{
        timer:b=no
        debriefingTimer:i=3
      }}
    }}
    else_actions{{
    }}
  }}''')
    if NORACE:
        # Without race mode the finisher is never removed (no isDelayed): finish on the last split gate.
        triggers[-1] = re.sub(r'\n      (unitWhenStatus|unitWhenInArea)\{.*?\n      \}', '', triggers[-1], flags=re.S)

# ---- mission settings: the variant's, retitled, solo-friendly
ms = section(variant, 'mission_settings')
ms = re.sub(r'    locName:t="[^"]*"', '    locName:t="Time Trial: Phi Phi Islands (prototype)"', ms)
ms = re.sub(r'    locDesc:t="[^"]*"',
            '    locDesc:t="Fly the Phi Phi Islands race course as fast as you can, in any aircraft you own. Shooting is disabled."', ms)
ms = re.sub(r'    postfix:t="[^"]*"\n', '', ms)
ms = ms.replace('    gt_race:b=yes\n', '    name:t="race_phiphi_trial"\n    gt_race:b=yes\n    allowEmptyTeams:b=yes\n', 1)


if SINGLE:
    import math
    sp = next(a for a in areas if a.lstrip().startswith('spawn01{'))
    m = re.search(r'tm:m=\[\[([-\d.e]+), [-\d.e]+, ([-\d.e]+)\].*?\[([-\d.e]+), ([-\d.e]+), ([-\d.e]+)\]\]', sp)
    hx, hz, x, y, z = map(float, m.groups())
    n = math.hypot(hx, hz); hx, hz = hx / n, hz / n
    player = None
    kept = []
    for u in units:
        nm = re.search(r'name:t="([^"]*)"', u).group(1)
        if re.fullmatch(r't[12]_player\d+', nm):
            if nm == 't1_player01':
                player = u
            continue
        kept.append(u)
    player = re.sub(r'name:t="t1_player01"', 'name:t="player_wing"', player)
    player = re.sub(r'tm:m=\[.*?\]\]', f'tm:m=[[{hx}, 0.0, {hz}] [0.0, 1.0, 0.0] [{-hz}, 0.0, {hx}] [{x}, {y + 150.0}, {z}]]', player, count=1)
    player = re.sub(r'unit_class:t="[^"]*"', f'unit_class:t="{PLANE}"', player, count=1)
    player = re.sub(r'weapons:t="[^"]*"', f'weapons:t="{PRESET}"', player, count=1)
    # Multiplayer slots get mods/crew from the player's hangar; in a single mission nothing fills them,
    # so the plane flew stock with an untrained crew. Standardize instead: every racer gets the same
    # fully upgraded plane and fully trained crew, so every racer flies the identical aircraft.
    player = re.sub(r'\n\s+(crewSkillK|applyAllMods):[a-z]+=[^\n]*', '', player)
    player = player.replace(f'weapons:t="{PRESET}"', f'weapons:t="{PRESET}"\n    crewSkillK:r=1.0\n    applyAllMods:b=yes', 1)
    player = re.sub(r'army:i=\d', 'army:i=1', player, count=1)
    units = [player] + kept
    # Drop references to the removed multiplayer slots from triggers (e.g. the countdown's else-branch,
    # which also restores time speed 0.01 -> 1.0, sets smoke on t1_player01/08/...). Blocks left with no
    # object are removed entirely.
    def _strip_slots(t):
        t = re.sub(r'\n\s+object:t="t[12]_player\d+"', '', t)
        return re.sub(r'\n      unitSetProperties\{\n(?:(?!\n      \}).)*?\n      \}',
                      lambda m: m.group(0) if 'object:t=' in m.group(0) else '', t, flags=re.S)
    triggers = [_strip_slots(t) for t in triggers]
    units = [re.sub(r'\n\s+squad_members:t="t[12]_player\d+"', '', u) for u in units]
    units = [u.replace('    props{\n', '    props{\n      squad_members:t="player_wing"\n', 1)
             if re.search(r'name:t="players_squad"', u) else u for u in units]
    ms = re.sub(r'  player\{.*?\n  \}', '  player{\n    army:i=1\n    wing:t="player_wing"\n  }', ms, count=1, flags=re.S)
    ms = re.sub(r'  player_teamB\{.*?\n  \}', '  player_teamB{\n    army:i=2\n  }', ms, count=1, flags=re.S)
    ms = ms.replace('    type:t="domination"', '    type:t="singleMission"', 1)
    ms = re.sub(r'    (killLimit|openDiffLevels|difficulty|country_axis|country_allies|allowEmptyTeams):[a-z0-9]+=[^\n]*\n', '', ms)
    ms = ms.replace('name:t="race_phiphi_trial"', f'name:t="{OUT[:-4]}"')
    title = f'Time Trial: Phi Phi Islands - {PLANE}' + (' (no race mode)' if NORACE else '')
    ms = re.sub(r'locName:t="[^"]*"', f'locName:t="{title}"', ms)
    if NORACE:
        ms = re.sub(r'    (gt_race|raceLaps|raceWinners|raceForceCannotShoot):[a-z0-9]+=[^\n]*\n', '', ms)
        # A true control: also remove the race machinery from triggers (race mode, the countdown's
        # time freeze/restore, and collision-ignoring), keeping only the course areas and split markers.
        _drop = r'(beginRaceMode|missionSetTimeSpeed)'
        triggers = [re.sub(r'\n      %s\{\n(?:(?!\n      \}).)*?\n      \}' % _drop, '', t, flags=re.S) for t in triggers]
        triggers = [re.sub(r'\n      unitSetProperties\{\n(?:(?!\n      \}).)*?ignoreCollisions:b=yes(?:(?!\n      \}).)*?\n      \}', '', t, flags=re.S) for t in triggers]


if COURSE:
    _mapname = COURSE['map'].replace('air_', '').replace('_', ' ').title()
    _i = COURSE_INFO
    ms = re.sub(r'level:t="[^"]*"', f'level:t="levels/{COURSE["map"]}.bin"', ms, count=1)
    _label = COURSE.get('name', 'Custom') if COURSE.get('gates') else '#%d' % COURSE['seed']
    ms = re.sub(r'locName:t="[^"]*"', lambda m: 'locName:t="Time Trial: %s %s - %s%s"' % (
        _mapname, _label, PLANE if SINGLE else 'any aircraft', ' (no race mode)' if NORACE else ''), ms, count=1)
    _turns = '' if _i['min_turn_radius_m'] != _i['min_turn_radius_m'] else ', turns no tighter than %.1f km' % (_i['min_turn_radius_m'] / 1000)
    ms = re.sub(r'locDesc:t="[^"]*"', lambda m: 'locDesc:t="A %.0f km %s over %s: %d gates%s, %d-%d m altitude. Fly it as fast as you can. Shooting is disabled."' % (
        _i['length_km'], 'circuit' if _i.get('loop', True) else 'sprint', _mapname, _i['gates'], _turns, _i['alt_range_m'][0], _i['alt_range_m'][1]), ms, count=1)
    ms = re.sub(r'name:t="race_phiphi[^"]*"', f'name:t="{OUT[:-4]}"', ms, count=1)


def block(name, head, items):
    inner = '\n'.join(head + items)
    return f'{name}{{\n{inner}\n}}\n' if inner.strip() else f'{name}{{\n}}\n'


out = ('selected_tag:t=""\nbin_dump_file:t=""\n'
       f'mission_settings{{\n{ms}}}\n'
       'imports{\n}\n'
       + block('triggers', trig_head, triggers)
       + block('mission_objectives', obj_head, objectives)
       + block('variables', [], variables)
       + 'dialogs{\n}\nairfields{\n}\neffects{\n}\n'
       + block('units', [], units)
       + block('areas', [], areas)
       + f'objLayers{{\n{section(base, "objLayers")}}}\n'
       + 'wayPoints{\n}\n')
open(OUT, 'w', newline='\r\n').write(out)
print(f'{OUT}: {len(units)} units, {len(areas)} areas, {len(triggers)} triggers, '
      f'{len(gate_names)} course gates, {len(gates)} split gates: {gates[0]}..{gates[-1]}')
