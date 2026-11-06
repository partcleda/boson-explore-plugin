# Runtime attribution and repair snapshots

Use this method when a flow is slow or its runtime gap against a reference is
unexplained. Follow the checkout's experiment and resource rules. A diagnostic
capture with shared hardware or extra snapshot work is not a controlled runtime
comparison.

1. Preserve the measured binary, inputs, settings, and uninstrumented result.
   Capture a Chrome/Perfetto trace with
   `boson --runtime-trace=run.trace.json -f flow.tcl`. The attached `=` is
   intentional. Use the runtime profiler, rather than treating a Tcl-only
   `--profile` or an STA aggregate report as full runtime coverage.
2. Read `bosonRuntimeProfile.wallUs`, `spansRecorded`, `spansDropped`, and
   `stages` in the saved JSON. Rank exclusive `selfUs`; use inclusive
   `totalUs` to understand an enclosing pass. Never add an enclosing pass's
   inclusive time to its children's time. Summed thread work can exceed wall
   time. A high timing-update count does not establish that STA dominates.
3. Trace the largest cost to its operation and work count. If an optimizer
   is opaque, instrument its pass boundary and then its dominant candidate
   generation, characterization, pricing, or validation boundary. Keep
   diagnostic changes separate from changes to candidate selection. Do not
   add full STA calls just to obtain a finer runtime breakdown.
4. Open the original trace in Perfetto and check import diagnostics as well
   as the producer's dropped-span count. Overlapping complete events can be
   dropped by the viewer even when the producer retained every event. Check
   the affected event names and verify counts for the important stages;
   retain the original trace and disclose any relevant loss. Locate the
   overlapping intervals' producer instead of filtering away the warning.
5. For topology inspection, enable `synth_graph_snapshot_dir` before compile.
   Confirm the snapshot manifest contains the required stages. A repairer's
   in-memory snapshot option is insufficient if its shell adapter discards
   those snapshots. Prefer streaming the input, every pass in every round,
   rollback, and final output into the existing graph-snapshot sink. Include
   no-change states. An attempted state followed by rollback is not the
   committed output. Avoid retaining every graph in RAM or re-running STA
   at each pass boundary solely to export topology.
6. Compare upstream WLO snapshots as well as mapped repair states. Identical
   upstream WLO graphs establish where differences begin; mapped-cell edits
   do not by themselves establish a changed word-level optimization.
7. When the user authorizes private hosting or review uploads, keep measured
   runs on the required experiment hosts and import their completed artifacts
   into the viewer. Preserve constraints, library restrictions, final master
   audits, and independent verification. Viewer import/queue elapsed is not
   compiler runtime: expose the original measurement separately and label
   both clocks. Verify the hosted trace opens and the stage files render in
   a browser. Private hosting does not authorize public sharing or feedback.

Coverage keys: `runtime-trace`, `exclusive-costs`, `candidate-work-counts`,
`viewer-import-quality`, `repair-pass-snapshots`, `rollback-snapshots`,
`upstream-wlo-identity`, `measurement-vs-import-time`, `hosted-viewer`.
