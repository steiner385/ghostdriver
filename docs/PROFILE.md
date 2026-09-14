# The profile document

A profile is a JSON file about one target: what must never be actuated,
how the target wants to be typed at, how it shows it is busy, and what a
probe may touch. It lives in the operator directory, never in a
repository (D60): `GHOSTDRIVER_OPERATOR_DIR/profiles/<name>.json`, and
`attach(profile_path="<name>")` finds it by bare name.

Everything here is optional. A profile with only a `denylist` is a
complete profile. `ghostdriver check-profile <name>` reads one back and
says what the tool will make of it.

## `matched_profile`

A label for the target's technology profile, for reports and results
(`"L1"` for a Delphi/VCL x86 target; `"unknown"` when unset). Never a
product or vendor name.

## `denylist`

Controls no session may actuate, however it was asked. Three forms of
entry, checked against every actuation before anything is sent:

| entry | matches | example |
|---|---|---|
| a caption pattern (fnmatch, case-insensitive) | a window's caption, or an element's name | `"*delete*"`, `"*submit*"` |
| an identity (D57) | an element by what it is: type-qualified name, automation id, or type and position under its host | `"TabItem:Change Log"`, `"MenuItem#3@ToolbarWindow32"` |
| a place (D72) | any actuation aimed inside a rectangle of the named window | see below |

A place is for the controls that have neither caption nor identity: a
grid cell, a row in an owner-drawn list, a painted toolbar button.

```json
{"within": "class=TsfDBGrid visible=true",
 "region": {"left": 0, "top": 24, "right": 600, "bottom": 44},
 "note": "the release row"}
```

`within` is a locator; `region` is in the client coordinates of the
window it names -- the frame `click at={x, y}` uses and a `capture` of
that window shows, so the numbers are read off a capture. The window is
resolved at the moment of each actuation, so the region follows it. A
control that scrolls inside its window is not tracked; what can be named
is better denied by name. A malformed place fails the profile load.

## `input_sensitivity`

How the target's surfaces react to typing speed. Each note:

```json
{"cadence": "fast_human", "source": "declared", "surface": "web",
 "evidence": "hosted web content counts input events", "recorded": "2026-09-02"}
```

`cadence` is `robot` (queue speed) or `fast_human` (~80 ms a character,
uneven); `surface` is `*` or a surface kind from `surfaces`; `source` is
`declared` (a person wrote it) or `learned` (a session ran the
differential and the tool wrote it, via `record_input_sensitivity`).
The tool picks the cadence for a control from the most specific note.

## `busy_indicator` (D69)

How the target shows it is still working, so an actuation result can say
`still_arriving` and `wait_idle` can wait for the screen to catch up
with the action. One of two forms:

```json
"busy_indicator": {"locator": "class=TProgressBar visible=true", "all_windows": true}
```

busy while the locator resolves; or

```json
"busy_indicator": {"region": {"left": 9, "top": 878, "right": 400, "bottom": 895},
                   "ink_above": 0.05}
```

busy while that screen-coordinate region renders more than `ink_above` of
non-background pixels -- for a status strip that paints its progress bars
rather than making them windows. Set the threshold from two captures, one
idle and one busy.

## `posted_click_only` (D#122)

Window classes whose click is the posted message and nothing else:

```json
"posted_click_only": ["TsfCommandButton", "TsfSpeedButton*"]
```

`fnmatch` patterns against the control's window class. For a plain HWND
control the ladder tries the UIA Invoke pattern first and the posted click
second; a toolkit that answers Invoke slowly, or not at all, costs that
rung's timeout and then a second delivery of a click the posted message
already made. A class listed here skips the pattern rung, and the click
result says so (`route_pinned`). A declared route beats a learned one
(D35): list a class after seeing `tiers_attempted: [1, 3]` and a slow
click, not before.

## `posted_click_only` (D#122)

Window classes whose click is the posted message and nothing else:

```json
"posted_click_only": ["TsfCommandButton", "TsfSpeedButton*"]
```

`fnmatch` patterns against the control's window class. For a plain HWND
control the ladder tries the UIA Invoke pattern first and the posted click
second; a toolkit that answers Invoke slowly, or not at all, costs that
rung's timeout and then a second delivery of a click the posted message
already made. A class listed here skips the pattern rung, and the click
result says so (`route_pinned`). A declared route beats a learned one
(D35): list a class after seeing `tiers_attempted: [1, 3]` and a slow
click, not before.

## `safe_controls`

What `probe_phase2` may actuate to learn how the target's controls
respond, and nothing else. Each entry carries its proof:

```json
{"locator": "class=TsfCommandButton text=\"Expand All\"",
 "expect": {"locator": "class=TPanel text=\"Instructions\"", "text": "..."},
 "note": "expands the instruction blocks; nothing is committed"}
```

`expect` is the same shape the actuation tools take. A control on both
this list and the denylist is a contradiction and is refused.

## What the tool writes back

`probe_grid` and `probe_phase2` merge what they learned (`grid_strategy`,
`grid_evidence`, `actuation_map`, `focus_behavior`) into the profile,
touching no other key. `record_input_sensitivity` appends a learned note.
Nothing the tool writes ever touches `denylist` or `safe_controls`.

## Retired keys

`environment_allowlist` is no longer read: which targets may be driven is
decided at attach, by the person, for the life of the target process
(R1, R1a). `check-profile` warns when it sees one.
