# SPDX-FileCopyrightText: 2026 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3

from audiodelays import Echo
from audiofilters import Distortion, DistortionMode, Filter, Phaser
from audiofreeverb import Freeverb
import displayio
import json
import microcontroller
import os
from synthio import Biquad, FilterMode, LFO, Synthesizer
from terminalio import FONT
import time
from vectorio import Rectangle

from adafruit_display_text.label import Label
from relic_keymanager import Sequencer
from relic_synthiota import Synthiota
from relic_synthvoice.percussive import Kick, Snare, ClosedHat, OpenHat, HighTom, MidTom, FloorTom, Ride

STEREO = False

MODE_EDIT = 0
MODE_SEQUENCER = 1
MODE_PLAY = 2
MODE_LEDS = (0xFF0000, 0x0000FF, 0x00FF00)

# improve performance with an overclock
microcontroller.cpu.frequency = 320_000_000 if STEREO else 300_000_000

# hardware and audio
displayio.release_displays()
synthiota = Synthiota(
    sample_rate=32000 if STEREO else 48000,
    channel_count=2 if STEREO else 1,
)

ARGS = {
    "buffer_size": synthiota.buffer_size,
    "sample_rate": synthiota.sample_rate,
    "channel_count": synthiota.channel_count,
}

effect_reverb = Freeverb(
    roomsize=0.7,
    damp=0.3,
    **ARGS,
)
synthiota.mixer.play(effect_reverb)

effect_echo = Echo(
    freq_shift=True,
    **ARGS,
)
effect_reverb.play(effect_echo)

effect_phaser = Phaser(
    frequency=LFO(offset=1000, scale=600),
    **ARGS,
)
effect_echo.play(effect_phaser)

effect_distortion = Distortion(
    mode=DistortionMode.CLIP,
    soft_clip=True,
    **ARGS,
)
effect_phaser.play(effect_distortion)

effect_filter = Filter(
    filter=tuple([
        Biquad(
            frequency=synthiota.sample_rate/2,
            mode=FilterMode.LOW_PASS,
        ) for i in range(2)
    ]),
    **ARGS,
)
effect_distortion.play(effect_filter)

synth = Synthesizer(
    sample_rate=synthiota.sample_rate,
    channel_count=synthiota.channel_count,
)
effect_filter.play(synth)

# Voices

VOICES = (
    Kick(synth),
    Snare(synth),
    ClosedHat(synth),
    OpenHat(synth),
    HighTom(synth),
    MidTom(synth),
    FloorTom(synth),
    Ride(synth),
)

VOICE_NAMES = (
    "KICK",
    "SNRE",
    "HHCL",
    "HHOP",
    "HTOM",
    "MTOM",
    "FTOM",
    "RIDE",
)

def voice_press(voice: int = None, velocity: float = 1.0) -> None:
    if 0 <= voice < len(VOICES):
        VOICES[voice].press(velocity)
        if voice in {2, 3}: # Hat
            for note in VOICES[((voice + 1) % 2) + 2].notes:
                synth.release(note)

# Sequencer

SEQUENCES = 16

sequencer = Sequencer(length=16, tracks=8)

def sequencer_press(notenum: int, velocity: float) -> None:
    voice_press(notenum-1, velocity)
sequencer.on_press = sequencer_press

def sequencer_release(notenum: int) -> None:
    VOICES[notenum-1].release()
sequencer.on_release = sequencer_release

sequences = [[[None for k in range(sequencer.length)] for j in range(sequencer.tracks)] for i in range(SEQUENCES)]
current_sequence = 0
next_sequence = None

def dump_sequence() -> None:
    global sequences, current_sequence
    for i in range(sequencer.tracks):
        for j in range(sequencer.length):
            if sequencer.has_note(j, i):
                sequences[current_sequence][i][j] = sequencer.get_note(j, track=i)[0]
            else:
                sequences[current_sequence][i][j] = None

