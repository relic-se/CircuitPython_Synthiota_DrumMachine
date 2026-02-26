# SPDX-FileCopyrightText: 2026 Cooper Dalrymple (@relic-se)
#
# SPDX-License-Identifier: GPLv3

from audiodelays import Echo
from audiofilters import Distortion, DistortionMode, Filter, Phaser
from audiofreeverb import Freeverb
import displayio
import microcontroller
from synthio import Biquad, FilterMode, LFO, Synthesizer
from terminalio import FONT
from vectorio import Rectangle

from adafruit_display_text.label import Label
from relic_keymanager import Sequencer
from relic_synthiota import Synthiota
from relic_synthvoice.percussive import Kick, Snare, ClosedHat, OpenHat, HighTom, MidTom, FloorTom, Ride

MODE_EDIT = 0
MODE_SEQUENCER = 1
MODE_PLAY = 2
MODE_LEDS = (0xFF0000, 0x0000FF, 0x00FF00)

# improve performance with an overclock
microcontroller.cpu.frequency = 300_000_000

# hardware and audio
displayio.release_displays()
synthiota = Synthiota(
    sample_rate=48000,
    channel_count=1,
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
            frequency=synthiota.sample_rate//2,
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

sequencer = Sequencer(length=16, tracks=8)

def sequencer_enabled(active: bool) -> None:
    if not active:
        for voice in VOICES:
            voice.release()
sequencer.on_enabled = sequencer_enabled

def sequencer_press(notenum: int, velocity: float) -> None:
    VOICES[notenum-1].press(velocity)
sequencer.on_press = sequencer_press

def sequencer_release(notenum: int) -> None:
    VOICES[notenum-1].release()
sequencer.on_release = sequencer_release

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
)

left_slider_parameter = Parameter(
    effect_filter.filter, "frequency",
    20, synthiota.sample_rate / 2, 2000,
    shape=4, smoothing=0.05, window=False,
)

right_slider_parameter = Parameter(
    effect_filter.filter, "Q",
    0.7, 4, 0.7,
    shape=2, smoothing=0.05, window=False,
)

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

pages_group = displayio.Group()
root_group.append(pages_group)

for i, (title, parameters) in enumerate(PAGES):
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

page = None
def set_page(index: int = 0) -> None:
    global page
    index = min(max(index, 0), len(PAGES)-1)
    if index == page:
        return
    if page is not None:
        for label, parameter in PAGES[page][1]:
            parameter.deactivate()
    page = index
    for i, page_group in enumerate(pages_group):
        page_group.hidden = i != page
set_page()

track = None
def set_track(index: int = 0) -> None:
    global track
    index = min(max(index, 0), sequencer.tracks-1)
    if index == track:
        return
    track = index
    # TODO: set track label
set_track()

mode = None
def set_mode(value: int = 0) -> None:
    global mode, page
    value = min(max(value, 0), 2)
    if value == mode:
        return
    mode = value
    pages_group.hidden = mode != MODE_PLAY
    if mode == MODE_PLAY:
        for label, parameter in PAGES[page][1]:
            parameter.deactivate()
    synthiota.mode_leds = [MODE_LEDS[i] * (i == mode) for i in range(3)]
set_mode(MODE_PLAY)

last_touched_steps = [False] * 16
while True:
    synthiota.update()
    sequencer.update()
    touched_steps = synthiota.touched_steps

    step_leds = [0] * 16

    # change mode
    if synthiota.up_button.pressed:
        set_mode(mode + 1)
    if synthiota.down_button.pressed:
        set_mode(mode - 1)

    # update sliders
    left_slider_parameter.update(synthiota.left_slider.value)
    right_slider_parameter.update(synthiota.right_slider.value)

    # toggle sequencer
    if synthiota.encoder_button.pressed:
        sequencer.active = not sequencer.active

    if mode == MODE_PLAY:

        # change page
        if synthiota.encoder.position != 0:
            set_page(page + (1 if synthiota.encoder.position < 0 else -1))
            synthiota.encoder.position = 0

        # update page parameters
        for i, (label, parameter) in enumerate(PAGES[page][1]):
            parameter.update(synthiota.pots[i])

        # sample playback
        for i, voice in enumerate(VOICES):
            if touched_steps[i] and not last_touched_steps[i]:
                voice.press()
            elif not touched_steps[i] and last_touched_steps[i]:
                voice.release()

        # update parameter ui bars
        for i in range(min(8, len(pages_group[page][2]))):
            bar = pages_group[page][2][i]
            bar.height = int(BAR_HEIGHT * PAGES[page][1][i][1].raw_value)
            bar.y = synthiota.display.height - bar.height

    elif mode == MODE_EDIT:

        # change sequencer track
        if synthiota.encoder.position != 0:
            set_track(track + (1 if synthiota.encoder.position < 0 else -1))
            synthiota.encoder.position = 0

        # edit sequence with step touches
        for i, value in enumerate(touched_steps):
            if value and not last_touched_steps[i]:
                if not sequencer.has_note(i, track):
                    sequencer.set_note(i, track+1, track=track)
                else:
                    sequencer.remove_note(i, track)
        
        # draw step positions
        for i in range(16):
            if sequencer.has_note(i, track):
                step_leds[i] = 0xFF0000

    elif mode == MODE_SEQUENCER:

        # control bpm with encoder
        if synthiota.encoder.position != 0:
            sequencer.bpm += -synthiota.encoder.position
            synthiota.encoder.position = 0

    # update leds
    step_leds[sequencer.position] = 0x00FF00
    for i in range(16):
        if touched_steps[i]:
            step_leds[i] = 0xFFFF00
    synthiota.step_leds = step_leds

    last_touched_steps[:] = touched_steps
