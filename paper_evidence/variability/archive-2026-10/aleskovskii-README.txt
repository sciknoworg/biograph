Each run_NN/ holds one draw: entities.json, events.json, relations.json,
sources.json and subject.json, copied out of the sandbox that produced it.

Which model produced it, at which commit, against which extraction-core
SHA-256, is in ../manifest.json keyed by document and run number -- never
inferred from the folder name. That is the one thing the 2026-09-04
comparison failed to record.
