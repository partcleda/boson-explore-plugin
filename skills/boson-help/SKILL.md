---
name: boson-help
description: Use whenever a boson command, flag, app variable or error has to be found or understood — "how do I X in boson", "what boson command / flag does X", "boson errored with STA-101", "boson can't do X", "boson doesn't support X", "find the boson command for X", "is there an app variable for X" — and always before concluding boson lacks a capability or reporting an issue to partcl. boson documents itself; this skill is the discovery ladder through its built-in help, search, message IDs, JSON command descriptions and shipped reference.
---

# Finding the boson command (ask boson first)

boson documents itself, and most "boson can't do X" is really "I didn't
find the command". Climb this ladder before concluding boson lacks a
capability, working around it, or reporting anything to partcl.

## The ladder

1. **Read the error.** Every boson error carries a message ID (e.g.
   `STA-101`); `help <MESSAGE-ID>` explains it, and many errors name the
   fixing command in their own text. Read the error before searching
   anywhere else.
2. **`help search <words>`** — real keyword search (multi-term AND, with
   plural stemming) over command names, descriptions, user procs and app
   variables. Globs work too (`help report_*`). Example: told not to use
   tie cells, `help search tie` finds `set_tiehi` / `set_tielow`, and
   `help search dont_use` finds `remove_dont_use`.
3. **`help <command>`** for the found command, and
   `help <command> options|examples|all` for its flags and worked
   examples. `help <app_variable>` works the same way for app variables.
4. **Browse by task.** `help` alone is a home page of task topics
   (synthesis, timing, constraints, files, physical, queries, scripting)
   plus an Explore block; `help topics`, `help <topic>`,
   `help <topic> all` and `help all` walk the whole surface.
5. **`describe_command <glob>`** — JSON command descriptions built for
   scripts and agents: typed arguments, categories, read/write effect.
6. **Grep the shipped reference.** Every install carries the full Markdown
   reference at `/opt/boson/docs/reference` (`commands.md`,
   `sdc-constraints.md`, `attributes.md`, `app-variables.md`,
   `messages.md`); `boson reference <dir>` regenerates it from the
   installed binary.

A mistyped or guessed command gets fuzzy "Did you mean X? Try `help X`"
steering — read it; it is usually right.

## In batch

The scripts in this plugin run boson non-interactively; help works the
same way there:

```sh
echo 'help search tie cells' | boson --no-color
```

or put the help commands in a one-line script run with `-f`.

## When the ladder comes up empty

Only then record the gap: `wish <verb> -why "<what you needed>"` logs a
request for a missing command (it is a logger, not a search; when the
command exists under another name, `wish` names it). Exhaust the ladder
first — a gap that `help search` would have answered is not a finding,
not a workaround, and not an issue for partcl.

## Skill feedback (last step, every run)

Before reporting, record what this skill did not cover: every step you took
that it did not prescribe (with the reason), a question it had no method
for, guidance that failed or misled (with the error), and inputs or coverage
you needed and did not get.

```sh
F=<plugin>/feedback/skill_feedback.py
python3 $F init --skill boson-help --question "<the user's question>"
python3 $F add off_script|missing_framework|wrong_guidance|missing_input --what "..." [--why "..."] [--error "..."]
python3 $F outcome yes|partly|no --iterations <n>
python3 $F render
```

End the report with the rendered section, "none" lines included. Then offer
once to share it: `python3 $F share` (add `--map name_map.json` when a debug
bundle's map exists) writes an anonymized copy and a `submit.tcl` that sends
it with boson's `report_feedback` when the user sources it. Never send or
source it without the user's explicit yes. See `feedback/README.md`.
