"""Course designer: free flight where each flare/chaff press drops a gate at your position.

Usage: python3 gen_course_designer.py <aircraft> <preset> [map=air_denmark] [flags=60]
  -> writes course_designer_<map>_<aircraft>.blk in the cwd; copy to <War Thunder folder>/UserMissions.

How it works (all logged by the client, read back with `wtlog.py gates`):
  * flags flag_001..NNN are hidden AI units, put to sleep at mission start.
  * Trigger designer_gate_NNN waits for a countermeasure shortcut press, then
    unitRespawn{ object: flag_NNN, target: player_wing } -> the log records
    "UnitRespawn received ... pos:(x,y,z)" (and a DBGSPAWN line with the spawn tm/heading),
    puts the flag back to sleep, shows a hint, and arms the next gate trigger.
  * Unlimited ammo/fuel, no enemies.
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import race_course

args = [a for a in sys.argv[1:] if '=' not in a]
opts = dict(a.split('=', 1) for a in sys.argv[1:] if '=' in a)
PLANE, PRESET = args[0], args[1]
MAP = opts.get('map', 'air_denmark')
N = int(opts.get('flags', 60))
SAFE = lambda x: re.sub(r'[^A-Za-z0-9_]', '_', x)
OUT = f'course_designer_{SAFE(MAP.replace("air_", ""))}_{SAFE(PLANE)}.blk'
cx, cz = race_course.MAPS[MAP]['centre']
START = (cx, 1500.0, cz)
SHORTCUTS = ['ID_FLARES', 'ID_COUNTERMEASURES_FLARES', 'ID_COUNTERMEASURES_CHAFF']


def f(v):
    r = '%.7g' % v
    return r if ('.' in r or 'e' in r) else r + '.0'


def tm(p, scale=1.0):
    return f'tm:m=[[{f(scale)}, 0.0, 0.0] [0.0, {f(scale)}, 0.0] [0.0, 0.0, {f(scale)}] [{f(p[0])}, {f(p[1])}, {f(p[2])}]]'


def armada(name, cls, weapons, army, pos, player=False):
    return f'''  armada{{
    name:t="{name}"
    {tm(pos)}
    unit_class:t="{cls}"
    objLayer:i=1
    closed_waypoints:b=no
    isShipSpline:b=no
    shipTurnRadius:r=100.0
    weapons:t="{weapons}"
    bullets0:t=""
    bullets1:t=""
    bullets2:t=""
    bullets3:t=""
    bulletsCount0:i=0
    bulletsCount1:i=0
    bulletsCount2:i=0
    bulletsCount3:i=0
    crewSkillK:r={'1.0' if player else '0.0'}
    applyAllMods:b={'yes' if player else 'no'}
    props{{
      army:i={army}
      count:i=1
      free_distance:r=70.0
      floating_distance:r=50.0
      minimum_distance_to_earth:r=500.0
      altLimit:r=12000.0
      attack_type:t="{'fire_at_will' if player else 'hold_fire'}"
      skill:i=4
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
    }}
  }}'''


units = [armada('player_wing', PLANE, PRESET, 1, START, player=True)]
for i in range(1, N + 1):
    # parked high above the far corner of the map until respawned at the player
    units.append(armada(f'flag_{i:03d}', 'po-2', '', 1, (cx - 35000.0 + 300.0 * i, 4000.0, cz - 35000.0)))


def trig(name, enabled, events, conds, acts, cond_type='ALL'):
    return f'''  {name}{{
    is_enabled:b={'yes' if enabled else 'no'}
    comments:t=""
    props{{
      actionsType:t="PERFORM_ONE_BY_ONE"
      conditionsType:t="{cond_type}"
      enableAfterComplete:b=no
    }}
    events{{
{events}
    }}
    conditions{{
{conds}
    }}
    actions{{
{acts}
    }}
    else_actions{{
    }}
  }}'''


sleep_all = '\n'.join(f'        target:t="flag_{i:03d}"' for i in range(1, N + 1))
triggers = [trig('designer_start', True, '      initMission{\n      }', '', f'''      unitPutToSleep{{
{sleep_all}
      }}
      wait{{
        time:r=2.0
      }}
      playHint{{
        hintType:t="custom"
        name:t="Course designer: pop flares or chaff to drop a gate at your position"
        action:t="show"
        shouldBlink:b=no
        shouldFadeOut:b=yes
        time:r=8.0
      }}''')]

press = '\n'.join(f'''      playerShortcutPressed{{
        control:t="{sc}"
      }}''' for sc in SHORTCUTS)
for i in range(1, N + 1):
    nxt = f'''
      triggerEnable{{
        target:t="designer_gate_{i + 1:03d}"
      }}''' if i < N else ''
    triggers.append(trig(f'designer_gate_{i:03d}', i == 1, '''      periodicEvent{
        time:r=0.05
      }''', press, f'''      unitRespawn{{
        delay:r=0.0
        offset:p3=0.0, 0.0, 0.0
        object:t="flag_{i:03d}"
        object_type:t="isDelayed"
        target:t="player_wing"
      }}
      wait{{
        time:r=0.3
      }}
      unitPutToSleep{{
        target:t="flag_{i:03d}"
      }}
      playHint{{
        hintType:t="custom"
        name:t="Gate {i:02d} placed"
        action:t="show"
        shouldBlink:b=no
        shouldFadeOut:b=yes
        time:r=2.0
      }}
      wait{{
        time:r=1.0
      }}{nxt}''', cond_type='ANY'))

mapname = MAP.replace('air_', '').replace('_', ' ').title()
out = f'''selected_tag:t=""
bin_dump_file:t=""
mission_settings{{
  player{{
    army:i=1
    wing:t="player_wing"
  }}
  player_teamB{{
    army:i=2
  }}
  mission{{
    name:t="{OUT[:-4]}"
    locName:t="Course Designer: {mapname} - {PLANE}"
    locDesc:t="Free flight. Pop flares or chaff to drop the next gate at your position (up to {N}). Gates are read back from the game log."
    level:t="levels/{MAP}.bin"
    type:t="singleMission"
    environment:t="Day"
    weather:t="clear"
    restoreType:t="attempts"
    optionalTakeOff:b=no
    isLimitedFuel:b=no
    isLimitedAmmo:b=no
  }}
}}
imports{{
}}
triggers{{
  isCategory:b=yes
  is_enabled:b=yes
{chr(10).join(triggers)}
}}
mission_objectives{{
  isCategory:b=yes
  is_enabled:b=yes
}}
variables{{
}}
dialogs{{
}}
airfields{{
}}
effects{{
}}
units{{
{chr(10).join(units)}
}}
areas{{
}}
objLayers{{
  layer{{
    enabled:b=yes
  }}
  layer{{
    enabled:b=yes
  }}
}}
wayPoints{{
}}
'''
open(OUT, 'w', newline='\r\n').write(out)
print(OUT, f'{N} flags, shortcuts: {", ".join(SHORTCUTS)}')
