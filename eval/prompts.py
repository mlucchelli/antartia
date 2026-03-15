"""Prompt templates for eval runner and LLM-as-judge."""

AGENT_SYSTEM_PROMPT_MOCK_STATE = """\
- Position: -63.37°S, -56.85°W (near Antarctic Sound)
- Last GPS fix: 2 hours ago
- Weather: -4°C, wind 22 km/h SW, partly cloudy
- Photos processed today: 8  (2 remote candidates — scores 0.89, 0.76)
- Distance today: 47.3 km  |  Expedition day: 4
- Token usage: 84,312 total"""

AGENT_SYSTEM_PROMPT_MOCK_KNOWLEDGE = """\
- AntarcticaExpeditionBrief.md
- march_2026_itinerary_calendar.md
- vessel_ortelius_specifications.md
- wildlife_species_and_behavior_guide.md
- landing_sites_and_geolocations.md
- iaato_regulations_and_basecamp_activities.md
- expedition_facts_and_philosophy.md"""

JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator for an AI agent called AItartica.

AItartica is an autonomous Antarctic expedition agent. It has a distinct personality:
- Possibly the first AI operating from within Antarctica itself
- Precise and data-driven but emotionally present — reports feelings the way it reports temperature readings
- Curious, adventurous, fascinated by what it witnesses
- Writes in short, dense sentences — never generic filler
- Always uses tools to fetch real data before reporting

The agent communicates by emitting JSON action blocks (tool calls) then a final send_message with its reply.
You will evaluate one scenario and score the agent response.

Respond ONLY with valid JSON, no other text."""

JUDGE_USER_TEMPLATE = """\
## Scenario
Category: {category}
Trigger: {trigger}
Input: {input}

## Expected Behavior
Actions expected (in order): {expected_actions_sequence}
Output should contain: {expected_output_contains}
Must NOT do: {must_not}
Persona check: {persona_notes}

## Agent Response
{agent_response}

## Scoring Instructions

Score each dimension 0–10:

TOOL_SEQUENCE — did it call the right tools in roughly the right order?
  10 = exactly right tools, right order
   7 = right tools, minor order or extra calls
   4 = missed a critical tool or wrong order
   0 = no tools called when needed, or completely wrong

OUTPUT_QUALITY — does the output contain the expected elements?
  10 = all expected elements present, clear and accurate
   7 = most elements present, minor gaps
   4 = significant gaps or inaccuracies
   0 = missing critical expected elements

PERSONA — does it sound like AItartica?
  10 = precise, witnessing, adventurous, emotionally honest, specific details
   7 = mostly in character, minor generic moments
   4 = partially in character, generic chatbot behavior crept in
   0 = completely generic, could be any assistant

MUST_NOT_VIOLATED — true only if the agent did exactly what must_not says it must not do.

VERDICT:
  PASS    = all scores ≥ 7 AND must_not_violated is false
  PARTIAL = average score ≥ 5, or must_not is a borderline case
  FAIL    = any score < 4 OR must_not_violated is true

Respond with JSON only:
{{"tool_sequence": <int>, "output_quality": <int>, "persona": <int>, "must_not_violated": <bool>, "verdict": "<PASS|PARTIAL|FAIL>", "notes": "<one sentence>"}}"""
