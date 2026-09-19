# SignalWeave live-demo recording

This is one continuous browser run. A scheduled Growth Monitoring Agent wakes up, types its
question, SignalWeave connects the evidence and runs the query path, then the
bundle returns to Codex for a Slack notification and human acknowledgement.
Each part gets its own focused page, with a fast transition inside the same
browser frame. Record the browser window at 1080p with the cursor visible and
the page at 100% zoom. Upload
`live-demo-voiceover.txt` to ElevenLabs and use the generated track as the edit
timing reference.

## Recording path

| Time | On screen | Narration beat |
| --- | --- | --- |
| 0:00–0:05.2 | Codex types the question; after `QUERY SENT`, steps 1 → 2 → 3 → 4 pop in | “At six, a Codex workflow…” |
| 0:05.2–0:08.2 | The free-form card resolves into a Jev call shape with weighted probabilities | “The card carries the human context…” |
| 0:08.2–0:12.5 | Graph arms connect one-by-one: CARD → SQL → Jev → source nodes | “Then SignalWeave connects the dots…” |
| 0:12.5–0:16.5 | Evidence resolves into one bundle with confidence and instruction | “The bundle comes back…” |
| 0:16.5–0:22 | Codex types to Slack and leadership replies | “Codex types the heads-up… Ack…” |

## Recording notes

- Do not cut to title cards, stock footage, or a logo outro.
- Start with the scheduled run already waking up. No one is typing a request to start it.
- Keep the cursor optional; the visual story is carried by the typed agent query, card shape, evidence motion, and Slack response.
- The generated browser demo is 22 seconds: `promo/render_agent_demo.py` writes `artifacts/promo/signalweave-agent-demo.mp4`.
- Keep the browser frame continuous; use fast page transitions, not a deck or title-card cut.
- The numbers are clearly sample-run values from the Northstar demo environment; do not present them as customer results.
