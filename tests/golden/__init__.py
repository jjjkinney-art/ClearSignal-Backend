"""
Phase 9G · Slice 5B — golden-set evaluation harness for dossier injection.

This package is a LOCAL / OFFLINE evaluation harness.  It NEVER touches
production traffic and NEVER enables ``DOSSIER_INJECTION_ENABLED``.  It builds
the same prior-dossier block that Slice 5A shadow-measures, injects it into a
controlled synthesis prompt under three conditions (OFF / TRUE / POISON), and
scores whether the injected prior improves continuity without anchoring the
model against fresh evidence.

Modules
-------
golden_set : per-ticker dossier fixtures + the golden question set.
poison     : adversarial-prior builder (confident prior that contradicts
             this cycle's evidence).
harness    : 3-way prompt assembly + model runner (skips cleanly with no key).
scoring    : the rubric, aggregate gates, and PASS/FAIL report formatter.
run_eval   : CLI entry point that wires it together.
"""