def load_sequence(index: int = None, dump: bool = True) -> None:
    global sequences, current_sequence, next_sequence
    if index is not None:
        next_sequence = index
    if next_sequence is None:
        return

    if dump:
        dump_sequence()

    next_sequence = min(max(next_sequence, 0), SEQUENCES)
    
    for i in range(sequencer.tracks):
        for j in range(sequencer.length):
            if sequences[next_sequence][i][j] is None:
                sequencer.remove_note(j, track=i)
            else:
                sequencer.set_note(j, sequences[next_sequence][i][j], track=i)

    current_sequence = next_sequence
    next_sequence = None

def sequencer_enabled(active: bool) -> None:
    if not active:
        for voice in VOICES:
            voice.release()
        load_sequence()
sequencer.on_enabled = sequencer_enabled

def sequencer_loop(pos: int) -> None:
    load_sequence()
sequencer.on_loop = sequencer_loop

# parameters
PARAM_WINDOW = 0.01

def map_value(in_value: float, in_minimum: float, in_maximum: float, out_minimum: float, out_maximum: float, clamp: bool = True) -> float:
    if clamp:
        in_value = min(max(in_value, in_minimum), in_maximum)
    return (in_value - in_minimum) / (in_maximum - in_minimum) * (out_maximum - out_minimum) + out_minimum

class Parameter:

    def __init__(self, obj: object = None, name: str = "", minimum: float = 0, maximum: float = 1, value: float = None, shape: int = 1, smoothing: float = 0.5, round: bool = False, window: bool = True):
        self._object = obj
        self._name = name
        self._minimum = minimum
        self._maximum = maximum
        self._shape = max(shape, 1)
        self._smoothing = min(max(smoothing, 0.001), 1)
        self._round = round
        self._window = window

        self.value = minimum if value is None else value
        self._last_value = None

        self._setattr()  # set initial value

    def _get_map_value(self, value: float = None) -> float:
        if value is None:
            value = self._value
        value = min(max(value, 0), 1)
        if self._shape > 1:
            value = pow(value, self._shape)
        value = map_value(value, 0, 1, self._minimum, self._maximum)
        if self._round:
            value = round(value)
        return value
    
    def _setattr(self) -> None:
        if self._object is not None and len(self._name):
            if isinstance(self._object, tuple):
                for obj in self._object:
                    setattr(obj, self._name, self._map_value)
            else:
                setattr(self._object, self._name, self._map_value)
        
    def deactivate(self) -> None:
        self._active = False

    def update(self, value: float) -> None:
        if value is None:
            return
        if self._last_value is None or abs(value - self._last_value) >= PARAM_WINDOW:
            self._last_value = value
        if not self._window or abs(self._value - self._last_value) < PARAM_WINDOW:
            self._active = True
        if self._active:
            self._value += (self._last_value - self._value) * self._smoothing

            # update mapped value
            self._map_value = self._get_map_value()

            # update object
            self._setattr()
    
    @property
    def value(self) -> float:
        return self._map_value
    
    @value.setter
    def value(self, value: float) -> None:
        self._map_value = min(max(value, self._minimum), self._maximum)

        # calculate relative value
        self._value = map_value(self._map_value, self._minimum, self._maximum, 0, 1)
        if self._shape > 1:
            self._value = pow(self._value, 1 / self._shape)  # invert smoothing

        self._setattr()
        self.deactivate()

    @property
    def raw_value(self) -> float:
        return self._value
    
    @raw_value.setter
    def raw_value(self, value: float) -> None:
        self._value = value
        self._map_value = self._get_map_value()

        self._setattr()
        self.deactivate()


