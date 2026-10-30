# Web research and agent permissions

## What it does
When the local data (NOAA, GBIF, OECD, the wiki, the live APIs) cannot answer a question, a separate
**researcher** agent can search the web. It is **off by default**:

- **Ask page:** tick "Search the web if the local data can't answer". This needs the AI writer.
- **Scenario page:** tick the box under "Tell us about you". Any question in the text box (a sentence ending in `?`)
  is answered from the real U.S. data and shown as **Your question**, separately from the fictional scenario.
  The web is used only if that local answer fails and the box is ticked.

How a search runs:
1. **Trusted sites first**, up to 2 searches. These are the sites in `data_real/web_trusted_domains.txt`:
   NOAA, FDA, USDA, Census, BLS, FAO, OECD, the fishery councils and the state agencies.
2. **The open web** only if step 1 found nothing usable. It uses the remaining searches and never reaches
   the sites in `data_real/web_blocked_domains.txt` (social media, forums, paste sites).
3. **At most 3 searches per question**, about $0.01 each plus tokens. A live test cost $0.012 to $0.024.

## What is kept
Python throws away everything the researcher writes. It keeps only the exact quoted text of each citation, with
its link and title. A quote is dropped if any of these apply:
- the page is not https
- the site is blocked
- the quote is a table dump rather than words
- the quote came back from a non-trusted site during the trusted pass

The writer may reword the quotes under the usual grounding check. Every number it uses must appear in a quote,
and advice or hype words are rejected. Answers are labelled **WEB (trusted source, quoted)** or
**WEB (open web, quoted)**, with confidence Medium or Low and a link for every quote. Web quotes never
change the scenario's numbers. The scenario agents receive a words-only version.

Contact details are removed from the question before it is sent. Questions the local data answers, non-U.S.
questions, and questions that look like instructions never go to the web. The scenario question and its answer
are not written to the saved run.

## Permission boundaries (`src/fishmarket/permissions.py`)
`llm.py` checks each request against this table **before** it is sent, so nothing is paid when a check fails.
No prompt can widen an agent's limits.

| Agent | Role | May use | Web | Max output tokens | Calls per run | Max cost per call |
|---|---|---|---|---|---|---|
| agent1 | planner | `submit_plan`, `choose_entry` | no | 800 | 6 | $0.03 |
| agent2 | analyst | `submit_analysis` | no | 3,000 | 3 | $0.10 |
| summary | writer | `submit_summary` | no | 1,600 | 8 | $0.05 |
| researcher | researcher | web search only (no structured tools) | yes, 3 searches per run | 1,500 | 2 | $0.12 |

Unknown agent names are refused. Every web search must carry either the allowed-sites list or the blocked-sites
list. The per-run $0.25 cap and the global $34 stop still apply on top of these limits.
