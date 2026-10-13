import json
import math
import random
from array import array
from collections import Counter, deque
from pathlib import Path

import pygame

try:
    import cv2
except ImportError:
    cv2 = None

# ------------------------------------------------------------
# AI BOSS BATTLE - 1v1 adaptive fighting prototype
# Uses the supplied arena and sprite sheets.
# ------------------------------------------------------------

WIDTH, HEIGHT = 1280, 720
FPS = 60
GROUND_Y = 625
ARENA_LEFT = 90
ARENA_RIGHT = WIDTH - 90
ROUND_TIME = 60.0
ROUNDS_TO_WIN = 2

# Arena background.
# Preferred: assets/background_20s.mp4 (smooth 20-second looping video).
# Fallback: the supplied PNG background frames if the video is missing or OpenCV
# is not installed.
BACKGROUND_VIDEO = "background_20s.mp4"
BACKGROUND_FRAME_FPS = 60.0  # Play PNG background animation at 60 frames per second
BACKGROUND_CROSSFADE = True
MENU_FRAME_FPS = 23.0  # Speed of the original menu frames
MENU_LOOP_BLEND_FRAMES = 18  # Smoothly join about 0.8 seconds of the ending and start
MENU_MUSIC_FILE = "gapless_slow.wav"
MENU_MUSIC_VOLUME = 0.45
MENU_MUSIC_FADE_MS = 450

ANNOUNCER_VOLUME = 0.90
ANNOUNCER_DIR = "sounds/announcer/core"

# Startup/loading animation rendered from rhs-studio-intro.html
LOADING_INTRO_FRAMES = "loading_frames"
LOADING_INTRO_FPS = 12.0
LOADING_INTRO_SOUND = "rhs_intro_sound.ogg"
LOADING_INTRO_SOUND_VOLUME = 1.0

BASE_DIR = Path(__file__).resolve().parent
ASSET_DIR = BASE_DIR / "assets"
AI_MEMORY_FILE = BASE_DIR / "ai_memory.json"

# Pre-cropped frames are placed on a consistent transparent canvas.
# This prevents legs/arms from being cut by equal-grid slicing.
DRAW_W = 420
DRAW_H = 370

# Frame map for the new 20-pose player/boss sprite sets.
# 00 READY, 01-04 WALK, 05 CROUCH, 06-08 JUMP, 09 BLOCK,
# 10 JAB, 11 CROSS, 12 LOW KICK, 13 HIGH KICK, 14 HIT,
# 15 FALL/DOWN, 16 GET UP, 17 VICTORY. Frames 18-19 are currently unused.
IDLE = 0
READY = 0
WALK_A = 1
WALK_B = 3
WALK_FRAMES = (1, 2, 3, 4)

# Movement tuning:
# Keep foot animation synchronized with actual distance traveled.
WALK_SPEED = 165.0
WALK_ACCEL = 780.0
WALK_BRAKE = 980.0
WALK_STRIDE_PX = 68.0

# New blue-player animation timings.
PLAYER_DODGE_DURATION = 0.42
PLAYER_DODGE_COOLDOWN = 0.65
PLAYER_DODGE_SPEED = 350.0
PLAYER_GETUP_DURATION = 0.55
PLAYER_KNOCKDOWN_HOLD = 0.42
PLAYER_HIT_ANIM_DURATION = 0.32

CROUCH = 5
JUMP_RISE = 6
JUMP = 7
JUMP_FALL = 8
JUMP_ATTACK = 8
BLOCK = 9
PUNCH_A = 10
PUNCH_B = 11
KICK_A = 12
KICK_B = 13
HEAVY = 13
HIT = 14
FALL = 15
DOWN = 15
GETUP = 16
VICTORY = 17

ATTACKS = {
    "jab": {
        "damage": 8,
        "range": 86,
        "duration": 0.36,
        "active_start": 0.11,
        "active_end": 0.22,
        "frame": PUNCH_A,
        "knockback": 25,
        "guard_damage": 2,
    },
    "cross": {
        "damage": 11,
        "range": 98,
        "duration": 0.46,
        "active_start": 0.15,
        "active_end": 0.29,
        "frame": PUNCH_B,
        "knockback": 35,
        "guard_damage": 3,
    },
    "kick": {
        "damage": 14,
        "range": 118,
        "duration": 0.58,
        "active_start": 0.18,
        "active_end": 0.36,
        "frame": KICK_A,
        "knockback": 48,
        "guard_damage": 4,
    },
    "heavy_kick": {
        "damage": 18,
        "range": 135,
        "duration": 0.72,
        "active_start": 0.24,
        "active_end": 0.45,
        "frame": KICK_B,
        "knockback": 70,
        "guard_damage": 7,
    },
}

BG = (18, 20, 26)
WHITE = (245, 245, 245)
GREY = (170, 175, 185)
RED = (215, 55, 55)
BLUE = (65, 150, 245)
GOLD = (238, 190, 80)
GREEN = (70, 210, 110)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def load_background_frames(folder, fallback_path, size):
    """Load all numbered background frames automatically."""
    frames = []
    paths = []

    if folder.exists():
        # Background animation files:
        # frame_000001.png, frame_000002.png, ... frame_000601.png
        # The six-digit number keeps the sequence in the correct order.
        def bg_number(path):
            try:
                return int(path.stem.split("_")[-1])
            except ValueError:
                return 10**9

        paths = sorted(folder.glob("frame_*.png"), key=bg_number)

        for path in paths:
            image = pygame.image.load(path).convert()
            image = pygame.transform.smoothscale(image, size)
            frames.append(image)

    if not frames:
        image = pygame.image.load(fallback_path).convert()
        frames = [pygame.transform.smoothscale(image, size)]
        print("No animated PNG frames found; using arena.png.")
    else:
        print(f"Loaded {len(frames)} background frame(s).")

    # Keep the frames in their original forward order.
    # Do not ping-pong a video-extracted sequence.
    return frames


