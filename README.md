# wtfox

aka: War Thunder Fox

Tools for building **time-trial race missions** for War Thunder: design a course by flying it, then generate a race for any aircraft you own.

Not affiliated with or endorsed by Gaijin Entertainment. No game files are included: every tool reads the game data from your own installation at run time.

Check out wtfox.live in the near future for more information about how these maps can be used.

## important

- Remember that clogs contain some personal data in the form of IP addresses, usernames, and certain network traffic logs. The script only runs locally, but when/if there is a website version up, clean them beforehand of any sensitive information.

## how to use it

1. **Design:** `gen_course_designer.py` writes a free-flight mission. Every time you pop flares or chaff, it drops a gate at your aircraft's position (up to 60).
2. **Read the gates:** the game client log records each gate's position. `wtlog.py gates` decodes the log locally and saves the gates, in order, to a JSON file.
3. **Generate the race:** `gen_race.py` builds a single-player race mission from those gates (or from a generated circuit, or Gaijin's Phi Phi Islands course) for the aircraft you choose. It uses the game's own race mode for the checkpoints.
4. **Fly it and read your splits:** split times are written to the client log as you pass gates. `wtlog.py splits` prints them with the total time and the result.

## requirements

- Python 3.9+
- `pip install -r requirements.txt` (`zstandard`, needed to read the game's archives)
- War Thunder installed. The tools look in the usual Steam and launcher locations. If they can't find the game, they **ask for the folder** (the one containing `aces.vromfs.bin`) and remember it in `~/.wtfox_path`. For scripts, set `WT_DIR` instead:
  - Windows: `set WT_DIR=D:\Games\WarThunder`
  - WSL / Linux: `export WT_DIR=/mnt/d/Games/WarThunder`
- Note: The CDK is not needed for this tool.

## quick start

All scripts are in `wtfox/`. Generated missions go into `<War Thunder folder>/UserMissions`, and **the game only rescans that folder when it starts**, so restart the game after adding files.

```sh
# 1. a course designer for your aircraft (internal unit name + loadout preset; see export_catalog.py)
python3 wtfox/gen_course_designer.py mig_29_9_12 mig_29_9_12_default map=air_denmark
#    -> course_designer_denmark_mig_29_9_12.blk: copy to UserMissions, fly it, pop flares to drop gates

# 2. read the gates from the newest game log
python3 wtfox/wtlog.py gates "" my_course.json

# 3. generate the race (a split every 3 gates)
python3 wtfox/gen_race.py 3 --single mig_29_9_12 mig_29_9_12_default \
    --course map=air_denmark,gates=my_course.json,name=my_course
#    -> race_denmark_my_course_mig_29_9_12.blk: copy to UserMissions and race it

# 4. your times
python3 wtfox/wtlog.py splits
```

A generated circuit instead of a designed one: `--course map=air_denmark,seed=7,km=20,spacing=2000` (see `gen_race.py` for all options).

## Tools

| Script                   | What it does                                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `gen_course_designer.py` | Free-flight mission that drops a gate at your position on each flare/chaff press                                                          |
| `gen_race.py`            | Race mission generator: designed courses, generated circuits, or the Phi Phi Islands course                                               |
| `race_course.py`         | Course geometry: smooth closed circuits with a minimum turn radius; gates from designed points (loop or sprint is detected automatically) |
| `wtlog.py`               | Decodes client logs (`.game_logs/*.clog`) and prints race splits and designed gates                                                       |
| `wtvrom.py`              | Reads the game's `.vromfs.bin` archives and converts binary BLK files to text                                                             |
| `export_catalog.py`      | Exports the aircraft list from your install: unit names, in-game names, BR, tech tree/premium/event, loadouts                             |

## Things worth knowing

- **You can only fly aircraft you own.** Missions name aircraft by internal unit name, which can differ from the in-game name (`mig-15` is shown as _MiG-15bis_). `export_catalog.py` maps one to the other.
- **Single missions don't use your hangar upgrades or crew,** so race missions give every racer the same aircraft: all modifications, fully trained crew.
- **Mission names must be plain identifiers** (letters, digits, underscores). The generators sanitise them; a `-` makes the game reject the mission.
- **Client logs contain personal data** (account name and ID, IP addresses, network traffic). The tools read them locally and only print the race lines. Don't share raw `.clog` files.
- Only `air_denmark` is set up for generated and designed courses so far (it's flat, so low courses are safe). Other maps need a known-safe area added to `MAPS` in `race_course.py`.

## License

MIT. See [LICENSE](LICENSE).
