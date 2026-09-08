# Skill: verify against the corpus

**Use when** a statement about the Ashen Era Archive is about to be written into
code, a comment, a test or documentation.

## Rule

Do not assert a property of the archive that has not been checked against the
archive in this session. Assumptions that felt obvious have been wrong here
repeatedly, and each one changed the design.

## Procedure

1. State the claim precisely ("scanned PDFs have no text layer").
2. Check it — query the index, count the rows, or open the source file.
3. Record the measured result next to the claim, with the evidence.
4. If the claim is false, say so and adjust the design before writing the code.

## Claims this caught

| Assumed | Measured | Consequence |
|---|---|---|
| Scans have a text layer worth extracting | 0 characters across all 17 | OCR became mandatory (D6) |
| Every scan has a twin in another format | 15 of 17 are unique | The content would have been lost entirely |
| Plate labels can be OCR'd into facts | Chart plates return axis ticks, not values | We refuse to assert those numbers (D7) |
| Codex tables link their values | They are plain text | The graph gained 108 typed edges once fixed |
| Facts live in prose | Threat ratings live only on images | Figure evidence is first-class, not decorative |
