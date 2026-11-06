# Agent guide

What the plugin holds and how to add a mode or a skill is in
[README.md](README.md).

## boson

Every skill here drives boson, partcl's GPU EDA toolkit. Its source is in
`partcleda/boson`, the boson source repo, for partcl staff.

- The skills depend on boson's Tcl commands, flags and app variables: in the
  `.tcl` files under `skills/*/scripts/`, in the Tcl the Python scripts there
  write, and in the command shapes in each `SKILL.md` and `references/*.md`.
  `feedback/` sends through boson's `report_feedback`. A renamed command or a
  changed flag, default or report format in boson can break a skill, so when
  you change one or it fails, check it against the current boson release
  (`help <command>` in the boson shell, and the release notes).
- partcl's boson developers debug boson results with these same skills. A
  skill fix or a new check found that way comes back here as a PR.
- boson's release container ships this plugin pinned to a commit, without
  `demo/` or any `tests/` directory. It refuses a pin with a `.lib`, `.lef`,
  `.def`, `.gds`, `.sdc` or `.spef` file anywhere else, so keep such fixtures
  under `tests/`.
