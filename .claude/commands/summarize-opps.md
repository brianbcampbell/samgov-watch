Summarize SAM.gov opportunity JSON files in `state/opps/`.

For each `state/opps/{id}.json` (skip any file ending in `_ext.json`):
1. Check if `state/opps/{id}_ext.json` already exists AND contains a non-empty `summary` field. If yes, skip — already processed.
2. Read `{id}.json`.
3. Generate:
   - `summary`: 2–3 sentences. What is being procured, who needs it, and any notable scope or constraints. Be specific — avoid vague language like "various services".
   - `deliverables`: a list of strings, each being a concrete thing the contractor must provide or do. Extract from the description. If none are stated explicitly, infer from context.
4. Write `state/opps/{id}_ext.json` with this structure:
   ```json
   {
     "summary": "...",
     "deliverables": ["...", "..."],
     "processed_at": "<ISO timestamp>"
   }
   ```

Work through files one at a time. After writing each `_ext.json`, move to the next. This way if you are interrupted, completed files are already saved and will be skipped on the next run.

If a JSON file has no `Description` field or an empty one, write the `_ext.json` with `summary` set to `""` and `deliverables` set to `[]` so it is not retried.

Do not modify `{id}.json` files.
