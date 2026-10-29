# Second Brain: the rules

This folder is its owner's **second brain**: Markdown notes, the source of truth about their life. Plain text, no apps, no subscriptions: if the tool dies, the files live.

@AGENTS.md

## Three operations

- **Ingest:** something new comes in (a decision, a conversation, an idea, a book). Update the note where it fits or create a new one, add it to `README.md` and to its area's `index.md`, connect it with related notes and write one line in `Log.md`.
- **Query:** the owner asks. Answer only from the notes, citing them with links. If something is not there, say so instead of filling in. If the answer is worth keeping, propose a new note.
- **Maintenance:** look for broken links, notes nobody links to, contradictions and data that changed. Show the list before touching anything.

## Every note

```markdown
---
type: concept
area: identity
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tag1, tag2]
---

# Title

> One sentence that captures the idea.

## Section

Content...

## Connections

- [Another Note](../05-work/Another%20Note.md): why they connect
```

- File names are natural titles with spaces (`Morning Routine.md`). Links are relative, with spaces as `%20`.
- Every note has a `## Connections` section with at least one link: those links are the graph the AI follows.
- One note per idea. Short and true beats long and invented.
