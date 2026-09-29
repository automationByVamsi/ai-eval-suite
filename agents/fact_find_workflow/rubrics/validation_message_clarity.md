Evaluate whether the agent's complaint-validation response clearly explains
why the input was rejected (or, on the success path, progresses without a
false InvalidComplaintId message).

Score higher when:
- Invalid inputs get an explicit InvalidComplaintId (or equivalent) explanation
- The message states the required format: NC prefix + 8 digits, single reference only
- Success-path answers do not falsely claim the reference is invalid

Score lower when:
- The rejection reason is vague or missing
- A valid NC######## reference is incorrectly rejected
- Extra prose obscures the validation outcome
