Put custom judge rubrics here, one Markdown file per metric, written in plain English:
what a good answer looks like, what should lower the score.

Then use it in agent.yaml:

    metrics:
      tone: {rubric: rubrics/tone.md, threshold: 0.8}

By default the judge sees `question` and `answer`. To judge something else, point a field
at it (`answer: rewritten_query`) or add more with `needs: [question, answer, contexts]`.