def draw_animated_background(surf, frames, anim_t):
    """Play PNG background frames forward at 60 FPS and soften the loop seam."""
    if len(frames) == 1:
        surf.blit(frames[0], (0, 0))
        return

    # Forward-only playback: 1 -> 2 -> ... -> 601 -> 1.
    # During the final 30 frames (~0.5 sec), gradually blend in the beginning
    # of the sequence. This hides the hard 601 -> 1 cut without reversing motion.
    frame_pos = (anim_t * BACKGROUND_FRAME_FPS) % len(frames)
    frame_index = int(frame_pos)
    subframe_blend = frame_pos - frame_index

    surf.blit(frames[frame_index], (0, 0))

    # Normal tiny interpolation between neighboring forward frames.
    next_index = (frame_index + 1) % len(frames)
    if BACKGROUND_CROSSFADE and subframe_blend > 0.001:
        nxt = frames[next_index]
        nxt.set_alpha(int(255 * subframe_blend))
        surf.blit(nxt, (0, 0))
        nxt.set_alpha(None)

    # Seam crossfade: blend the last 30 frames into matching early frames.
    seam_frames = min(30, max(2, len(frames) // 10))
    seam_start = len(frames) - seam_frames
    if BACKGROUND_CROSSFADE and frame_index >= seam_start:
        seam_pos = (frame_pos - seam_start) / seam_frames
        seam_pos = max(0.0, min(1.0, seam_pos))
        # Smoothstep makes the transition less noticeable at both ends.
        seam_alpha = seam_pos * seam_pos * (3.0 - 2.0 * seam_pos)
        early_pos = (frame_pos - seam_start) % seam_frames
        early_index = int(early_pos) % len(frames)
        early_next = (early_index + 1) % len(frames)
        early_blend = early_pos - int(early_pos)

        early = frames[early_index].copy()
        if early_blend > 0.001:
            e2 = frames[early_next]
            e2.set_alpha(int(255 * early_blend))
            early.blit(e2, (0, 0))
            e2.set_alpha(None)
        early.set_alpha(int(255 * seam_alpha))
        surf.blit(early, (0, 0))





class VideoBackground:
    """Stream a looping MP4 as a pygame background.

    The video is decoded at its own FPS (normally 30 FPS), while the game can
    continue running at 60 FPS. Only the newest decoded video frame is converted
    to a pygame Surface, which keeps CPU usage much lower than decoding on every
    game frame.
    """

    def __init__(self, path, size):
        self.path = Path(path)
        self.size = tuple(size)
        self.cap = None
        self.surface = None
        self.available = False
        self.accumulator = 0.0
        self.video_fps = 30.0
        self.frame_time = 1.0 / self.video_fps

        if cv2 is None:
            print("Background video disabled: install OpenCV with 'pip install opencv-python'.")
            return

        if not self.path.exists():
            print(f"Background video not found: {self.path}")
            print("Using PNG background frames instead.")
            return

        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            print(f"Could not open background video: {self.path}")
            self.cap.release()
            self.cap = None
            return

        fps = float(self.cap.get(cv2.CAP_PROP_FPS))
        if math.isfinite(fps) and fps > 1.0:
            self.video_fps = fps
        self.frame_time = 1.0 / self.video_fps

        ok, frame = self.cap.read()
        if not ok:
            print(f"Could not read the first frame of: {self.path}")
            self.close()
            return

        self.surface = self._to_surface(frame)
        self.available = True
        print(
            f"Video background loaded: {self.path.name} "
            f"({self.video_fps:.1f} FPS, looping)"
        )

    def _to_surface(self, frame):
        """Convert an OpenCV BGR frame into a pygame Surface."""
        target_w, target_h = self.size
        h, w = frame.shape[:2]
        if (w, h) != (target_w, target_h):
            interpolation = cv2.INTER_AREA if w >= target_w and h >= target_h else cv2.INTER_LINEAR
            frame = cv2.resize(frame, self.size, interpolation=interpolation)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # .convert() makes pygame own its copy of the pixel data.
        return pygame.image.frombuffer(rgb.tobytes(), self.size, "RGB").convert()

    def update(self, dt):
        if not self.available or self.cap is None:
            return

        # Cap a very large delay so returning from a debugger/window drag does
        # not make us decode hundreds of frames at once.
        self.accumulator += min(dt, 0.25)
        if self.accumulator < self.frame_time:
            return

        frames_to_advance = int(self.accumulator / self.frame_time)
        self.accumulator -= frames_to_advance * self.frame_time
        frames_to_advance = min(frames_to_advance, 6)

        newest = None
        for _ in range(frames_to_advance):
            ok, frame = self.cap.read()

            if not ok:
                # Seamless loop: jump back to the first frame and continue.
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
                if not ok:
                    return

            newest = frame

        if newest is not None:
            self.surface = self._to_surface(newest)

    def draw(self, surf):
        if self.surface is not None:
            surf.blit(self.surface, (0, 0))

    def close(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = None
        self.available = False


def load_frames(folder):
    """Load the 20 pre-cropped semantic animation frames."""
    frames = []
    for i in range(20):
        path = folder / f"frame_{i:02d}.png"
        frames.append(pygame.image.load(path).convert_alpha())
    return frames


def load_action_set(folder):
    """Load the new blue-player action folders extracted from the sprite sheet."""
    actions = {}
    fps = {}

    meta_path = folder / "animations.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fps = meta.get("fps", {})
        except Exception:
            fps = {}

    action_names = (
        "idle",
        "walk",
        "dash",
        "jump",
        "guard",
        "hit",
        "punch_combo",
        "kick_combo",
        "dodge_roll",
        "get_up",
        "ko_down",
    )

    for action in action_names:
        action_dir = folder / action
        paths = sorted(action_dir.glob("frame_*.png"))
        if paths:
            actions[action] = [
                pygame.image.load(path).convert_alpha()
                for path in paths
            ]

    if actions:
        print(
            "Blue player action set loaded: "
            + ", ".join(f"{name}={len(frames)}" for name, frames in actions.items())
        )

    return actions, fps


class BehaviorMemory:
    """Simple persistent player-behavior model.

    It does not use a large ML library. It learns action frequencies,
    recent habits, preferred range, aggression, jumping, blocking and retreating.
    The boss uses those learned tendencies to alter its decisions.
    """

    def __init__(self):
        self.counts = Counter()
        self.recent = deque(maxlen=24)
        self.distance_sum = 0.0
        self.distance_samples = 0
        self.session_actions = 0
        self.load()

    def load(self):
        if not AI_MEMORY_FILE.exists():
            return
        try:
            data = json.loads(AI_MEMORY_FILE.read_text(encoding="utf-8"))
            self.counts.update(data.get("counts", {}))
            self.distance_sum = float(data.get("distance_sum", 0.0))
            self.distance_samples = int(data.get("distance_samples", 0))
        except Exception:
            pass

    def save(self):
        data = {
            "counts": dict(self.counts),
            "distance_sum": round(self.distance_sum, 2),
            "distance_samples": self.distance_samples,
        }
        try:
            AI_MEMORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def record(self, action):
        self.counts[action] += 1
        self.recent.append(action)
        self.session_actions += 1

    def sample_distance(self, d):
        self.distance_sum += float(d)
        self.distance_samples += 1

    def ratio(self, action, recent=False):
        source = Counter(self.recent) if recent else self.counts
        total = sum(source.values())
        return source.get(action, 0) / total if total else 0.0

    def group_ratio(self, names, recent=False):
        source = Counter(self.recent) if recent else self.counts
        total = sum(source.values())
        if total == 0:
            return 0.0
        return sum(source.get(n, 0) for n in names) / total

    def average_distance(self):
        if not self.distance_samples:
            return 200.0
        return self.distance_sum / self.distance_samples

    def summary(self):
        attack = self.group_ratio(["jab", "cross", "kick", "heavy_kick"])
        kick = self.group_ratio(["kick", "heavy_kick"])
        block = self.ratio("block")
        jump = self.ratio("jump")
        retreat = self.ratio("retreat")
        return attack, kick, block, jump, retreat


class Fighter:
    def __init__(self, name, x, frames, is_player, action_set=None, action_fps=None):
        self.name = name
        self.x = float(x)
        self.y = float(GROUND_Y)
        self.vx = 0.0
        self.vy = 0.0
        self.frames = frames
        self.is_player = is_player
        self.action_set = action_set or {}
        self.action_fps = action_fps or {}

        self.health = 100
        self.max_health = 100
        self.facing = 1 if is_player else -1
        self.on_ground = True
        self.crouching = False
        self.blocking = False
        self.attack_name = None
        self.attack_t = 0.0
        self.attack_hit = False
        self.hitstun = 0.0
        self.hit_anim_t = 0.0
        self.flash_t = 0.0
        self.walk_anim = 0.0
        self.motion_t = 0.0
        self.jump_anim_t = 0.0
        self.walk_vx = 0.0
        self.landing_t = 0.0
        self.pose = IDLE
        self.move_dir = 0
        self.dash_t = 0.0
        self.dash_duration = 0.16
        self.dash_cooldown = 0.0
        self.knocked_down = False
        self.down_t = 0.0
        self.getup_t = 0.0
        self.ko_anim_t = 0.0
        self.dodge_t = 0.0
        self.dodge_dir = 0
        self.dodge_cooldown = 0.0
        self.attack_serial = 0
        self.dash_serial = 0

    @property
    def attacking(self):
        return self.attack_name is not None

    @property
    def dodging(self):
        return self.dodge_t > 0.0

    def body_rect(self):
        h = 138 if self.crouching else 222
        w = 96 if self.crouching else 104
        bottom = int(self.y)
        return pygame.Rect(int(self.x - w / 2), bottom - h, w, h)

    def reset(self, x):
        self.x = float(x)
        self.y = float(GROUND_Y)
        self.vx = self.vy = 0.0
        self.health = self.max_health
        self.on_ground = True
        self.crouching = False
        self.blocking = False
        self.attack_name = None
        self.attack_t = 0.0
        self.attack_hit = False
        self.hitstun = 0.0
        self.hit_anim_t = 0.0
        self.pose = IDLE
        self.move_dir = 0
        self.walk_anim = 0.0
        self.motion_t = 0.0
        self.jump_anim_t = 0.0
        self.walk_vx = 0.0
        self.landing_t = 0.0
        self.dash_t = 0.0
        self.dash_cooldown = 0.0
        self.knocked_down = False
        self.down_t = 0.0
        self.getup_t = 0.0
        self.ko_anim_t = 0.0
        self.dodge_t = 0.0
        self.dodge_dir = 0
        self.dodge_cooldown = 0.0

    def can_act(self):
        return (
            self.hitstun <= 0
            and not self.knocked_down
            and self.getup_t <= 0
            and self.dodge_t <= 0
        )

    def start_attack(self, name):
        if not self.can_act() or self.attacking or self.blocking:
            return False
        self.attack_name = name
        self.attack_t = 0.0
        self.attack_hit = False
        self.crouching = False
        self.walk_vx *= 0.35
        self.attack_serial += 1
        return True

    def jump(self):
        if self.can_act() and self.on_ground and not self.attacking and not self.blocking:
            self.vy = -700
            self.on_ground = False
            self.crouching = False
            self.jump_anim_t = 0.0
            return True
        return False

    def dash(self, direction):
        if (
            self.can_act()
            and self.on_ground
            and not self.attacking
            and not self.blocking
            and self.dash_cooldown <= 0
        ):
            self.dash_t = self.dash_duration
            self.dash_cooldown = 0.58
            self.vx = direction * 560
            self.walk_vx = 0.0
            self.dash_serial += 1
            return True
        return False

    def dodge(self, direction):
        """Blue-player dodge/roll. Returns True when the move begins."""
        if (
            not self.action_set
            or not self.can_act()
            or not self.on_ground
            or self.attacking
            or self.blocking
            or self.dodge_cooldown > 0
        ):
            return False

        if direction == 0:
            direction = -self.facing

        self.dodge_dir = 1 if direction > 0 else -1
        self.dodge_t = PLAYER_DODGE_DURATION
        self.dodge_cooldown = PLAYER_DODGE_COOLDOWN
        self.walk_vx = 0.0
        self.vx = 0.0
        return True

    def take_hit(self, damage, knockback, attacker_facing, guard_damage=0):
        # Dodge/roll has a short invulnerable window for the blue player.
        if self.action_set and self.dodge_t > 0:
            return

        if self.blocking and self.on_ground:
            damage = max(1, int(damage * 0.23)) + guard_damage
            knockback *= 0.28
            self.hitstun = max(self.hitstun, 0.10)
        else:
            self.hitstun = max(self.hitstun, 0.20 + damage * 0.006)

        self.hit_anim_t = 0.0
        self.health = max(0, self.health - damage)
        self.x += attacker_facing * knockback
        self.flash_t = 0.10

        if self.health <= 0:
            self.knocked_down = True
            self.down_t = 999.0
            self.ko_anim_t = 0.0
            self.pose = DOWN
        elif self.action_set and damage >= 17 and not self.blocking:
            # Use the sheet's KO/down -> get-up sequence for heavy non-KO hits.
            self.knocked_down = True
            self.down_t = PLAYER_KNOCKDOWN_HOLD
            self.ko_anim_t = 0.0
            self.pose = FALL
        elif damage >= 17 and not self.blocking:
            self.pose = FALL
        else:
            self.pose = HIT

    def _action_frame(self, action, progress=None, loop_time=None):
        frames = self.action_set.get(action)
        if not frames:
            return None

        if progress is not None:
            p = clamp(progress, 0.0, 0.999999)
            index = min(len(frames) - 1, int(p * len(frames)))
        else:
            fps = float(self.action_fps.get(action, 8))
            t = self.motion_t if loop_time is None else loop_time
            index = int(t * fps) % len(frames)

        return frames[index]

    def _sheet_frame(self):
        """Return the new-sheet frame for the blue player, or None for old sprites."""
        if not self.action_set:
            return None

        # KO / down has highest priority and ends on the final down frame.
        if self.health <= 0 and self.knocked_down:
            frames = self.action_set.get("ko_down", [])
            if frames:
                fps = float(self.action_fps.get("ko_down", 8))
                index = min(len(frames) - 1, int(self.ko_anim_t * fps))
                return frames[index]

        # Temporary knockdown before getting up.
        if self.knocked_down:
            frames = self.action_set.get("ko_down", [])
            if frames:
                fps = float(self.action_fps.get("ko_down", 8))
                index = min(len(frames) - 1, int(self.ko_anim_t * fps))
                return frames[index]

        if self.getup_t > 0:
            progress = 1.0 - self.getup_t / PLAYER_GETUP_DURATION
            return self._action_frame("get_up", progress=progress)

        if self.dodge_t > 0:
            progress = 1.0 - self.dodge_t / PLAYER_DODGE_DURATION
            return self._action_frame("dodge_roll", progress=progress)

        if self.attacking:
            duration = max(0.001, ATTACKS[self.attack_name]["duration"])
            progress = self.attack_t / duration
            action = (
                "punch_combo"
                if self.attack_name in ("jab", "cross")
                else "kick_combo"
            )
            return self._action_frame(action, progress=progress)

        if self.hitstun > 0:
            progress = self.hit_anim_t / PLAYER_HIT_ANIM_DURATION
            return self._action_frame("hit", progress=progress)

        if not self.on_ground:
            # The seven jump frames play once across most of the jump arc.
            progress = min(0.999, self.jump_anim_t / 0.78)
            return self._action_frame("jump", progress=progress)

        if self.blocking:
            return self._action_frame("guard", loop_time=self.motion_t)

        if self.dash_t > 0:
            progress = 1.0 - self.dash_t / self.dash_duration
            return self._action_frame("dash", progress=progress)

        if abs(self.walk_vx) > 8:
            frames = self.action_set.get("walk", [])
            if frames:
                return frames[int(self.walk_anim) % len(frames)]

        return self._action_frame("idle", loop_time=self.motion_t)

    def update(self, dt):
        self.motion_t += dt
        self.flash_t = max(0.0, self.flash_t - dt)
        self.dash_cooldown = max(0.0, self.dash_cooldown - dt)
        self.dodge_cooldown = max(0.0, self.dodge_cooldown - dt)
        self.landing_t = max(0.0, self.landing_t - dt)

        if self.hitstun > 0:
            self.hitstun = max(0.0, self.hitstun - dt)
            self.hit_anim_t += dt

        # Permanent KO or temporary heavy knockdown.
        if self.knocked_down:
            self.ko_anim_t += dt
            self.vx *= 0.84
            self.walk_vx *= 0.75
            self.x += self.vx * dt
            self.x = clamp(self.x, ARENA_LEFT, ARENA_RIGHT)

            if self.health > 0 and self.action_set:
                self.down_t -= dt
                if self.down_t <= 0:
                    self.knocked_down = False
                    self.getup_t = PLAYER_GETUP_DURATION
                    self.hitstun = 0.0

            self.pose = DOWN
            return

        # Get-up animation locks movement briefly.
        if self.getup_t > 0:
            self.getup_t = max(0.0, self.getup_t - dt)
            self.walk_vx = 0.0
            self.move_dir = 0
            return

        # Dodge / roll movement.
        if self.dodge_t > 0:
            self.dodge_t = max(0.0, self.dodge_t - dt)
            self.x += self.dodge_dir * PLAYER_DODGE_SPEED * dt
            self.x = clamp(self.x, ARENA_LEFT, ARENA_RIGHT)
            self.walk_vx = 0.0
            self.blocking = False
            return

        # Vertical movement.
        if not self.on_ground:
            self.jump_anim_t += dt
            self.vy += 1700 * dt
            self.y += self.vy * dt
            if self.y >= GROUND_Y:
                self.y = GROUND_Y
                self.vy = 0
                self.on_ground = True
                self.landing_t = 0.10

        # Horizontal movement.
        if self.dash_t > 0:
            self.dash_t -= dt
            self.x += self.vx * dt
            if self.dash_t <= 0:
                self.vx = 0
        else:
            can_walk = (
                self.can_act()
                and not self.attacking
                and not self.blocking
                and not self.crouching
            )

            target_vx = self.move_dir * WALK_SPEED if can_walk else 0.0
            accel = WALK_ACCEL if target_vx != 0 else WALK_BRAKE
            delta = target_vx - self.walk_vx
            max_step = accel * dt

            if delta > max_step:
                self.walk_vx += max_step
            elif delta < -max_step:
                self.walk_vx -= max_step
            else:
                self.walk_vx = target_vx

            if abs(self.walk_vx) < 0.4 and target_vx == 0:
                self.walk_vx = 0.0

            distance_moved = abs(self.walk_vx) * dt
            self.x += self.walk_vx * dt

            if can_walk and abs(self.walk_vx) > 8:
                frame_count = (
                    len(self.action_set.get("walk", []))
                    if self.action_set
                    else len(WALK_FRAMES)
                )
                frame_count = max(1, frame_count)
                self.walk_anim += (
                    distance_moved / WALK_STRIDE_PX
                ) * frame_count

        self.x = clamp(self.x, ARENA_LEFT, ARENA_RIGHT)

        # Attack timing.
        if self.attacking:
            self.attack_t += dt
            info = ATTACKS[self.attack_name]
            self.pose = info["frame"]
            if self.attack_t >= info["duration"]:
                self.attack_name = None
                self.attack_t = 0.0
                self.attack_hit = False

        # Old pose logic stays active for the red boss.
        if not self.action_set and not self.attacking:
            if self.hitstun > 0:
                pass
            elif not self.on_ground:
                if self.vy < -180:
                    self.pose = JUMP_RISE
                elif self.vy > 180:
                    self.pose = JUMP_FALL
                else:
                    self.pose = JUMP
            elif self.blocking:
                self.pose = BLOCK
            elif self.crouching:
                self.pose = CROUCH
            elif abs(self.walk_vx) > 8:
                self.pose = WALK_FRAMES[int(self.walk_anim) % len(WALK_FRAMES)]
            else:
                self.pose = IDLE

    def active_hitbox(self):
        if not self.attacking or self.attack_hit:
            return None

        info = ATTACKS[self.attack_name]
        if not (info["active_start"] <= self.attack_t <= info["active_end"]):
            return None

        body = self.body_rect()
        if self.attack_name in ("kick", "heavy_kick"):
            hit_h = 55
        else:
            hit_h = 48
        y = body.centery - hit_h // 2

        if self.facing == 1:
            return pygame.Rect(body.right - 5, y, info["range"], hit_h)
        return pygame.Rect(body.left - info["range"] + 5, y, info["range"], hit_h)

    def draw(self, surf):
        frame = self._sheet_frame()
        if frame is None:
            frame = self.frames[self.pose % len(self.frames)]

        if self.facing == -1:
            frame = pygame.transform.flip(frame, True, False)

        bounds = frame.get_bounding_rect(min_alpha=8)
        draw_x = float(self.x - bounds.centerx)
        draw_y = float(self.y - bounds.bottom)

        if (
            not self.action_set
            and self.on_ground
            and not self.attacking
            and not self.knocked_down
            and not self.crouching
            and abs(self.walk_vx) < 8
        ):
            draw_y += math.sin(self.motion_t * 3.0) * 1.0

        if self.landing_t > 0:
            landing_phase = 1.0 - self.landing_t / 0.10
            draw_y += math.sin(landing_phase * math.pi) * 1.5

        # Very small attack commitment; the sheet already contains the motion.
        if self.attacking and not self.action_set:
            info = ATTACKS[self.attack_name]
            progress = clamp(
                self.attack_t / max(0.001, info["duration"]),
                0.0,
                1.0,
            )
            lunge = math.sin(progress * math.pi)
            amount = 4.0 if self.attack_name in ("jab", "cross") else 2.5
            draw_x += self.facing * amount * lunge

        draw_x = int(draw_x)
        draw_y = int(draw_y)

        if self.flash_t > 0:
            flash = frame.copy()
            flash.fill((85, 85, 85, 0), special_flags=pygame.BLEND_RGBA_ADD)
            surf.blit(flash, (draw_x, draw_y))
        else:
            surf.blit(frame, (draw_x, draw_y))




class AdaptiveBossAI:
    def __init__(self, memory):
        self.memory = memory
        self.think_t = 0.0
        self.move = 0
        self.block = False
        self.last_plan = "Reading player..."

    def reset_round(self):
        self.think_t = 0.0
        self.move = 0
        self.block = False
        self.last_plan = "Reading player..."

    def decide(self, boss, player, dt):
        if not boss.can_act() or boss.knocked_down:
            boss.move_dir = 0
            boss.blocking = False
            return

        dist = abs(player.x - boss.x)
        boss.facing = 1 if player.x > boss.x else -1

        self.think_t -= dt
        if self.think_t > 0:
            boss.move_dir = self.move
            boss.blocking = self.block and not boss.attacking
            return

        self.think_t = random.uniform(0.08, 0.16)

        recent_attack = self.memory.group_ratio(
            ["jab", "cross", "kick", "heavy_kick"], recent=True
        )
        punch_bias = self.memory.group_ratio(["jab", "cross"])
        kick_bias = self.memory.group_ratio(["kick", "heavy_kick"])
        jump_bias = self.memory.ratio("jump")
        block_bias = self.memory.ratio("block")
        retreat_bias = self.memory.ratio("retreat")
        advance_bias = self.memory.ratio("advance")

        self.move = 0
        self.block = False

        # Immediate reaction: a learned defensive response to player attack habits.
        if player.attacking and dist < 165:
            defend_chance = 0.42 + recent_attack * 0.42
            if kick_bias > punch_bias:
                defend_chance += 0.10
            if random.random() < defend_chance:
                self.block = True
                self.last_plan = "Learned defense"
                return

        # Anti-jump adaptation.
        if not player.on_ground and dist < 175:
            anti_air_chance = 0.28 + min(0.48, jump_bias * 1.5)
            if random.random() < anti_air_chance:
                boss.start_attack("kick")
                self.last_plan = "Anti-air"
                return

        # Far range: chase players that commonly retreat.
        if dist > 245:
            chase = 0.58 + retreat_bias * 0.75
            if random.random() < min(0.94, chase):
                if dist > 340 and boss.dash_cooldown <= 0 and random.random() < 0.35:
                    boss.dash(boss.facing)
                    self.last_plan = "Dash chase"
                else:
                    self.move = boss.facing
                    self.last_plan = "Chasing retreat"
            else:
                self.move = 0
                self.last_plan = "Waiting"
            boss.move_dir = self.move
            boss.blocking = self.block
            return

        # Mid range: kicks become more useful; punish predictable forward movement.
        if dist > 125:
            if advance_bias > 0.18 and random.random() < 0.28:
                boss.start_attack("heavy_kick")
                self.last_plan = "Intercept"
                return

            if random.random() < 0.48:
                self.move = boss.facing
                self.last_plan = "Closing range"
            elif random.random() < 0.38:
                boss.start_attack("kick")
                self.last_plan = "Range kick"
            else:
                self.move = -boss.facing
                self.last_plan = "Spacing"

            boss.move_dir = self.move
            boss.blocking = self.block
            return

        # Close range: choose attacks using learned player tendencies.
        r = random.random()

        # Frequent blocker -> heavier guard-damage attacks.
        if block_bias > 0.16 and r < 0.42:
            boss.start_attack("heavy_kick")
            self.last_plan = "Guard pressure"
        # Frequent kick player -> defend or use faster jab.
        elif kick_bias > 0.18 and r < 0.55:
            if random.random() < 0.48:
                self.block = True
                self.last_plan = "Kick read"
            else:
                boss.start_attack("jab")
                self.last_plan = "Fast counter"
        # Frequent punch player -> block/cross counter.
        elif punch_bias > 0.18 and r < 0.58:
            if random.random() < 0.38:
                self.block = True
                self.last_plan = "Punch read"
            else:
                boss.start_attack("cross")
                self.last_plan = "Counter cross"
        else:
            choices = ["jab", "cross", "kick", "heavy_kick"]
            weights = [0.34, 0.28, 0.25, 0.13]
            boss.start_attack(random.choices(choices, weights=weights, k=1)[0])
            self.last_plan = "Mixed offense"

        boss.move_dir = self.move
        boss.blocking = self.block and not boss.attacking


class AnimatedHealthBar:
    """Fighting-game style health bar with smooth damage animation.

    The main bar moves quickly to the real HP value while a bright damage
    trail follows behind. Low health adds a pulse and hits briefly flash the
    edge of the bar.
    """

    def __init__(self, x, y, w, h, max_value, fill_color, glow_color, reverse=False):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.max_value = float(max_value)
        self.fill_color = fill_color
        self.glow_color = glow_color
        self.reverse = reverse

        self.value = float(max_value)
        self.display_value = float(max_value)
        self.trail_value = float(max_value)
        self.last_value = float(max_value)
        self.trail_delay = 0.0
        self.hit_flash = 0.0
        self.anim_t = 0.0

    def sync(self, value):
        """Instantly sync the bar, useful when a new round starts."""
        value = clamp(float(value), 0.0, self.max_value)
        self.value = value
        self.display_value = value
        self.trail_value = value
        self.last_value = value
        self.trail_delay = 0.0
        self.hit_flash = 0.0

    def update(self, dt, value):
        self.value = clamp(float(value), 0.0, self.max_value)
        self.anim_t += dt

        if self.value < self.last_value:
            self.trail_delay = 0.20
            self.hit_flash = 0.16

        self.last_value = self.value
        self.hit_flash = max(0.0, self.hit_flash - dt)

        # Fast front bar. Exponential smoothing keeps it frame-rate independent.
        front_speed = 1.0 - math.exp(-17.0 * dt)
        self.display_value += (self.value - self.display_value) * front_speed

        # Golden/white damage trail waits for a moment, then catches up slowly.
        if self.trail_value < self.display_value:
            self.trail_value = self.display_value

        if self.trail_delay > 0.0:
            self.trail_delay = max(0.0, self.trail_delay - dt)
        else:
            trail_speed = 1.0 - math.exp(-4.8 * dt)
            self.trail_value += (self.display_value - self.trail_value) * trail_speed

        if abs(self.display_value - self.value) < 0.02:
            self.display_value = self.value
        if abs(self.trail_value - self.display_value) < 0.02:
            self.trail_value = self.display_value

    def _value_rect(self, value):
        inner_x = self.x + 4
        inner_y = self.y + 4
        inner_w = self.w - 8
        inner_h = self.h - 8
        amount = max(0, int(inner_w * value / self.max_value))

        if self.reverse:
            x = inner_x + inner_w - amount
        else:
            x = inner_x

        return pygame.Rect(x, inner_y, amount, inner_h)

    def draw(self, surf):
        outer = pygame.Rect(self.x, self.y, self.w, self.h)
        inner = outer.inflate(-8, -8)
        health_ratio = self.value / self.max_value if self.max_value else 0.0

        # Low HP breathing pulse.
        low_pulse = 0.0
        if health_ratio <= 0.25:
            low_pulse = (math.sin(self.anim_t * 9.0) + 1.0) * 0.5

        # Soft colored glow around the whole bar.
        glow_alpha = 48 + int(48 * low_pulse) + (55 if self.hit_flash > 0 else 0)
        glow_surface = pygame.Surface((self.w + 26, self.h + 26), pygame.SRCALPHA)
        pygame.draw.rect(
            glow_surface,
            (*self.glow_color, min(155, glow_alpha)),
            pygame.Rect(8, 8, self.w + 10, self.h + 10),
            border_radius=13,
        )
        surf.blit(glow_surface, (self.x - 13, self.y - 13), special_flags=pygame.BLEND_RGBA_ADD)

        # Transparent glass-style fighting-game frame.
        # The arena stays visible through the health bar instead of a solid black box.
        frame_pad = 8
        frame_surface = pygame.Surface(
            (self.w + frame_pad * 2, self.h + frame_pad * 2), pygame.SRCALPHA
        )
        local_outer = pygame.Rect(frame_pad, frame_pad, self.w, self.h)
        local_inner = local_outer.inflate(-8, -8)

        # Very light smoky glass background.
        pygame.draw.rect(
            frame_surface, (6, 8, 14, 42), local_outer.inflate(8, 8), border_radius=12
        )
        pygame.draw.rect(
            frame_surface, (18, 22, 32, 58), local_outer, border_radius=9
        )
        pygame.draw.rect(
            frame_surface, (2, 4, 8, 40), local_inner, border_radius=6
        )

        # Semi-transparent metallic borders.
        pygame.draw.rect(
            frame_surface, (205, 215, 235, 155), local_outer.inflate(5, 5), 2, border_radius=11
        )
        pygame.draw.rect(
            frame_surface, (245, 248, 255, 130), local_outer, 2, border_radius=9
        )
        pygame.draw.rect(
            frame_surface, (110, 120, 145, 95), local_inner, 1, border_radius=6
        )

        surf.blit(frame_surface, (self.x - frame_pad, self.y - frame_pad))

        # Delayed damage indicator.
        trail_rect = self._value_rect(self.trail_value)
        if trail_rect.width > 0:
            pygame.draw.rect(surf, (255, 214, 105), trail_rect, border_radius=5)
            trail_shine = trail_rect.copy()
            trail_shine.height = max(2, trail_rect.height // 3)
            pygame.draw.rect(surf, (255, 245, 205), trail_shine, border_radius=5)

        # Main blue/red HP fill.
        hp_rect = self._value_rect(self.display_value)
        if hp_rect.width > 0:
            boost = int(38 * low_pulse)
            base = tuple(min(255, c + boost) for c in self.fill_color)
            pygame.draw.rect(surf, base, hp_rect, border_radius=5)

            # Top highlight makes the bar look less flat.
            shine = hp_rect.copy()
            shine.height = max(3, hp_rect.height // 3)
            shine_color = tuple(min(255, c + 75) for c in base)
            pygame.draw.rect(surf, shine_color, shine, border_radius=5)

            # Darker lower edge for depth.
            lower = hp_rect.copy()
            lower.y = hp_rect.bottom - max(2, hp_rect.height // 5)
            lower.height = max(2, hp_rect.height // 5)
            dark = tuple(max(0, int(c * 0.58)) for c in base)
            pygame.draw.rect(surf, dark, lower, border_radius=4)

            # Bright spark/edge on recent damage.
            if self.hit_flash > 0:
                edge_x = hp_rect.left if self.reverse else hp_rect.right - 2
                pygame.draw.line(
                    surf,
                    (255, 255, 255),
                    (edge_x, hp_rect.top - 2),
                    (edge_x, hp_rect.bottom + 2),
                    4,
                )

        # Subtle transparent divisions across the bar.
        div_surface = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for i in range(1, 10):
            sx = int((self.w - 8) * i / 10) + 4
            pygame.draw.line(
                div_surface, (0, 0, 0, 75), (sx, 6), (sx, self.h - 6), 1
            )
        surf.blit(div_surface, (self.x, self.y))


def separate_fighters(a, b):
    """Keep the visible fighters from standing inside each other."""
    # Center-to-center spacing tuned for the current character sprites.
    # Crouching/down poses can sit a little closer.
    if a.knocked_down or b.knocked_down:
        min_gap = 92.0
    elif a.crouching or b.crouching:
        min_gap = 100.0
    else:
        min_gap = 112.0

    dx = b.x - a.x
    dist = abs(dx)

    # Avoid ambiguous direction if both centers become exactly equal.
    if dist < 0.001:
        dx = 1.0 if a.facing == 1 else -1.0
        dist = 0.001

    if dist < min_gap:
        overlap = min_gap - dist

        # Split the correction between both fighters.
        push = overlap * 0.5
        sign = 1.0 if dx > 0 else -1.0

        a.x -= sign * push
        b.x += sign * push

        # Stop walking velocity that is still pushing into the opponent.
        if a.walk_vx * sign > 0:
            a.walk_vx = 0.0
        if b.walk_vx * sign < 0:
            b.walk_vx = 0.0

        # Stop dash momentum when the fighters make body contact.
        if a.dash_t > 0 and a.vx * sign > 0:
            a.dash_t = 0.0
            a.vx = 0.0
        if b.dash_t > 0 and b.vx * sign < 0:
            b.dash_t = 0.0
            b.vx = 0.0

        a.x = clamp(a.x, ARENA_LEFT, ARENA_RIGHT)
        b.x = clamp(b.x, ARENA_LEFT, ARENA_RIGHT)


def resolve_attack(attacker, defender):
    """Resolve one hit."""
    hitbox = attacker.active_hitbox()
    if hitbox and hitbox.colliderect(defender.body_rect()):
        info = ATTACKS[attacker.attack_name]
        attacker.attack_hit = True

        damage = info["damage"]
        knockback = info["knockback"]
        guard_damage = info["guard_damage"]

        defender.take_hit(damage, knockback, attacker.facing, guard_damage)

        return True
    return False



def draw_glow_text(surf, text, font, center, color, glow_color, glow=10):
    """Draw title text with a simple neon-style glow."""
    base = font.render(text, True, color)
    glow_img = font.render(text, True, glow_color)
    rect = base.get_rect(center=center)

    for dx, dy, alpha in ((-glow, 0, 55), (glow, 0, 55), (0, -glow, 55), (0, glow, 55),
                          (-5, -5, 35), (5, 5, 35)):
        temp = glow_img.copy()
        temp.set_alpha(alpha)
        surf.blit(temp, temp.get_rect(center=(center[0] + dx, center[1] + dy)))

    surf.blit(base, rect)


def draw_menu_button(surf, rect, label, font, selected, accent):
    """Draw a beveled menu button that matches the artwork more closely."""

    notch = 22
    pts = [
        (rect.x + notch, rect.y),
        (rect.right - notch, rect.y),
        (rect.right, rect.centery),
        (rect.right - notch, rect.bottom),
        (rect.x + notch, rect.bottom),
        (rect.x, rect.centery),
    ]

    if selected:
        glow = pygame.Surface((rect.w + 40, rect.h + 34), pygame.SRCALPHA)
        glow_rect = glow.get_rect()
        glow_pts = [
            (20 + notch, 17),
            (glow_rect.w - 20 - notch, 17),
            (glow_rect.w - 20, glow_rect.centery),
            (glow_rect.w - 20 - notch, glow_rect.h - 17),
            (20 + notch, glow_rect.h - 17),
            (20, glow_rect.centery),
        ]
        pygame.draw.polygon(glow, (*accent, 85), glow_pts)
        pygame.draw.polygon(glow, (*accent, 38), glow_pts, 12)
        surf.blit(glow, (rect.x - 20, rect.y - 17), special_flags=pygame.BLEND_RGBA_ADD)

        for i in range(7):
            alpha = max(18, 70 - i * 8)
            ring = pygame.Surface((rect.w + 22 + i * 6, rect.h + 16 + i * 4), pygame.SRCALPHA)
            rr = ring.get_rect()
            ring_pts = [
                (11 + i * 3 + notch, 8 + i * 2),
                (rr.w - 11 - i * 3 - notch, 8 + i * 2),
                (rr.w - 11 - i * 3, rr.centery),
                (rr.w - 11 - i * 3 - notch, rr.h - 8 - i * 2),
                (11 + i * 3 + notch, rr.h - 8 - i * 2),
                (11 + i * 3, rr.centery),
            ]
            pygame.draw.polygon(ring, (*accent, alpha), ring_pts, 2)
            surf.blit(ring, (rect.x - 11 - i * 3, rect.y - 8 - i * 2))

        pygame.draw.polygon(surf, (84, 8, 10), pts)
        inner = rect.inflate(-10, -10)
        inner_pts = [
            (inner.x + notch - 5, inner.y),
            (inner.right - notch + 5, inner.y),
            (inner.right, inner.centery),
            (inner.right - notch + 5, inner.bottom),
            (inner.x + notch - 5, inner.bottom),
            (inner.x, inner.centery),
        ]
        pygame.draw.polygon(surf, (196, 24, 18), inner_pts)
        shine = pygame.Rect(inner.x + 20, inner.y + 4, inner.w - 40, max(6, inner.h // 3))
        pygame.draw.rect(surf, (255, 170, 140), shine, border_radius=8)
        pygame.draw.polygon(surf, (255, 255, 255), pts, 2)
        pygame.draw.polygon(surf, (255, 110, 90), inner_pts, 2)
        text_color = (255, 245, 238)
        shadow_color = (70, 0, 0)
    else:
        pygame.draw.polygon(surf, (12, 14, 21), pts)
        inner = rect.inflate(-8, -8)
        inner_pts = [
            (inner.x + notch - 6, inner.y),
            (inner.right - notch + 6, inner.y),
            (inner.right, inner.centery),
            (inner.right - notch + 6, inner.bottom),
            (inner.x + notch - 6, inner.bottom),
            (inner.x, inner.centery),
        ]
        pygame.draw.polygon(surf, (22, 24, 33), inner_pts)
        top_shine = pygame.Rect(inner.x + 24, inner.y + 3, inner.w - 48, max(4, inner.h // 4))
        pygame.draw.rect(surf, (48, 52, 65), top_shine, border_radius=6)
        pygame.draw.polygon(surf, (145, 150, 162), pts, 2)
        pygame.draw.polygon(surf, (72, 76, 90), inner_pts, 1)
        text_color = (214, 217, 226)
        shadow_color = (0, 0, 0)

    # Small side diamonds like in the reference image.
    d = 8
    left_diamond = [
        (rect.x + 11, rect.centery),
        (rect.x + 11 + d, rect.centery - d),
        (rect.x + 11 + d * 2, rect.centery),
        (rect.x + 11 + d, rect.centery + d),
    ]
    right_diamond = [
        (rect.right - 11, rect.centery),
        (rect.right - 11 - d, rect.centery - d),
        (rect.right - 11 - d * 2, rect.centery),
        (rect.right - 11 - d, rect.centery + d),
    ]
    dia_color = (255, 245, 240) if selected else (185, 190, 205)
    dia_fill = accent if selected else (28, 30, 42)
    pygame.draw.polygon(surf, dia_fill, left_diamond)
    pygame.draw.polygon(surf, dia_fill, right_diamond)
    pygame.draw.polygon(surf, dia_color, left_diamond, 2)
    pygame.draw.polygon(surf, dia_color, right_diamond, 2)

    shadow = font.render(label, True, shadow_color)
    txt = font.render(label, True, text_color)
    shadow_rect = shadow.get_rect(center=(rect.centerx, rect.centery + 2))
    txt_rect = txt.get_rect(center=rect.center)
    surf.blit(shadow, shadow_rect)
    surf.blit(txt, txt_rect)


def make_seamless_menu_frames(frames):
    """Replace a short ending section with an end-to-start crossfade.

    Precomputing the transition ONCE prevents costly full-screen blending
    on every refresh. The loop continues forward, not back and forth.
    """
    count = len(frames)
    if count < 7:
        # Too few images for a reliable, continuous crossfade.
        return frames, 0

    overlap = min(MENU_LOOP_BLEND_FRAMES, (count - 1) // 3)
    if overlap < 2:
        return frames, 0

    seamless = frames[:count - overlap]
    for i in range(overlap):
        # Keep forward motion from the tail while gradually introducing
        # the matching first frames; finish on frame[overlap - 1].
        tail = frames[count - overlap + i].copy()
        beginning = frames[i].copy()
        progress = (i + 1) / overlap
        alpha = progress * progress * (3.0 - 2.0 * progress)
        beginning.set_alpha(round(255 * alpha))
        tail.blit(beginning, (0, 0))
        seamless.append(tail)

    print(f"Menu loop overlap: {overlap} frames ({overlap / MENU_FRAME_FPS:.2f}s)")
    return seamless, overlap


def get_menu_frame(frames, anim_t, loop_overlap=0):
    """Play the first pass fully, then repeat past the overlapped beginning."""
    if not frames:
        return None
    count = len(frames)
    step = max(0, int(anim_t * MENU_FRAME_FPS))
    if step < count:
        index = step
    else:
        # The ending already fades into frames 0..overlap-1; don't replay
        # these images, or the loop would appear to pause/stutter.
        index = loop_overlap + (step - count) % (count - loop_overlap)
    return frames[index]


def draw_start_menu(
    surf,
    menu_bg,
    menu_font,
    small_font,
    button_rects,
    labels,
    selected,
    anim_t,
):
    """Draw the animated menu and only a small moving selection marker.

    The menu text/design already exists inside each animation frame, so nothing
    is drawn on top of the option text.
    """
    surf.blit(menu_bg, (0, 0))

    if not button_rects:
        return

    selected = selected % len(button_rects)
    rect = button_rects[selected]

    # Small animated markers only. No rectangle, plate, glow box, or duplicate text.
    pulse = (math.sin(anim_t * 6.0) + 1.0) * 0.5
    cy = rect.centery
    offset = int(3 * pulse)

    # Keep the arrows outside the menu words.
    left_x = WIDTH // 2 - 165 - offset
    right_x = WIDTH // 2 + 165 + offset
    size = 7
    color = (230, 245, 255)

    # >>
    for extra in (0, 10):
        x = left_x - extra
        pygame.draw.lines(
            surf,
            color,
            False,
            [(x - size, cy - size), (x, cy), (x - size, cy + size)],
            2,
        )

    # <<
    for extra in (0, 10):
        x = right_x + extra
        pygame.draw.lines(
            surf,
            color,
            False,
            [(x + size, cy - size), (x, cy), (x + size, cy + size)],
            2,
        )

def draw_options_menu(
    surf,
    bg,
    title_font,
    font,
    small_font,
    labels,
    selected,
    button_rects,
):
    """OPTIONS page with selector arrows kept close to the selected text."""
    surf.blit(bg, (0, 0))

    shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 190))
    surf.blit(shade, (0, 0))

    draw_glow_text(surf, "OPTIONS", title_font, (WIDTH // 2, 150), WHITE, BLUE, 7)

    panel = pygame.Rect(WIDTH // 2 - 250, 230, 500, 230)
    panel_surf = pygame.Surface(panel.size, pygame.SRCALPHA)
    panel_surf.fill((8, 10, 17, 220))
    surf.blit(panel_surf, panel.topleft)
    pygame.draw.rect(surf, (170, 178, 200), panel, 2, border_radius=14)

    pulse_t = pygame.time.get_ticks() / 1000.0
    pulse = (math.sin(pulse_t * 5.0) + 1.0) * 0.5
    drift = int(2 * pulse)

    for i, (label, rect) in enumerate(zip(labels, button_rects)):
        selected_now = (i == selected)
        color = WHITE if selected_now else (195, 200, 215)

        label_img = font.render(label, True, color)
        label_rect = label_img.get_rect(center=rect.center)
        surf.blit(label_img, label_rect)

        if selected_now:
            cy = label_rect.centery

            # Keep the double arrows visually attached to the word,
            # rather than floating far away from it.
            gap = 24
            size = 8
            arrow_color = (242, 118, 108)

            left_x = label_rect.left - gap - drift
            right_x = label_rect.right + gap + drift

            # subtle local glow only
            for x in (left_x - 6, right_x + 6):
                glow = pygame.Surface((34, 34), pygame.SRCALPHA)
                pygame.draw.circle(glow, (*arrow_color, 28), (17, 17), 13)
                surf.blit(glow, (x - 17, cy - 17), special_flags=pygame.BLEND_RGBA_ADD)

            # Left double chevrons >>
            for extra in (0, 10):
                x = left_x - extra
                pygame.draw.lines(
                    surf,
                    arrow_color,
                    False,
                    [(x - size, cy - size), (x, cy), (x - size, cy + size)],
                    2,
                )

            # Right double chevrons <<
            for extra in (0, 10):
                x = right_x + extra
                pygame.draw.lines(
                    surf,
                    arrow_color,
                    False,
                    [(x + size, cy - size), (x, cy), (x + size, cy + size)],
                    2,
                )

    note = small_font.render(
        "UP / DOWN = Select     ENTER / X = Confirm     ESC / Circle = Back",
        True,
        (210, 215, 230),
    )
    surf.blit(note, note.get_rect(center=(WIDTH // 2, 530)))



def draw_controller_guide(surf, bg, controller_img, title_font, small_font):
    """Clean controller help page: controller image left, action list right."""
    surf.blit(bg, (0, 0))

    shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 205))
    surf.blit(shade, (0, 0))

    draw_glow_text(
        surf,
        "CONTROLLER",
        title_font,
        (WIDTH // 2, 72),
        WHITE,
        BLUE,
        6,
    )

    # Main glass panel
    panel = pygame.Rect(55, 115, WIDTH - 110, 520)
    glass = pygame.Surface(panel.size, pygame.SRCALPHA)
    glass.fill((7, 10, 18, 225))
    surf.blit(glass, panel.topleft)
    pygame.draw.rect(surf, (155, 175, 205), panel, 2, border_radius=16)

    # -------------------------------------------------
    # LEFT: controller image
    # -------------------------------------------------
    image_area = pygame.Rect(panel.x + 25, panel.y + 30, 590, 410)

    if controller_img is not None:
        scale = min(
            image_area.w / controller_img.get_width(),
            image_area.h / controller_img.get_height(),
        )
        size = (
            max(1, int(controller_img.get_width() * scale)),
            max(1, int(controller_img.get_height() * scale)),
        )
        image = pygame.transform.smoothscale(controller_img, size)
        image_rect = image.get_rect(center=image_area.center)
        surf.blit(image, image_rect)
    else:
        missing = small_font.render(
            "controller_guide.png not found",
            True,
            WHITE,
        )
        surf.blit(missing, missing.get_rect(center=image_area.center))

    # -------------------------------------------------
    # RIGHT: clean button list
    # -------------------------------------------------
    list_panel = pygame.Rect(panel.x + 650, panel.y + 32, 475, 405)
    list_bg = pygame.Surface(list_panel.size, pygame.SRCALPHA)
    list_bg.fill((12, 18, 30, 238))
    surf.blit(list_bg, list_panel.topleft)
    pygame.draw.rect(surf, (85, 130, 200), list_panel, 2, border_radius=12)

    header_font = pygame.font.SysFont("arial", 25, bold=True)
    header = header_font.render("PS4 BUTTONS", True, GOLD)
    surf.blit(header, (list_panel.x + 24, list_panel.y + 18))

    mappings = [
        ("D-PAD ← / →", "Move"),
        ("LEFT STICK", "Move"),
        ("D-PAD ↑", "Jump"),
        ("SQUARE", "Jab"),
        ("TRIANGLE", "Cross Punch"),
        ("X / CROSS", "Kick / Select"),
        ("CIRCLE", "Heavy Kick / Back"),
        ("R1", "Dash"),
        ("OPTIONS", "Pause / Main Menu"),
    ]

    y = list_panel.y + 68
    key_x = list_panel.x + 24
    action_x = list_panel.x + 235

    for button_name, action in mappings:
        key_text = small_font.render(button_name, True, GOLD)
        action_text = small_font.render(action, True, WHITE)
        surf.blit(key_text, (key_x, y))
        surf.blit(action_text, (action_x, y))
        y += 34

    # Menu controls line
    menu_label = small_font.render(
        "MENU: D-pad ↑/↓ = Move   X = Select   Circle = Back",
        True,
        (205, 215, 235),
    )
    surf.blit(menu_label, menu_label.get_rect(center=(WIDTH // 2, 590)))

    back = small_font.render(
        "ESC / ENTER / Circle / OPTIONS = Back to OPTIONS",
        True,
        (205, 215, 235),
    )
    surf.blit(back, back.get_rect(center=(WIDTH // 2, 665)))



def _joy_button(joy, index):
    """Safely read a joystick button without crashing on missing mappings."""
    return (
        joy is not None
        and 0 <= index < joy.get_numbuttons()
        and bool(joy.get_button(index))
    )


def _ps4_buttons(joy):
    """Return shoulder/start mapping for native DualShock or Xbox-emulated pads."""
    if joy is None:
        return {"l1": 4, "r1": 5, "options": 7}
    name = joy.get_name().lower()
    native_ps = any(tag in name for tag in ("wireless controller", "dualshock", "dualsense", "playstation"))
    if native_ps and joy.get_numbuttons() >= 11:
        # Native DualShock 4 / DualSense SDL button layout.
        return {"l1": 9, "r1": 10, "options": 6}
    # DS4Windows / Steam Input commonly exposes an Xbox-style layout.
    return {"l1": 4, "r1": 5, "options": 7}


def _controller_direction(joy, deadzone=0.28):
    """Read left/right from left stick or D-pad."""
    if joy is None:
        return 0

    # D-pad hat first when available.
    if joy.get_numhats() > 0:
        hx, _ = joy.get_hat(0)
        if hx < 0:
            return -1
        if hx > 0:
            return 1

    # Native PS pads may expose D-pad as buttons 13/14.
    if _joy_button(joy, 13):
        return -1
    if _joy_button(joy, 14):
        return 1

    if joy.get_numaxes() > 0:
        x = joy.get_axis(0)
        if x < -deadzone:
            return -1
        if x > deadzone:
            return 1
    return 0


def _controller_down(joy, deadzone=0.45):
    """Read crouch/down from D-pad or left stick."""
    if joy is None:
        return False
    if joy.get_numhats() > 0 and joy.get_hat(0)[1] < 0:
        return True
    if _joy_button(joy, 12):
        return True
    return joy.get_numaxes() > 1 and joy.get_axis(1) > deadzone


def play_loading_intro(screen, clock, frame_folder, sound_path=None):
    """Play the RHS loading animation tightly synchronized to its soundtrack.

    Playback is based on elapsed real time instead of sleeping once per image.
    If loading a frame is momentarily slow, the animation skips ahead to the
    correct frame instead of letting the audio and visuals drift apart.
    """
    frame_folder = Path(frame_folder)
    sound_path = Path(sound_path) if sound_path is not None else None

    if not frame_folder.exists():
        print(f"Loading frames folder not found: {frame_folder}")
        return True

    def frame_number(path):
        try:
            return int(path.stem.split("_")[-1])
        except ValueError:
            return 10**9

    frame_paths = list(frame_folder.glob("frame_*.jpg"))
    frame_paths += list(frame_folder.glob("frame_*.png"))
    frame_paths = sorted(frame_paths, key=frame_number)

    if not frame_paths:
        print(f"No loading frames found in: {frame_folder}")
        return True

    # Dedicated loading-audio channel.
    loading_sound = None
    loading_channel = None

    if sound_path is not None and sound_path.exists():
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()

            pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
            loading_channel = pygame.mixer.Channel(6)
            loading_sound = pygame.mixer.Sound(str(sound_path))
            loading_sound.set_volume(LOADING_INTRO_SOUND_VOLUME)
            print(f"Loading intro sound loaded: {sound_path.name}")
        except pygame.error as exc:
            print(f"Could not load loading intro sound: {exc}")
            loading_sound = None
            loading_channel = None
    elif sound_path is not None:
        print(f"Loading intro sound not found: {sound_path}")

    print(
        f"Playing RHS loading animation: {len(frame_paths)} frames "
        f"at {LOADING_INTRO_FPS:.1f} FPS"
    )

    frame_duration = 1.0 / LOADING_INTRO_FPS
    # Allow all loading frames to play; do not cut the animation off early.
    total_duration = len(frame_paths) / LOADING_INTRO_FPS
    print(f"Full loading intro duration: {total_duration:.1f} seconds")

    # Show frame 1 first, then start the soundtrack on that exact visual.
    try:
        first_frame = pygame.image.load(frame_paths[0]).convert()
        if first_frame.get_size() != (WIDTH, HEIGHT):
            first_frame = pygame.transform.smoothscale(first_frame, (WIDTH, HEIGHT))
        screen.blit(first_frame, (0, 0))
        pygame.display.flip()
    except pygame.error as exc:
        print(f"Could not load first loading frame: {exc}")
        return True

    if loading_sound is not None and loading_channel is not None:
        loading_channel.play(loading_sound)

    start_time = pygame.time.get_ticks() / 1000.0
    last_index = -1
    last_surface = first_frame

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if loading_channel is not None:
                    loading_channel.stop()
                return False

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if loading_channel is not None:
                    loading_channel.fadeout(150)
                return True

        elapsed = pygame.time.get_ticks() / 1000.0 - start_time
        if elapsed >= total_duration:
            break

        # Real-time frame index keeps animation and sound locked together.
        frame_index = min(
            len(frame_paths) - 1,
            int(elapsed / frame_duration),
        )

        if frame_index != last_index:
            try:
                frame = pygame.image.load(frame_paths[frame_index]).convert()
                if frame.get_size() != (WIDTH, HEIGHT):
                    frame = pygame.transform.smoothscale(frame, (WIDTH, HEIGHT))
                last_surface = frame
                screen.blit(frame, (0, 0))
                pygame.display.flip()
                last_index = frame_index
            except pygame.error as exc:
                print(f"Could not load loading frame {frame_paths[frame_index].name}: {exc}")

        # Keep the event loop responsive without controlling animation timing.
        clock.tick(FPS)

    # Explicitly display the final READY frame.
    try:
        final_frame = pygame.image.load(frame_paths[-1]).convert()
        if final_frame.get_size() != (WIDTH, HEIGHT):
            final_frame = pygame.transform.smoothscale(final_frame, (WIDTH, HEIGHT))
        last_surface = final_frame
    except pygame.error:
        pass

    if last_surface is not None:
        screen.blit(last_surface, (0, 0))
        pygame.display.flip()

    # The full loading animation has finished. Stop any remaining intro
    # audio only when transitioning into the menu.
    if loading_channel is not None and loading_channel.get_busy():
        loading_channel.stop()

    return True


def main():
    pygame.init()
    pygame.joystick.init()
    pygame.display.set_caption("AI Boss Battle - Adaptive 1v1")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    # PS4 / gamepad support. Connect the controller before starting the game.
    controller = None
    if pygame.joystick.get_count() > 0:
        controller = pygame.joystick.Joystick(0)
        controller.init()
        print(f"Controller connected: {controller.get_name()}")
        print(
            f"  axes={controller.get_numaxes()} "
            f"buttons={controller.get_numbuttons()} hats={controller.get_numhats()}"
        )
    else:
        print("No controller detected. Keyboard controls remain available.")

    # Show the RHS cinematic before loading the large sprite/background sets.
    # The final READY frame stays visible during the remaining asset loading.
    if not play_loading_intro(
        screen,
        clock,
        ASSET_DIR / LOADING_INTRO_FRAMES,
        ASSET_DIR / LOADING_INTRO_SOUND,
    ):
        pygame.quit()
        return

    font = pygame.font.SysFont("arial", 24, bold=True)
    small = pygame.font.SysFont("arial", 18)
    big = pygame.font.SysFont("arial", 72, bold=True)
    title_font = pygame.font.SysFont("arial", 58, bold=True, italic=True)
    menu_font = pygame.font.SysFont("arial", 28, bold=True)

    # Main-menu music. Put .mp3 inside the project's assets folder.
    menu_music_path = ASSET_DIR / MENU_MUSIC_FILE
    menu_music_available = False
    menu_music_playing = False

    if pygame.mixer.get_init() and menu_music_path.exists():
        try:
            pygame.mixer.music.load(str(menu_music_path))
            pygame.mixer.music.set_volume(MENU_MUSIC_VOLUME)
            menu_music_available = True
            print(f"Menu music loaded: {menu_music_path.name}")
        except pygame.error as exc:
            print(f"Could not load menu music: {exc}")
    elif not menu_music_path.exists():
        print(f"Menu music not found: {menu_music_path}")

    # --------------------------------------------------------
    # Fighting-game announcer
    # Expected folder:
    # assets/sounds/announcer/core/
    # --------------------------------------------------------
    announcer_sounds = {}
    announcer_channel = None
    announcer_dir = ASSET_DIR / ANNOUNCER_DIR

    announcer_names = (
        "first_round",
        "second_round",
        "third_round",
        "fight",
        "ko",
        "knockout",
        "victor",
        "you_died",
        "game_over",
        "sudden_death",
    )

    if pygame.mixer.get_init():
        pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        announcer_channel = pygame.mixer.Channel(2)

        for sound_name in announcer_names:
            sound_path = announcer_dir / f"{sound_name}.wav"
            if sound_path.exists():
                try:
                    sound = pygame.mixer.Sound(str(sound_path))
                    sound.set_volume(ANNOUNCER_VOLUME)
                    announcer_sounds[sound_name] = sound
                except pygame.error as exc:
                    print(f"Could not load announcer sound {sound_path.name}: {exc}")

        print(f"Loaded {len(announcer_sounds)} announcer sound(s).")

    def play_announcer(sound_name):
        """Play one announcer clip without stacking voices on top of each other."""
        sound = announcer_sounds.get(sound_name)
        if sound is None or announcer_channel is None:
            return
        announcer_channel.stop()
        announcer_channel.play(sound)

    def play_round_announcement(number):
        round_voice = {
            1: "first_round",
            2: "second_round",
            3: "third_round",
        }.get(number)
        if round_voice:
            play_announcer(round_voice)

    # The updated menu artwork has exactly three selectable rows.
    menu_labels = ("START GAME", "OPTIONS", "QUIT")

    # Aligned to the START GAME / OPTIONS / QUIT rows in the supplied frame.
    menu_button_centers_y = (498, 552, 606)
    menu_button_rects = [
        pygame.Rect(WIDTH // 2 - 190, cy - 23, 380, 46)
        for cy in menu_button_centers_y
    ]

    # OPTIONS submenu.
    option_labels = ("CONTROLLER", "BACK")
    option_selected = 0
    option_button_rects = [
        pygame.Rect(WIDTH // 2 - 155, 300, 310, 50),
        pygame.Rect(WIDTH // 2 - 155, 375, 310, 50),
    ]

    # Prefer the numbered PNG frames. The MP4 is only a fallback.
    background_frames = load_background_frames(
        ASSET_DIR / "background_frames",
        ASSET_DIR / "arena.png",
        (WIDTH, HEIGHT),
    )
    use_png_background = len(background_frames) > 1

    video_background = VideoBackground(
        ASSET_DIR / BACKGROUND_VIDEO,
        (WIDTH, HEIGHT),
    )

    bg = background_frames[0]
    if (
        not use_png_background
        and video_background.available
        and video_background.surface is not None
    ):
        bg = video_background.surface.copy()

    # Full-screen start-menu artwork.
    # It now supports the new wallpaper names as well as the old menu_screen.png.
    menu_candidates = [
        ASSET_DIR / "infernal_blue_versus_red_battle_screen.png",
        ASSET_DIR / "ai_boss_battle_vanguard_vs_nemesis.png",
        ASSET_DIR / "menu_bg.png",
        ASSET_DIR / "menu_screen.png",
    ]
    menu_bg = None
    for menu_path in menu_candidates:
        if menu_path.exists():
            menu_bg = pygame.image.load(menu_path).convert()
            menu_bg = pygame.transform.smoothscale(menu_bg, (WIDTH, HEIGHT))
            print(f"Menu background loaded: {menu_path.name}")
            break
    if menu_bg is None:
        # Safe fallback: the game still starts even if the menu image was not copied yet.
        menu_bg = bg.copy()

    # Animated title-menu frames: assets/menu_frames/frame_000001.png, ...
    # Reuse the numbered-frame loader, with the static menu image as a safe fallback.
    menu_frames = load_background_frames(
        ASSET_DIR / "menu_frames",
        menu_candidates[0] if menu_candidates[0].exists() else (ASSET_DIR / "arena.png"),
        (WIDTH, HEIGHT),
    )
    # If the loader had to fall back to arena.png but we already found a proper
    # static menu image, use that image instead.
    if len(menu_frames) == 1 and not (ASSET_DIR / "menu_frames").exists():
        menu_frames = [menu_bg]
    menu_frames, menu_loop_overlap = make_seamless_menu_frames(menu_frames)
    print(f"Menu animation: {len(menu_frames)} frame(s) at {MENU_FRAME_FPS:.1f} FPS")

    # Controller reference image supplied by the user.
    controller_guide = None
    for controller_path in (
        ASSET_DIR / "controller_guide.png",
        ASSET_DIR / "ps4_controller.png",
    ):
        if controller_path.exists():
            controller_guide = pygame.image.load(controller_path).convert_alpha()
            print(f"Controller guide loaded: {controller_path.name}")
            break

    player_frames = load_frames(ASSET_DIR / "player_frames")
    boss_frames = load_frames(ASSET_DIR / "boss_frames")

    # New sheet animations are used only by the blue player.
    player_action_set, player_action_fps = load_action_set(
        ASSET_DIR / "player_sheet_actions"
    )

    # Menu artwork reuses the same transparent fighter images as the battle.
    if player_action_set.get("idle"):
        menu_player_frame = player_action_set["idle"][0]
    else:
        menu_player_frame = player_frames[READY]
    menu_boss_frame = pygame.transform.flip(boss_frames[READY], True, False)

    memory = BehaviorMemory()
    ai = AdaptiveBossAI(memory)

    player = Fighter(
        "VANGUARD",
        370,
        player_frames,
        True,
        action_set=player_action_set,
        action_fps=player_action_fps,
    )
    boss = Fighter("NEMESIS", 910, boss_frames, False)

    # Animated fighting-game health bars: blue MC vs red boss.
    player_health_bar = AnimatedHealthBar(
        55, 28, 455, 30, player.max_health, BLUE, (40, 150, 255), reverse=False
    )
    boss_health_bar = AnimatedHealthBar(
        WIDTH - 510, 28, 455, 30, boss.max_health, RED, (255, 55, 55), reverse=True
    )

    player_rounds = 0
    boss_rounds = 0
    round_number = 1
    timer = ROUND_TIME

    state = "menu"
    state_t = 0.0
    menu_selected = 0
    menu_anim_t = 0.0
    background_anim_t = 0.0
    winner_text = ""
    resume_state = None
    sample_t = 0.0
    prev_movement_tag = None
    prev_block = False
    fight_announced = False

    def start_new_match():
        """Reset the fight and start a fresh match."""
        nonlocal player_rounds, boss_rounds, round_number
        nonlocal timer, winner_text, state, state_t, resume_state, fight_announced

        player_rounds = 0
        boss_rounds = 0
        round_number = 1
        player.reset(370)
        boss.reset(910)
        player_health_bar.sync(player.health)
        boss_health_bar.sync(boss.health)
        ai.reset_round()
        timer = ROUND_TIME
        winner_text = ""
        resume_state = None
        state = "countdown"
        state_t = 2.2
        fight_announced = False
        play_round_announcement(round_number)

    def activate_menu_selection(index):
        """Run the selected START GAME / OPTIONS / QUIT action."""
        nonlocal state, running, option_selected

        if index == 0:  # START GAME
            start_new_match()
        elif index == 1:  # OPTIONS
            option_selected = 0
            state = "settings"
        else:  # QUIT
            running = False

    def activate_option_selection(index):
        """Run an item from the OPTIONS submenu."""
        nonlocal state

        if index == 0:  # CONTROLLER
            state = "controls"
        else:  # BACK
            state = "menu"

    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 1 / 30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if state == "menu":
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key in (pygame.K_UP, pygame.K_w):
                        menu_selected = (menu_selected - 1) % len(menu_labels)
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        menu_selected = (menu_selected + 1) % len(menu_labels)
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        activate_menu_selection(menu_selected)

                elif state == "settings":
                    if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                        state = "menu"
                    elif event.key in (pygame.K_UP, pygame.K_w):
                        option_selected = (option_selected - 1) % len(option_labels)
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        option_selected = (option_selected + 1) % len(option_labels)
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        activate_option_selection(option_selected)

                elif state == "controls":
                    if event.key in (
                        pygame.K_ESCAPE,
                        pygame.K_RETURN,
                        pygame.K_BACKSPACE,
                    ):
                        state = "settings"

                else:
                    # ESC returns to the title screen instead of closing the game.
                    if event.key == pygame.K_ESCAPE:
                        memory.save()
                        resume_state = state
                        state = "menu"
                        menu_selected = 0
                        player.move_dir = boss.move_dir = 0
                        player.blocking = boss.blocking = False

                    if state == "fight":
                        if event.key == pygame.K_j and player.start_attack("jab"):
                            memory.record("jab")
                        elif event.key == pygame.K_k and player.start_attack("cross"):
                            memory.record("cross")
                        elif event.key == pygame.K_u and player.start_attack("kick"):
                            memory.record("kick")
                        elif event.key == pygame.K_i and player.start_attack("heavy_kick"):
                            memory.record("heavy_kick")
                        elif event.key == pygame.K_w and player.jump():
                            memory.record("jump")
                        elif event.key == pygame.K_SPACE:
                            keys = pygame.key.get_pressed()
                            direction = -1 if keys[pygame.K_a] else 1
                            if player.dash(direction):
                                memory.record("dash")
                        elif event.key == pygame.K_q:
                            keys = pygame.key.get_pressed()
                            if keys[pygame.K_a]:
                                direction = -1
                            elif keys[pygame.K_d]:
                                direction = 1
                            else:
                                direction = -player.facing
                            if player.dodge(direction):
                                memory.record("dodge")

                    if state == "match_over" and event.key == pygame.K_RETURN:
                        start_new_match()

            # --------------------------------------------------------
            # PS4 / controller button events
            # Face buttons use the SDL layout shared by native PS4 and
            # DS4Windows Xbox emulation: Cross=0, Circle=1, Square=2, Triangle=3.
            # --------------------------------------------------------
            if event.type == pygame.JOYBUTTONDOWN and controller is not None:
                btn = event.button
                pad_map = _ps4_buttons(controller)

                if state == "menu":
                    # Cross = select, Circle = back/quit.
                    if btn == 0:
                        activate_menu_selection(menu_selected)
                    elif btn == 1:
                        running = False
                    elif btn == 11:  # native PS4 D-pad up
                        menu_selected = (menu_selected - 1) % len(menu_labels)
                    elif btn == 12:  # native PS4 D-pad down
                        menu_selected = (menu_selected + 1) % len(menu_labels)

                elif state == "settings":
                    if btn == 0:  # X / Cross
                        activate_option_selection(option_selected)
                    elif btn in (1, pad_map["options"]):  # Circle / Options
                        state = "menu"
                    elif btn == 11:
                        option_selected = (option_selected - 1) % len(option_labels)
                    elif btn == 12:
                        option_selected = (option_selected + 1) % len(option_labels)

                elif state == "controls":
                    if btn in (0, 1, pad_map["options"]):
                        state = "settings"

                else:
                    # Options returns to title screen.
                    if btn == pad_map["options"]:
                        memory.save()
                        resume_state = state
                        state = "menu"
                        menu_selected = 0
                        player.move_dir = boss.move_dir = 0
                        player.blocking = boss.blocking = False

                    if state == "fight":
                        # PS4 face buttons:
                        # Square = jab, Triangle = cross, Cross/X = kick, Circle = heavy kick.
                        if btn == 2 and player.start_attack("jab"):
                            memory.record("jab")
                        elif btn == 3 and player.start_attack("cross"):
                            memory.record("cross")
                        elif btn == 0 and player.start_attack("kick"):
                            memory.record("kick")
                        elif btn == 1 and player.start_attack("heavy_kick"):
                            memory.record("heavy_kick")
                        elif btn == 11 and player.jump():
                            memory.record("jump")
                        elif btn == pad_map["r1"]:
                            direction = _controller_direction(controller)
                            if direction == 0:
                                direction = -player.facing if _controller_down(controller) else player.facing

                            if _controller_down(controller):
                                if player.dodge(direction):
                                    memory.record("dodge")
                            elif player.dash(direction):
                                memory.record("dash")

                    if state == "match_over" and btn == 0:
                        start_new_match()

            if state == "menu" and event.type == pygame.JOYHATMOTION:
                _, hy = event.value
                if hy > 0:
                    menu_selected = (menu_selected - 1) % len(menu_labels)
                elif hy < 0:
                    menu_selected = (menu_selected + 1) % len(menu_labels)

            if state == "settings" and event.type == pygame.JOYHATMOTION:
                _, hy = event.value
                if hy > 0:
                    option_selected = (option_selected - 1) % len(option_labels)
                elif hy < 0:
                    option_selected = (option_selected + 1) % len(option_labels)

            if state == "fight" and event.type == pygame.JOYHATMOTION:
                # D-pad up jumps.
                _, hy = event.value
                if hy > 0 and player.jump():
                    memory.record("jump")

            if state == "menu" and event.type == pygame.MOUSEMOTION:
                for i, rect in enumerate(menu_button_rects):
                    if rect.collidepoint(event.pos):
                        menu_selected = i
                        break

            if state == "menu" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, rect in enumerate(menu_button_rects):
                    if rect.collidepoint(event.pos):
                        menu_selected = i
                        activate_menu_selection(menu_selected)
                        break

            if state == "settings" and event.type == pygame.MOUSEMOTION:
                for i, rect in enumerate(option_button_rects):
                    if rect.collidepoint(event.pos):
                        option_selected = i
                        break

            if state == "settings" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, rect in enumerate(option_button_rects):
                    if rect.collidepoint(event.pos):
                        option_selected = i
                        activate_option_selection(option_selected)
                        break


        keys = pygame.key.get_pressed()
        menu_anim_t += dt
        background_anim_t += dt

        # Start music whenever the title menu is visible and fade it out when
        # leaving the menu for gameplay, controls, or settings.
        if state == "menu" and announcer_channel is not None and announcer_channel.get_busy():
            announcer_channel.stop()

        title_screen_state = state in ("menu", "settings", "controls")

        if menu_music_available:
            if title_screen_state and not menu_music_playing:
                try:
                    pygame.mixer.music.play(-1, fade_ms=MENU_MUSIC_FADE_MS)
                    menu_music_playing = True
                except pygame.error as exc:
                    print(f"Could not play menu music: {exc}")
                    menu_music_available = False
            elif not title_screen_state and menu_music_playing:
                pygame.mixer.music.fadeout(MENU_MUSIC_FADE_MS)
                menu_music_playing = False

        # Decode the MP4 at its native frame rate. The title menu has its own
        # artwork, so we only spend CPU on video when it can actually be seen.
        if state != "menu" and not use_png_background and video_background.available:
            video_background.update(dt)

        if state in ("menu", "controls", "settings"):
            # Gameplay is paused while the title/help screen is open.
            pass

        elif state == "countdown":
            state_t -= dt
            player.move_dir = 0
            boss.move_dir = 0
            player.blocking = boss.blocking = False

            # Say "Fight!" once, shortly before player control begins.
            if state_t <= 0.8 and not fight_announced:
                play_announcer("fight")
                fight_announced = True

            if state_t <= 0:
                state = "fight"
                timer = ROUND_TIME

        elif state == "fight":
            timer = max(0.0, timer - dt)

            # Player movement and guard.
            player.move_dir = 0
            player.crouching = False

            if player.can_act() and not player.attacking:
                # Keyboard and PS4 controller can be used at the same time.
                pad_dir = _controller_direction(controller)
                if keys[pygame.K_a]:
                    player.move_dir = -1
                elif keys[pygame.K_d]:
                    player.move_dir = 1
                elif pad_dir:
                    player.move_dir = pad_dir

                pad_map = _ps4_buttons(controller)
                if player.action_set:
                    # The new sheet intentionally uses no crouch animation.
                    player.crouching = False
                else:
                    player.crouching = bool(
                        player.on_ground
                        and (keys[pygame.K_s] or _controller_down(controller))
                    )
                player.blocking = bool(
                    player.on_ground
                    and (keys[pygame.K_l] or _joy_button(controller, pad_map["l1"]))
                )
            else:
                player.blocking = False


            # Track movement tendencies from the human player's point of view.
            sample_t -= dt
            if sample_t <= 0:
                sample_t = 0.22
                distance = abs(player.x - boss.x)
                memory.sample_distance(distance)

                tag = "idle"
                if player.move_dir:
                    toward = player.move_dir == (1 if boss.x > player.x else -1)
                    tag = "advance" if toward else "retreat"

                # Avoid recording idle/movement dozens of times if unchanged.
                if tag != prev_movement_tag or tag != "idle":
                    memory.record(tag)
                prev_movement_tag = tag

            if player.blocking and not prev_block:
                memory.record("block")
            prev_block = player.blocking

            # Always face each other.
            player.facing = 1 if boss.x > player.x else -1
            boss.facing = 1 if player.x > boss.x else -1

            ai.decide(boss, player, dt)

            player.update(dt)
            boss.update(dt)
            separate_fighters(player, boss)

            resolve_attack(player, boss)
            resolve_attack(boss, player)

            # Hit reactions and close attacks can change position in this same
            # frame, so enforce body spacing again before drawing.
            separate_fighters(player, boss)

            # Round end.
            if player.health <= 0 or boss.health <= 0 or timer <= 0:
                memory.save()

                # Only announce K.O. for a real health knockout, not a timer result.
                if player.health <= 0 or boss.health <= 0:
                    play_announcer("ko")

                if player.health == boss.health:
                    winner_text = "DRAW"
                elif boss.health <= 0 or player.health > boss.health:
                    player_rounds += 1
                    winner_text = "PLAYER WINS ROUND"
                else:
                    boss_rounds += 1
                    winner_text = "BOSS WINS ROUND"

                state = "round_over"
                state_t = 2.8

        elif state == "round_over":
            state_t -= dt
            player.update(dt)
            boss.update(dt)
            if state_t <= 0:
                if player_rounds >= ROUNDS_TO_WIN or boss_rounds >= ROUNDS_TO_WIN:
                    state = "match_over"
                    if player_rounds > boss_rounds:
                        winner_text = "PLAYER WINS MATCH"
                        player.pose = VICTORY
                        play_announcer("victor")
                    else:
                        winner_text = "BOSS WINS MATCH"
                        boss.pose = VICTORY
                        play_announcer("you_died")
                    memory.save()
                else:
                    round_number += 1
                    player.reset(370)
                    boss.reset(910)
                    player_health_bar.sync(player.health)
                    boss_health_bar.sync(boss.health)
                    ai.reset_round()
                    timer = ROUND_TIME
                    state = "countdown"
                    state_t = 2.2
                    fight_announced = False
                    play_round_announcement(round_number)

        # ----------------- DRAW -----------------
        if state == "menu":
            # Seamless forward loop: smoothly blend the end into the start.
            animated_menu_bg = get_menu_frame(menu_frames, menu_anim_t, menu_loop_overlap)
            draw_start_menu(
                screen,
                animated_menu_bg,
                menu_font,
                small,
                menu_button_rects,
                menu_labels,
                menu_selected,
                menu_anim_t,
            )
            pygame.display.flip()
            continue

        if state == "settings":
            options_bg = get_menu_frame(menu_frames, menu_anim_t, menu_loop_overlap)
            draw_options_menu(
                screen,
                options_bg,
                title_font,
                font,
                small,
                option_labels,
                option_selected,
                option_button_rects,
            )
            pygame.display.flip()
            continue

        if state == "controls":
            controller_bg = get_menu_frame(menu_frames, menu_anim_t, menu_loop_overlap)
            draw_controller_guide(
                screen,
                controller_bg,
                controller_guide,
                title_font,
                small,
            )
            pygame.display.flip()
            continue

        # Moving battle background. Prefer the numbered PNG frame sequence.
        if use_png_background:
            draw_animated_background(screen, background_frames, background_anim_t)
        elif video_background.available and video_background.surface is not None:
            video_background.draw(screen)
        else:
            draw_animated_background(screen, background_frames, background_anim_t)

        # Slight foreground shade for readability.
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 18))
        screen.blit(shade, (0, 0))

        player.draw(screen)
        boss.draw(screen)

        # Transparent HUD glass strip. The arena remains visible behind the health bars.
        hud_glass = pygame.Surface((WIDTH, 112), pygame.SRCALPHA)
        hud_glass.fill((8, 10, 16, 42))
        screen.blit(hud_glass, (0, 0))
        player_health_bar.update(dt, player.health)
        boss_health_bar.update(dt, boss.health)
        player_health_bar.draw(screen)
        boss_health_bar.draw(screen)


        p_name = font.render("VANGUARD", True, WHITE)
        b_name = font.render("NEMESIS - ADAPTIVE AI", True, WHITE)
        screen.blit(p_name, (55, 63))
        screen.blit(b_name, (WIDTH - 55 - b_name.get_width(), 63))

        timer_text = font.render(str(int(math.ceil(timer))), True, GOLD)
        screen.blit(timer_text, (WIDTH // 2 - timer_text.get_width() // 2, 28))

        rounds = small.render(
            f"Round {round_number}     Player {player_rounds} - {boss_rounds} Boss",
            True,
            WHITE,
        )
        screen.blit(rounds, (WIDTH // 2 - rounds.get_width() // 2, 67))

        # AI learning panel.
        attack_r, kick_r, block_r, jump_r, retreat_r = memory.summary()
        panel = pygame.Surface((365, 82), pygame.SRCALPHA)
        panel.fill((10, 12, 18, 175))
        screen.blit(panel, (WIDTH - 385, HEIGHT - 100))
        learned = small.render(
            f"AI learned: attack {attack_r*100:.0f}%  kick {kick_r*100:.0f}%  jump {jump_r*100:.0f}%",
            True,
            WHITE,
        )
        plan = small.render(f"Boss plan: {ai.last_plan}", True, GOLD)
        memory_line = small.render(
            f"block {block_r*100:.0f}%  retreat {retreat_r*100:.0f}%  samples {memory.session_actions}",
            True,
            GREY,
        )
        screen.blit(learned, (WIDTH - 370, HEIGHT - 90))
        screen.blit(plan, (WIDTH - 370, HEIGHT - 66))
        screen.blit(memory_line, (WIDTH - 370, HEIGHT - 42))

        controls = small.render(
            "A/D Move   W Jump   S Crouch   SPACE Dash   J/K Punch   U/I Kick   L Block",
            True,
            WHITE,
        )
        screen.blit(controls, (24, HEIGHT - 32))

        if state == "countdown":
            text = big.render("FIGHT!" if state_t < 0.8 else f"ROUND {round_number}", True, WHITE)
            screen.blit(text, (WIDTH // 2 - text.get_width() // 2, 190))

        elif state == "round_over":
            text = font.render(winner_text, True, GOLD)
            screen.blit(text, (WIDTH // 2 - text.get_width() // 2, 180))

        elif state == "match_over":
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 120))
            screen.blit(overlay, (0, 0))
            text = big.render(winner_text, True, GOLD)
            screen.blit(text, (WIDTH // 2 - text.get_width() // 2, 220))
            again = font.render("ENTER = Rematch   |   ESC = Main Menu", True, WHITE)
            screen.blit(again, (WIDTH // 2 - again.get_width() // 2, 310))

        pygame.display.flip()

    memory.save()
    video_background.close()
    if pygame.mixer.get_init():
        pygame.mixer.music.stop()
    pygame.quit()


if __name__ == "__main__":
    main()
