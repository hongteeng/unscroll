# Unscroll: the first 20 posts

This is an acceptance worksheet, not a record of completed testing. Fill it in on the owner's Mac using the owner's actual saved posts.

Choose 20 posts that include spoken tips, accents or jargon, text-heavy videos, carousels, little/no text, overlapping ideas and at least one unavailable post if present. Note the post IDs before processing. The mix should test the app's limits rather than only easy videos.

| Post ID | Type | Caption complete? | Speech/slides complete? | Important ideas retained? | Specifics exact? | Nothing invented? | Category fits? | Outcome / fix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | | | | | | | | |
| 02 | | | | | | | | |
| 03 | | | | | | | | |
| 04 | | | | | | | | |
| 05 | | | | | | | | |
| 06 | | | | | | | | |
| 07 | | | | | | | | |
| 08 | | | | | | | | |
| 09 | | | | | | | | |
| 10 | | | | | | | | |
| 11 | | | | | | | | |
| 12 | | | | | | | | |
| 13 | | | | | | | | |
| 14 | | | | | | | | |
| 15 | | | | | | | | |
| 16 | | | | | | | | |
| 17 | | | | | | | | |
| 18 | | | | | | | | |
| 19 | | | | | | | | |
| 20 | | | | | | | | |

For each post, watch the original once and compare it with the full extracted source and entry. Check speech, every carousel slide, brief overlays, names, numbers, tools, frameworks and explicitly stated actions. Record missing source text separately from a summarisation error. A source quote match is not a substitute for this check.

Acceptance proposed in the PRD: no important idea omitted and nothing invented in all 20. A thin entry is acceptable when the original is thin and the limitation is clearly labelled. A capture failure is not a faithful entry; it needs a visible logged failure and a recovery route.

## Operational checks

- Pause during processing; finish the current job and leave the rest queued.
- Stop and restart the app; resume without re-extracting posts with saved source text.
- Retry an AI failure; preserve the extraction.
- Inspect the application-support folder: media from extraction attempts is removed; text remains.
- Select two posts for permanent downloads; verify only those two appear under Downloads/Unscroll.
- Approve categories only after reviewing the proposal. Check one primary placement and any extra placements.
- Rename and merge categories; verify every entry survives and one primary placement remains per categorised post.
- Reimport the same export; verify no duplicate post entries or unnecessary rewrites.
- Capture new saves with the extension; compare discovered IDs with TikTok and report any missing links or collection metadata.

## Ten search queries

Write these before trying search. Include paraphrases that do not use the video's exact words. Record expected IDs and whether they appear near the top. Time one representative find task against the proposed 30-second target.

| Query | Expected post ID(s) | Returned near top? | Seconds / notes |
| --- | --- | --- | --- |
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |
| 10 | | | |

Record Mac model, macOS version, peak memory (Activity Monitor), elapsed processing time, Whisper model, Claude model, input/output token totals and actual API spend for the batch. Use the measured numbers to decide whether to process the full backlog or adjust extraction/model settings first.
