---
description: Work out what boson got wrong in a run of your design (bad netlist decisions + current issues) and build an anonymized, leak-checked debug bundle to send partcl.
argument-hint: [--run-dir run] [--netlist f --sdc f --timing f --timing-json f --qor f --journal f ...] [--literal NAME] [--pdk-node "7 nm"] [--include-netlist]
---

Run the `boson-netlist-debug` skill on the arguments below. Follow its
rules exactly: anonymize first and write REPORT.md only from the
anonymized copies, keep `name_map.json` local, run the leak check and do
not ship a bundle that fails it, show the customer MANIFEST.md and
REPORT.md before they send anything, and never upload anything yourself.
If there is no decision journal yet, give them the rerun recipe from the
skill. Finish with the skill's reporting format.

Arguments: $ARGUMENTS