PAGES = (
    tuple([
        (
            VOICE_NAMES[i],
            tuple(filter(
                lambda x: x is not None,
                (
                    ("TUN", Parameter(VOICES[i], "tune", -12, 12, 0)),
                    ("LVL", Parameter(VOICES[i], "amplitude", value=0.5)),
                    ("DCY", Parameter(VOICES[i], "decay_time", -1, 1, 0)),
                    ("PAN", Parameter(VOICES[i], "pan", -1, 1, 0)) if STEREO else None,
                )
            ))
        )
        for i in range(len(VOICES))
    ]),
    (
        (
            "SQNC",
            (
                ("BPM", Parameter(sequencer, "bpm", 40, 240, 120, round=True)),
                ("SRT", Parameter(sequencer, "loop_start", 0, 15, 0, round=True)),
                ("END", Parameter(sequencer, "loop_end", 1, 16, 16, round=True)),
            )
        ),
    ),
    (
        (
            "DIST",
            (
                ("GN", Parameter(effect_distortion, "drive", value=0.5)),
                ("MX", Parameter(effect_distortion, "mix")),
            )
        ),
        (
            "PHSR",
            (
                ("PR", Parameter(effect_phaser.frequency, "rate", 0.1, 8, 1, 3)),
                ("PF", Parameter(effect_phaser, "feedback", value=0.5)),
                ("PM", Parameter(effect_phaser, "mix")),
            )
        ),
        (
            "ECHO",
            (
                ("TM", Parameter(effect_echo, "delay_ms", 25, 500, 250, 2)),
                ("DC", Parameter(effect_echo, "decay", value=0.25)),
                ("MX", Parameter(effect_echo, "mix")),
            )
        ),
        (
            "RVRB",
            (
                ("SZ", Parameter(effect_reverb, "roomsize", value=0.7)),
                ("DMP", Parameter(effect_reverb, "damp", value=0.3)),
                ("MX", Parameter(effect_reverb, "mix")),
            )
        ),
    ),
)

left_slider_parameter = Parameter(
    effect_filter.filter, "frequency",
    20, synthiota.sample_rate / 2, synthiota.sample_rate / 2,
    shape=4, smoothing=0.05, window=False,
)

right_slider_parameter = Parameter(
    effect_filter.filter, "Q",
    0.7, 4, 0.7,
    shape=2, smoothing=0.05, window=False,
)

# saving
SAVE_LOCATION = "/synthiota-drum-machine.json"

def get_parameter_data() -> dict:
    data = {}
    for pages in PAGES:
        for i, (title, parameters) in enumerate(pages):
            data[title] = {}
            for j, (label, parameter) in enumerate(parameters):
                data[title][label] = parameter.value
    return data

def get_save_data() -> dict:
    global sequences
    return {
        "parameters": get_parameter_data(),
        "sequences": sequences,
    }

def save(dump: bool = True) -> None:
    if dump:
        dump_sequence()

    with open(SAVE_LOCATION, "w") as f:
        json.dump(get_save_data(), f)

# ui
TITLE_HEIGHT = 20
LABEL_HEIGHT = 10
BAR_HEIGHT = synthiota.display.height-TITLE_HEIGHT-LABEL_HEIGHT
BAR_WIDTH = synthiota.display.width//8

root_group = displayio.Group()
synthiota.display.root_group = root_group
palette = displayio.Palette(2)
palette[0] = 0x000000
palette[1] = 0xFFFFFF

