# Falcon Semantica S1 Example

This example proves one Falcon-style Porsche decision chain through Semantica's generic ContextGraph decision/provenance primitives.

## Boundary

Allowed Falcon/Porsche-specific files:

```text
examples/falcon/porsche_decision_fixture.json
examples/falcon/porsche_decision_s1.py
examples/falcon/s1-result.schema.json
tests/integration/test_falcon_*_s1.py
```

Do not add Porsche ontology, Falcon quest classes, NPC definitions, Godot state, or Consultant/XP concepts to Semantica core.

## DecisionStorageRule

Store a Decision node only when an event:

- changes scope;
- changes an artifact;
- changes priority;
- rejects a meaningful alternative;
- requires human approval;
- triggers downstream work;
- creates material risk;
- creates a reusable precedent.

Do not store routine agent steps, transient execution logs, or progress messages as Decision nodes.

## S1/S2/S3 handoff

S1 returns `GO` only if all five deterministic queries pass from stored records. S2 can add precedent search. S3 can visualize the resulting Decision Graph in Falcon Academy.
