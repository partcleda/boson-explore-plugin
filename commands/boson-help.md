---
description: Find or understand a boson command, flag, app variable or error through boson's own help, before assuming a gap.
argument-hint: <what you are trying to do, or the error text / message ID>
---

Run the `boson-help` skill on the question below. If there is an error,
read its message ID first (`help <MESSAGE-ID>`); then climb the discovery
ladder — `help search <words>`, `help <command>` (then `options|examples`),
`help` topics, `describe_command <glob>`, and the shipped reference at
`/opt/boson/docs/reference` — until the command or answer is found. Only
if the whole ladder comes up empty, record the gap with
`wish <verb> -why "..."` and say so. Never conclude boson lacks a
capability without finishing the ladder.

Arguments: $ARGUMENTS