root_group.append(Label(
    font=FONT, text="Drums", color=0xFFFFFF, scale=2,
    anchored_position=(0, TITLE_HEIGHT//2),
    anchor_point=(0, 0.5),
))

status_label = Label(
    font=FONT, text="", color=0xFFFFFF, scale=2,
    anchored_position=(synthiota.display.width//2, (synthiota.display.height-TITLE_HEIGHT)//2+TITLE_HEIGHT),
    anchor_point=(0.5, 0.5),
)
status_label.hidden = True
root_group.append(status_label)

modes_group = displayio.Group()
root_group.append(modes_group)

for pages in PAGES:
    pages_group = displayio.Group()
    pages_group.hidden = True
    modes_group.append(pages_group)

    for i, (title, parameters) in enumerate(pages):
        page_group = displayio.Group()
        page_group.hidden = True
        pages_group.append(page_group)

        page_group.append(Label(
            font=FONT, text=title, color=0xFFFFFF, scale=2,
            anchored_position=(synthiota.display.width-3, TITLE_HEIGHT//2),
            anchor_point=(1, 0.5),
        ))

        label_group = displayio.Group()
        page_group.append(label_group)

        bar_group = displayio.Group()
        page_group.append(bar_group)
        
        for j, (label, parameter) in enumerate(parameters):
            label_group.append(Label(
                font=FONT, text=label, color=0xFFFFFF,
                anchored_position=(j*BAR_WIDTH+BAR_WIDTH//2, TITLE_HEIGHT+LABEL_HEIGHT//2),
                anchor_point=(0.5, 0.5),
            ))
            bar_group.append(Rectangle(
                pixel_shader=palette, color_index=1,
                width=BAR_WIDTH, height=BAR_HEIGHT,
                x=j*BAR_WIDTH, y=TITLE_HEIGHT+LABEL_HEIGHT,
            ))

mode = None
page = [None] * len(PAGES)
def set_page(mode_index: int = None, page_index: int = None) -> None:
    global page, mode
    mode_index = mode if mode_index is None else min(max(mode_index, 0), len(PAGES)-1)
    page_index = page[mode_index] if page_index is None else min(max(page_index, 0), len(PAGES[mode_index])-1)
    if page_index is None:
        page_index = 0
    if mode_index == mode and page[mode_index] == page_index:
        return
    if mode is not None and page[mode] is not None:
        for label, parameter in PAGES[mode][page[mode]][1]:
            parameter.deactivate()
    mode = mode_index
    page[mode] = page_index
    for i, pages_group in enumerate(modes_group):
        pages_group.hidden = i != mode
        for j, page_group in enumerate(pages_group):
            page_group.hidden = i != mode or j != page[mode]
    synthiota.mode_leds = [MODE_LEDS[i] * (i == mode) for i in range(3)]
set_page(mode_index=MODE_PLAY, page_index=0)

# load save data
try:
    os.stat(SAVE_LOCATION)
except OSError:
    pass
else:
    modes_group.hidden = True
    status_label.text = "Loading..."
    status_label.hidden = False
    synthiota.pot_leds = [0xFFA500] * 8
    synthiota.audio.stop()

    with open(SAVE_LOCATION, "r") as f:
        data = json.load(f)

        if "parameters" in data and isinstance(data["parameters"], dict):
            for pages in PAGES:
                for i, (title, parameters) in enumerate(pages):
                    if title in data["parameters"]:
                        for j, (label, parameter) in enumerate(parameters):
                            if label in data["parameters"][title] and isinstance(data["parameters"][title][label], float):
                                parameter.value = data["parameters"][title][label]

        if "sequences" in data and isinstance(data["sequences"], list):
            for i in range(min(len(sequences), len(data["sequences"]))):
                if isinstance(data["sequences"][i], list):
                    for j in range(min(len(sequences[i]), len(data["sequences"][i]))):
                        if isinstance(data["sequences"][i][j], list):
                            for k in range(min(len(sequences[i][j]), len(data["sequences"][i][j]))):
                                if data["sequences"][i][j][k] is None or isinstance(data["sequences"][i][j][k], int):
                                    sequences[i][j][k] = data["sequences"][i][j][k]
            load_sequence(0, dump=False)
    
    status_label.text = "Complete!"
    synthiota.pot_leds = [0x00FF00] * 8
    time.sleep(1)
    status_label.hidden = True
    modes_group.hidden = False
    synthiota.leds.fill(0)
    synthiota.audio.play(synthiota.mixer)
    synthiota.mixer.play(effect_reverb)

# loop

last_touched_steps = [False] * 16
while True:
    synthiota.update()
    sequencer.update()
    touched_steps = synthiota.touched_steps

    # handle save
    if synthiota.up_button.long_press or synthiota.down_button.long_press:

        # stop sequencer and audio
        sequencer.active = False
        synthiota.audio.stop()
        
        # clear leds
        synthiota.leds.fill(0)

        # show label
        modes_group.hidden = True
        status_label.text = "Saving..."
        status_label.hidden = False

        # indicate leds
        synthiota.pot_leds = [0xFFA500] * 8

        # perform save
        save()

        # indicate success
        status_label.text = "Complete!"
        synthiota.pot_leds = [0x00FF00] * 8
        time.sleep(1)

        # reset ui
        status_label.hidden = True
        modes_group.hidden = False
        synthiota.leds.fill(0)

        # continue audio
        synthiota.audio.play(synthiota.mixer)
        synthiota.mixer.play(effect_reverb)

        continue # reset loop

    step_leds = [0] * 16

    # change mode
    if synthiota.up_button.pressed:
        set_page(mode_index=mode + 1)
    if synthiota.down_button.pressed:
        set_page(mode_index=mode - 1)

    # update sliders
    left_slider_parameter.update(synthiota.left_slider.value)
    right_slider_parameter.update(synthiota.right_slider.value)

    # toggle sequencer
    if synthiota.encoder_button.pressed:
        sequencer.active = not sequencer.active
    if synthiota.encoder_button.long_press and not sequencer.active:
        sequencer.position = 0

    # change page
    if synthiota.encoder.position != 0:
        set_page(page_index=page[mode] + (1 if synthiota.encoder.position < 0 else -1))
        synthiota.encoder.position = 0

    # update page parameters
    for i, (label, parameter) in enumerate(PAGES[mode][page[mode]][1]):
        parameter.update(synthiota.pots[i])

    # update parameter ui bars
    for i in range(min(8, len(modes_group[mode][page[mode]][2]))):
        bar = modes_group[mode][page[mode]][2][i]
        bar.height = int(BAR_HEIGHT * PAGES[mode][page[mode]][1][i][1].raw_value)
        bar.y = synthiota.display.height - bar.height
    
    if mode == MODE_PLAY:

        # sample playback
        for i, voice in enumerate(VOICES):
            if touched_steps[i] and not last_touched_steps[i]:
                voice_press(i)
            elif not touched_steps[i] and last_touched_steps[i]:
                voice.release()

        # indicate voices
        for i in range(len(VOICES)):
            step_leds[i] = 0xFF0000

    elif mode == MODE_EDIT:

        # edit sequence with step touches
        for i, value in enumerate(touched_steps):
            if value and not last_touched_steps[i]:
                if not sequencer.has_note(i, page[MODE_EDIT]):
                    sequencer.set_note(i, page[MODE_EDIT]+1, track=page[MODE_EDIT])
                else:
                    sequencer.remove_note(i, page[MODE_EDIT])
        
        # draw step positions
        for i in range(16):
            if sequencer.has_note(i, page[MODE_EDIT]):
                step_leds[i] = 0xFF0000

    elif mode == MODE_SEQUENCER:

        # allow sequence selection
        for i, value in enumerate(touched_steps):
            if value and not last_touched_steps[i] and i != current_sequence:
                next_sequence = i
                if not sequencer.active:
                    load_sequence()
                break  # only allow first sequence selection

        # indicate sequence length
        for i in range(16):
            if sequencer.loop_start <= i < sequencer.loop_end:
                step_leds[i] = 0xFF0000

        # indicate current sequence
        step_leds[current_sequence] = 0x0000FF

        if next_sequence is not None:
            step_leds[next_sequence] = 0xFFFF00

    # update leds
    step_leds[sequencer.position] = 0x00FF00
    for i in range(16):
        if touched_steps[i]:
            step_leds[i] = 0xFFFF00
    synthiota.step_leds = step_leds

    last_touched_steps[:] = touched_steps
