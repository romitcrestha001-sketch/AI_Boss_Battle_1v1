# AI Boss Battle – Adaptive 1v1

This is a self-contained Pygame fighting prototype made from the three images you supplied.

## What it includes

- Player (blue Vanguard) vs Boss (red Nemesis)
- Your arena image as the stage
- 1v1 movement with arena boundaries
- Fighters cannot walk through each other
- Jump, crouch, dash, block
- 4 attacks
- Health bars
- 60-second rounds
- Best of 3 rounds
- KO / round win / match win
- Adaptive boss AI
- AI memory saved in `ai_memory.json`

## Controls

- A / D = move
- W = jump
- S = crouch
- SPACE = dash
- J = jab
- K = stronger punch
- U = kick
- I = heavy kick
- L = block
- ESC = quit
- ENTER = rematch after the match ends

## How the boss learns

The boss records how often the human player:

- attacks
- uses punches
- uses kicks
- jumps
- blocks
- advances
- retreats
- dashes

It also remembers these habits between matches in `ai_memory.json`.

Examples:

- If you attack often, the boss blocks more.
- If you jump often, the boss attempts anti-air kicks more often.
- If you retreat often, the boss chases more aggressively.
- If you block a lot, the boss uses more heavy guard-pressure attacks.
- If you repeat kicks or punches, the boss changes its defensive/counter choices.

This is a lightweight adaptive AI system, so no machine-learning package is required.

## Install

Open PowerShell in this folder and run:

```powershell
py -m pip install pygame-ce
```

If you already use a virtual environment, install pygame-ce inside that environment instead.

## Run

```powershell
py main.py
```

or:

```powershell
python main.py
```

## Reset the boss learning

Delete:

`ai_memory.json`

The game will create a fresh memory file the next time you play.

## Files

- `main.py` – complete game
- `assets/arena.png`
- `assets/player_sheet.png`
- `assets/boss_sheet.png`
- `requirements.txt`

## Sprite fix in this version

The original sprite sheets are **not an equal 5x4 grid**. Some characters extend across the
imaginary row boundaries, which caused feet/legs to be cut off.

This version pre-crops each complete pose from the transparent artwork and puts it on a
consistent transparent canvas.

The hit flash was also changed so transparent pixels stay transparent. This removes the
white rectangle that appeared when fighters hit each other.
