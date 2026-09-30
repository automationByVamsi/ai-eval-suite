"""
Synthesizer: generate test cases ("goldens") for any agent from source documents.

    SOURCE  ─────────────►  GENERATOR  ───────────────►  OUTPUT TEMPLATE
    where documents come     DeepEval Synthesizer, one     the JSON shape of this agent's
    from: Athena, files,     call per document x style,    test cases (synth.yaml `output:`)
    JSON, any API            CORTEX model, checked +
                             de-duplicated

  generator.py         the two commands: make sources, make goldens
  settings.py          reads and validates agents/<agent>/synth/synth.yaml and styles/*.md
  documents.py         picks documents (GROUP= / IDS=), fetches them, caches them
  output_template.py   turns a generated question/answer into the agent's test case JSON
  sources/             one file per source type (athena_mcp, files, json_records, ...)

Everything for one agent lives in agents/<agent>/synth/ — a new agent or a new case shape needs
no change here. A new kind of source is one new file in sources/.
"""
