# Wiki Conventions (v3)

Operating rules every wiki edit must follow. This is the rulebook. All detail lives here. `wiki_schema.md` is the slim system prompt; this file is the reference.

---

## 1. Page Naming

- **Slug format**: `hyphen-case-slug.md`. No underscores. Korean slugs allowed.
- **Decision pages**: `decision-YYYY-MM-DD-<slug>.md`. Date prefix keeps the corpus navigable.
- **Comparisons**: `<a>-vs-<b>.md`.
- **All pages** live in a flat `3_Wiki/` directory. No subdirectories.

## 2. Frontmatter: How to fill each tag

### `kind` (7 options)

Choose one and only one. This is the most important tag -- it determines how the page is read and linked.

| Value | When to use | Example |
|---|---|---|
| `concept` | A reusable idea, method, theory, principle. Can be used across many contexts. | `bayes-theorem.md` |
| `entity` | A specific thing: person, tool, organization, model, paper, event. | `deepseek-v4.md` |
| `source-record` | One raw source distilled. A single course chapter, paper, conversation, book note. This is a Zettelkasten literature note -- it captures one source faithfully. | `attention-is-all-you-need.md` |
| `project` | The user's ongoing project. Describes what, why, how. | `orot-council.md` |
| `decision` | A decision the user made. Weighs tradeoffs, documents rationale, preserves the "why." | `decision-2026-05-18-zero-base-facet-redesign.md` |
| `insight` | An extracted insight or realization. More personal than a concept, more reusable than a decision. | `why-agents-need-boundaries.md` |
| `comparison` | A vs B side-by-side analysis. Weighs pros, cons, tradeoffs. | `cnn-vs-transformer.md` |

**Key distinction**: `source-record` vs `concept`. A source-record is bound to one source. A concept is extracted from multiple sources and stands on its own. This is the Zettelkasten distinction baked into the schema.

### `form` (2 options)

| Value | When to use |
|---|---|
| `prose` | Flowing explanation. The default for most pages. |
| `index` | Link/navigation hub. A table of contents. Independent of `kind`. |

### `topics` (0-5 keywords)

Pick from `ontology/topics.md` (canonical list and aliases). New topics are allowed -- lint warns but doesn't block. Vocabulary grows naturally.

Aliases are resolved at lint time: `fp` → `functional-programming`.

### `subject` (path from subject tree)

Must be a valid path in `ontology/subject-tree.md`. Path notation means renaming or splitting a domain is done by editing the tree file -- pages don't need rewriting.

A page that genuinely spans two subjects can list both: `subject: [ml/agents, study/research-methods]`.

### `source-types` (list, always)

Where this page's knowledge came from. Valid values:

`course`, `conversation`, `paper`, `article`, `docs`, `book`, `video`, `podcast`, `external`

A page can be informed by multiple source types: `source-types: [course, paper, conversation]`.

### `domains` (automatic -- never write by hand)

Top-level of the subject path. Lint computes this. Example: `subject: statistics/distribution` → `domains: [statistics]`.

### `confidence` (3 options)

| Value | When |
|---|---|
| `high` | Well-established, peer-reviewed, or personally verified multiple times. |
| `medium` | Reasonably confident. From a reliable source or one verification. |
| `low` | Speculative, single source, or early thinking. Flag for later review. |

### `created` and `updated`

ISO dates. `created` is set once. `updated` changes every time the page is touched.

---

## 3. Prose Relations

Relations are written as natural language phrases in the body, not as structured frontmatter.

Recognized patterns (lint validates wikilinks inside them):

- `builds on [[x]]` -- dependency chain
- `contradicts [[y]]` -- flagged conflict
- `instance of [[category]]` -- is-a relationship
- `applies to [[project-slug]]` -- concept used in practice
- `decided [[x]] over [[y]] when [[constraint]]` -- selection decision
- `failed when [[condition]]` -- failure mode of a decision
- `trade-off: [[a]] vs [[b]]` -- weighed comparison

Bottom-up vocabulary. If a pattern appears enough times to feel like a real category, add it to this list.

---

## 4. Decision Page Body Template

Decision pages (`kind: decision`) follow this template. Empty sections are dropped -- use only what applies.

```
## Context
What was the situation? Background facts the reader needs.

## Problem
What needed solving? What was the tension?

## Decision
What was decided? One sentence.

## Alternatives
What else was considered? Why were they rejected?

## Rationale
Why this choice? What evidence or principles?

## Mechanism
How does it work in practice? Concrete steps.

## Outcome
What happened? Was it the right call?

## Failure mode
When does this decision break? Under what conditions?

## Iteration
What changed since the original decision?

## Invariant
What must stay true for this decision to remain valid?

## Reusability
When would you apply this same pattern again?

## Related
Wikilinks to connected pages. Use prose relations.

## Next action
What to do next. Concrete and time-bound.
```

---

## 5. index.md Curation Rules

`index.md` is the curated entry point catalog -- NOT an automatic enumerator.

- **Entry points only**: Hand-picked pages that serve as good starting points for each domain.
- **Not exhaustive**: The page list is in `ontology/wiki-manifest.json`.
- **Updated on every ingest/save**: Add new entry points when they genuinely improve navigation.
- **Format**: `## Domain Name` sections with `- [[page-slug|Title]] — one-line summary` entries.

---

## 6. log.md Audit Trail

Append-only. One line per action. Machine-parseable format:

```
## [YYYY-MM-DD HH:MM] <action-type> | <Page or Source Title> -- <summary>
```

Action types: `ingest`, `create`, `update`, `save`, `synapse`, `lint`, `curate`, `promote`, `migrate`.

---

## 7. Post-Ingest Cleanup

After creating wiki pages from `raw/` sources:

- `raw/conversations/`: Keep capture summaries permanently. `_transcripts/` held for 90 days then auto-archive.
- `raw/courses/{slug}/`: Move to archive on course completion.
- `raw/articles/`: Keep permanently (lightweight text).
- `raw/assets/`: Keep only referenced images. Unreferenced assets flagged by lint.

---

## 8. Schema Evolution Policy

**Who can change what:**

| Change | Authority |
|---|---|
| New kind value | User only (trunk schema change) |
| New form value | User only |
| New source-types value | User only |
| New topic in `ontology/topics.md` | LLM autonomous (lint warns if premature) |
| New subject path in tree | User approval required |
| New prose relation pattern | Bottom-up: frequent use → add to CONVENTIONS |
| New lint check | User proposal + LLM implement |

**LLM autonomous actions**: For low-impact additions -- a new topic, a new concept page, an obvious alias. Lint catches premature additions on a 30-day window.

**LLM never**: Adds new `kind`/`form` values, modifies subject-tree.md without approval, runs destructive operations (delete, move, rename without confirmation).

---

## 9. External Skills Worth Chaining

When appropriate, the agent should suggest chaining in these external skills (if available in the user's environment):

- `paper-summarizer`: For distilling academic papers into source-records
- `lecture-translator`: For converting course videos to structured notes
- `deep-research`: For multi-source synthesis across a domain

None are required. The agent handles all of these natively.
