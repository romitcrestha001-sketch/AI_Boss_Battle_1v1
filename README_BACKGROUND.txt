# Animated Background Update

This package adds the 10 uploaded arena frames as a moving Pygame background.

## Copy into your project

1. Replace your current `main.py` with the included `main.py`.
2. Copy `assets/background_frames/` into your existing `assets/` folder.
3. Keep your existing `assets/arena.png`, `menu_screen.png`, `player_frames/`, and `boss_frames/`.
4. Run the game normally.

The animation uses a ping-pong loop and a light cross-fade so frame 10 does not jump harshly back to frame 1.

To change speed, edit:

```python
BACKGROUND_FPS = 7.5
```

For lower GPU usage, edit:

```python
BACKGROUND_CROSSFADE = False
```
