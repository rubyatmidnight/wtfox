#!/usr/bin/env python3
"""Export the aircraft catalogue the web generator needs (rerun after big game patches).

Usage: export_catalog.py [out.json]   (default: catalog.json)

One entry per ownable aircraft (in char config/wpcost.blk with a flight model in aces):
  id            internal name -> mission unit_class (e.g. "mig-15", which the game shows as MiG-15bis)
  name          in-game display name (lang units.csv "<id>_shop", English, icon glyphs stripped)
  country, rank, br {ab, rb, sb}  BR = 1.0 + economicRank*/3 (rounded to 0.1)
  source        "tech_tree" (researchable: value > 0 and no gold/gift/event), "premium" (costGold),
                "event" (gift/event), or "other"
  class         wpcost unitClass (exp_fighter, exp_bomber, exp_assault, exp_helicopter, ...)
  presets       loadout preset names from the flight model; presets[0] is the default
"""
import csv, io, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wtvrom import Archive

OUT = sys.argv[1] if len(sys.argv) > 1 else 'catalog.json'
char, aces, lang = Archive('char'), Archive('aces'), Archive('lang')

wp = char.text('config/wpcost.blk')
fm_files = {n[len('gamedata/flightmodels/'):-4].lower(): n for n in aces.files
            if n.startswith('gamedata/flightmodels/') and n.count('/') == 2 and n.endswith('.blk')}

names = {}
rows = csv.reader(io.StringIO(lang.text('lang/units.csv')), delimiter=';')
header = next(rows)
for r in rows:
    if r and r[0].endswith('_shop') and len(r) > 1:
        names[r[0][:-5]] = re.sub(r'^[^\w(]+', '', r[1].replace('\xa0', ' ')).strip()   # drop icon glyphs, normalise nbsp


def br(rank):
    return None if rank is None else round(1.0 + int(rank) / 3.0 + 1e-9, 1)


catalog = []
for m in re.finditer(r'^(\S+)\{\n(.*?)^\}', wp, re.S | re.M):
    uid, body = m.group(1), m.group(2)
    if uid.lower() not in fm_files:
        continue
    g = lambda k: (re.search(r'^  %s:\w+=("?)([^"\n]*)\1' % k, body, re.M) or [None, None, None])[2]
    gold, gift, event, value = g('costGold'), g('gift'), g('event'), g('value')
    if gold:
        source = 'premium'
    elif gift or event:
        source = 'event'
    elif value and int(value) > 0:
        source = 'tech_tree'
    else:
        source = 'other'
    try:
        t = aces.text(fm_files[uid.lower()])
        pm = re.search(r'\nweapon_presets\{(.*?)\n\}', t, re.S)
        presets = re.findall(r'name:t="([^"]+)"', pm.group(1)) if pm else []
    except Exception:
        presets = []
    catalog.append({
        'id': uid, 'name': names.get(uid, uid), 'country': (g('country') or '').replace('country_', ''),
        'rank': int(g('rank') or 0),
        'br': {'ab': br(g('economicRankArcade')), 'rb': br(g('economicRankHistorical')), 'sb': br(g('economicRankSimulation'))},
        'source': source, 'class': g('unitClass') or '', 'presets': presets,
    })

catalog.sort(key=lambda a: (a['br']['rb'] or 0, a['name']))
json.dump({'game_version_note': 'exported from local game files', 'aircraft': catalog}, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
from collections import Counter
print(f'{len(catalog)} aircraft -> {OUT}; by source {dict(Counter(a["source"] for a in catalog))}; '
      f'by class {dict(Counter(a["class"] for a in catalog).most_common(6))}')
