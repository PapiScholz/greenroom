# ADR-0002: Classify by whole words and hide unclassified skills behind their own gate

- **Status:** accepted
- **Date:** 2026-10-18

## Context

`classify()` counted a keyword as a hit whenever it appeared as a substring of the skill's name and description. Short keywords fired inside other words: `orm` in "performance", `ui` in "build" and "guide", `api` in "fastapi". Ties between two families left the skill unclassified even when its name made the family obvious (`gsap-react`). Measured against the author's registry (254 skills already placed in families), the substring rule put 31 skills in another family.

Unclassified skills went to `pending` and stayed visible. ADR-0001 accepted that as the conservative choice: never hide what has no gate. Each one cost context in every session, the cost greenroom exists to remove.

## Decision

A keyword must start a word, and a keyword of 3 letters or less must be the whole word. That is the rule the prompt log already used, now shared in `keyword_pattern()`. A tie between families goes to the one with more hits in the skill's name (frontmatter name and folder). Still tied, the skill is pending.

Pending skills are hidden like any family member, behind a generated gate (`gate-other`, or `pending_gate` in the registry) that exists only while something is pending. Skills with `disable-model-invocation: true` and no family are not pending: they cost no context and need no gate.

## Alternatives considered

| Alternative | Why it was rejected |
|---|---|
| Whole words plus a list of common endings (`s`, `ing`, `ation`…) | Measured: one fewer skill in another family and five more left pending than the shared rule, and a second rule to keep in sync with the prompt log |
| Let the model classify pending skills at session start | Costs tokens on every session that has pending skills and needs a write path from the model to `registry.json` |
| Keep pending skills visible (ADR-0001) | Every unclassified skill costs context in every session |

## Consequences

Against the same 254 skills: 158 land in their current family (161 with substrings), 70 go to pending (62) and 26 to another family (31). A skill in the wrong gate is harder to find than one behind `gate-other`, so more pending and fewer wrong is the better side of the trade. Most of the remaining errors come from keywords that several families share (`design`, `agent`, `workflow`), which is tuning in `registry.json`, not the matcher.

A skill stays in exactly one family. Listing it in two gates when the race is close was measured on 2026-10-18 against the same 254 skills (keywords tuned since: 171 same, 71 pending, 12 wrong): errors fell from 12 to 6, but 77 skills would sit in two or more gates (25 in three or more), 105 extra gate rows, and `usage` attributes each skill to one gate. Instead the sync note flags the close race (`new -> design (close: motion): x`): 70 of the 183 classified skills would carry the note, among them 7 of the 12 wrong ones. The remaining errors are placement choices the keywords cannot express (a design skill kept in the motion family), fixed by moving the skill by hand.

No skill is ever unreachable: a pending skill is still in the user's `/` menu, `gate-other` lists it, and `check` counts it as covered. The map asks the model to suggest a family for each pending skill once.

Supersedes the "unclear skills stay visible" consequence of ADR-0001.

## Sources

- [Claude Code skills: `skillOverrides`](https://code.claude.com/docs/en/skills)
