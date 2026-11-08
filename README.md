# Unscroll

An extension-first development build of your saved-TikTok organiser. The library is packaged inside the Chrome extension and opens in a full Chrome tab. A local Mac helper performs transcription, OCR, storage and selected downloads. Made for an Apple Silicon Mac with 8 GB RAM, English posts, and temporary media that is removed after extraction.

**Status: runnable development build, awaiting installation and a 20-post acceptance test on your Mac.** This is source code with local launchers, not a signed, standalone Mac application. The real TikTok capture, Claude calls and Mac dependency installation have not been exercised here.

## Start on your Mac

1. Unzip this folder somewhere permanent, such as `~/Applications/Unscroll`. Keep all files together.
2. Install [Homebrew](https://brew.sh) if you do not already have it.
3. Open `Setup.command`. It installs Python 3.12, ffmpeg, Tesseract and the Python dependencies, then asks for your **Claude API key** in Terminal. Typing the key is hidden. A Claude chat subscription does not supply API credits. Choose a model ID available to your API account; the default is configurable.
4. Run **Enable-Automatic-Helper.command** to start the local helper now and at future logins. Keep this project folder in place. Alternatively, use `Start.command` for manual startup and leave that Terminal open.
5. Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select this project’s `extension` folder.
6. Click the Unscroll toolbar icon, paste the local pairing token printed during setup, and choose **Open your library**. The library opens as an extension page in a full Chrome tab. You can also paste the token on its connection screen.

If you miss the setup token, open **http://127.0.0.1:8765**, choose Settings and copy it. This local page remains available as a settings/recovery interface. **Disable-Automatic-Helper.command** removes automatic startup while preserving your data. A restarted helper preserves the queue and waits for you to resume it.

If Finder does not run the launchers, open Terminal in this folder and run `bash Setup.command`, followed by `bash Start.command`. If macOS blocks a downloaded script, review its source and use macOS's normal Open/Privacy & Security controls. No system security settings need to be disabled.

The first transcription and semantic-search runs download model files. Later inference runs locally. Setup needs an internet connection, several GB of free space and permission to install Homebrew packages. Other open applications will affect performance; the 8 GB configuration uses one background worker and two CPU inference threads, but peak memory has not been measured on a Mac.

## Upgrading from the first Sift build

Stop the earlier Sift helper/Terminal before starting Unscroll; both use local port 8765. Keep your data directory intact. Unscroll will reuse the existing Sift database when present. Run setup in the new project folder, remove the old unpacked extension from Chrome, and load the new `extension` folder. Pair it with the token printed by the new setup.

## First useful run

1. In TikTok, request your data export. Extract its JSON file or the **Favorite Videos** TXT file from the ZIP.
2. Click **Import saves** in Unscroll. Select the extracted JSON/TXT file, or paste full `/@creator/video/ID` and `/@creator/photo/ID` links. Importing the same post again updates supplied metadata without rewriting a completed entry. JSON imports select the Favorite Videos section, excluding browsing history and likes. Text imports should use the Favorite Videos file, not a combined activity dump.
3. Click **Process next 20**. Watch **Processing** for progress or failures. This is the initial evaluation batch; it does not automatically start all 500 posts.
4. Open entries. Compare the **Full extracted source**, each bullet's **Check source quote**, and the original post. **Mark checked** records your review.
5. Choose **Organise with AI**. Review, rename, combine, add or remove categories and subcategories. **Approve & organise** locks in the two-level tree and queues placements. No category tree is installed without your approval.
6. Search by an idea, browse categories, or filter by creator, format and saved date. Posts without an exported save date are excluded from date-filtered results; Unscroll does not guess a date.
7. Tick the posts you want and choose **Download selected**. Only those posts are queued for permanent media downloads. Suggested offline picks are highlighted, and each entry explains its suggestion.

Use **Processing → Queue remaining backlog** after the 20-post quality check. Pause stops after the current job; it preserves queued jobs. Dead, private, blocked or unsupported posts remain visible with retry controls.

### Remove an accidental import

Open **Processing → Pause** and wait for the active post to finish. In **Settings → Clear accidental imports**, choose **Remove all unprocessed posts** and confirm the count. This applies to the whole library, even with filters active, and protects completed entries and permanent downloads. To remove a specific selection, tick those posts and choose **Remove selected posts**. Selected removal includes processed posts and removes their entries, search vectors and category placements from the library; downloaded files stay on disk. Queued jobs for removed posts are cancelled; TikTok saves are unchanged. A local recovery copy retains removed records. **Settings → Undo last removal** restores that batch while keeping the queue paused. Undo refuses to overwrite posts that have been imported again. After clearing an accidental backlog, import a few individual links and use **Process selected** or **Process next 20**.

## Capture new saves with Chrome

1. Open `chrome://extensions`, enable Developer mode, and choose **Load unpacked**. Select this project's `extension` folder.
2. Start the local helper, then paste the setup token into the extension (or retrieve it through Settings at http://127.0.0.1:8765).
3. In your own logged-in TikTok tab, open Favorites or the collection you want. Click **Choose collection on page**, then click a video tile inside that collection. Reopen the extension and choose an import mode. Confirm the loaded-link count before importing. **Check for new saves** starts at the top of the chosen grid; **Continue importing older saves** resumes within that selection; **Rescan everything** refreshes that grid's metadata. Keep the popup open, or choose **Stop importing**. Importing links does not start media processing or permanent downloads.
4. Click **Open your library** in the extension and process the new posts. Existing IDs are deduplicated automatically.

The extension acts only when clicked. It reads loaded links and available first-party page metadata; it does not obtain cookies or change anything on TikTok. Collections can be labelled with the extension's optional collection field. Use the same label when continuing an import. A quick check preserves your older-import bookmark and submits only posts missing from the helper's library. It assumes new saves appear near the top, so use a full rescan to recover gaps or refresh collection labels on existing posts. If TikTok has unloaded the bookmarked post, continuing may need to scroll through earlier posts to find it again; a missing bookmark produces an explicit recovery message. Imports save progress after each batch, stop after six scans without additional links, and pause after 200 batches; continue again if needed. Closing the popup interrupts the current scan, so its last unconfirmed batch may be retried. Automatic discovery of every collection and every saved post is **not guaranteed**. Use the data export as the backlog index. The extension and TikTok's current page structure still need a live account test.

## When a post cannot be fetched

Open the entry and attach your own video file, or the complete set of carousel images. For slides, use ordered filenames such as `01.jpg`, `02.jpg` and verify the selection order before processing. Attaching new media clears the previous extraction, entry and search vector; click **Process post** to extract it again.

Temporary attachments and fetched media are removed after an extraction attempt, including failed attempts. A failed local attachment must be attached again. If extraction succeeds and Claude later fails, retry reuses the saved text without fetching or transcribing again. Downloading later normally fetches the original post again; a subsequently deleted post may therefore be unavailable for offline keeping.

For videos that require authentication, you may optionally supply your own Netscape-format cookie file through `UNSCROLL_COOKIES_FILE` in `.env`. Cookies are never fetched from your browser automatically. Treat that file as a credential. The carousel page fallback does not currently use this cookie file; local slides are the reliable recovery route when photo capture is blocked.

## Privacy and files

| Item | Location or behavior |
| --- | --- |
| Database, caption, transcript, slide text, entries, categories, jobs | `~/Library/Application Support/Unscroll/` |
| Temporary fetched media and attachments | Under that folder; removed after the extraction attempt; partial fetched files from a crash are removed at next startup |
| Attachments waiting to be processed | Remain locally until extraction; process them to trigger removal |
| Selected permanent downloads | `~/Downloads/Unscroll/<post-id>/` |
| Claude API key | `.env` in this project folder, written with owner-only permissions |
| Local search vectors | SQLite, computed on this Mac with FastEmbed |
| Text sent to Claude | Caption, transcript/OCR text for one entry; titles/topics for category proposals; entry text and category labels for placement |

No media is sent to Claude. Normal network access still occurs to TikTok/media hosts, package repositories, model repositories and the Claude API. The app listens on loopback only, checks request hosts/origins, and requires a local token for its data API. This is a single-owner local application; do not expose its port to a network.

**Settings → Export library text** downloads a readable JSON copy of the posts, extracted text, entries, categories and placements. It omits the API key and pairing token. It is a portable text export, not a full database restore format. For a full backup, stop Unscroll and copy its entire application-support folder together with your chosen download folder. Do not share `.env`, your pairing token or cookies.

## What this build implements

- Favorite export/TXT/link import, persistent post IDs, metadata enrichment and duplicate protection.
- Local English speech transcription (`base.en`, CPU int8), ordered slide OCR and video-frame OCR.
- One structured entry per post: points, explicitly stated actions, exact specifics, topics and offline suggestion.
- Exact quote checks: an entry is rejected if its supporting quotes or specifics are absent from the source. These checks establish text matches; they do not prove that a paraphrase is complete or semantically correct. Human review remains necessary.
- Persisted SQLite job queue, stage checkpoints, manual retries, pause/resume and selected downloads.
- AI category proposal, user approval, primary and extra placements, manual move, re-run, rename and merge.
- Keyword plus local semantic search; possible overlap links without combining entries.
- A full library interface packaged in the Chrome extension: categories, source review, search, filters, job controls and selected downloads.
- A connection screen with local token pairing and an actionable helper-unavailable state.
- Optional per-user macOS helper startup, with a matching removal control.
- A user-triggered Manifest V3 extension for loaded saves and available structured photo metadata.

## Known limits before calling this version 1 complete

- This build has **not passed the PRD's 20-post fidelity test**, 10-query search evaluation, or 500-post capture/completion test. It has no measured Mac memory/runtime or API cost results yet.
- Real TikTok capture, extension behavior and Mac setup remain unverified. Page changes, authentication and region restrictions can block capture. Photo posts rely on first-party hydration data or a verified complete slide list; the app fails visibly rather than knowingly treating a partial carousel as complete.
- On-screen text is sampled once per second. Short overlays can be missed, and OCR/transcription can misread words. This is not a guarantee to extract every word.
- Carousel captions and slide text are extracted; carousel audio is not transcribed in this build.
- Only full TikTok video/photo URLs are accepted. Open shortened links first. Favorites collections are labels captured when supplied, rather than a fully reconstructed TikTok collection hierarchy.
- Title/topic category proposals are sent in one request and limited to 600,000 JSON characters. Very large libraries may need batching in a later build; the request fails explicitly rather than silently omitting entries.
- Local search uses a small English model. Its passage length limit can omit the end of long entry text during embedding; full source text remains available and is not shortened in storage. Overlap is a semantic candidate, not a claim that two videos say the same thing.
- Category approval is the initial tree installation. Afterward, rename/merge preserve placements; adding new branches after approval is future work. Pause the queue and wait for the active job before changing categories, attachments or entries.
- The app has no transcript editing, thumbnail-image cache, automatic cost estimates, signed installer or multiuser support. Clicking an original post opens TikTok normally. No posts are modified or redistributed.

## Validation

Run from this project folder after setup:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

During this build, **25 Python checks passed**: eight extension authentication, packaged asset and helper configuration checks, plus 17 core checks covering import scoping/deduplication, source quote validation, thin sources, URL/image host checks, queue deduplication, temporary cleanup, restart stage reuse, failed-AI source retention and separate semantic results. Four offline JavaScript boot scenarios also passed: no token, token pairing, authenticated API routing, and a stopped helper. These use a small simulated environment and do not render the UI. Python compilation, JavaScript parsing and shell-script syntax checks also passed.

To repeat the offline extension connection checks, run `node tests/extension_boot.cjs` with Node 18+ available.

The current update includes executed FastAPI integration checks and real Chromium tests against synthetic TikTok markup. Run `node tests/popup_import.cjs` for import/resume/stop/failure behavior and `node tests/collection_scope.cjs` with Playwright and Chromium for collection isolation. Set `UNSCROLL_CHROMIUM` to override the browser executable (default `/usr/bin/chromium`). Fixtures include a selected 20-post grid alongside unrelated, hidden and nested grids, route/title changes and replaced DOM nodes. These checks do not establish live-account TikTok compatibility or Mac acceptance.

Collection safety: only visible video tiles directly belonging to the chosen supported grid can supply links. Hydration data can enrich selected IDs but cannot add posts. Unsupported, hidden, detached or changed collection contexts stop importing. Reloading the page or choosing another grid creates a fresh progress scope; old unscoped bookmarks are ignored. Progress remains available while the same selection stays open. Choose the collection again after a page reload. This overrides the older page-only bookmark behavior described above.

Claude requests retry connection failures once. An invalid tool record (including an unexpected evidence `label`) gets one fresh, strictly validated generation attempt; quote verification still applies afterward. Successful API calls record usage even if their result needs correction. Read timeouts do not automatically issue another possibly billable generation. Extracted source text is retained for manual retry.

Use `docs/20-post-review.md` for the real acceptance run. The default Claude model is configurable; choose an available model in Setup if the default is unavailable to your account. Model/API usage is recorded as token counts, without an unverified dollar estimate.

## Developer notes

The Chrome extension bundles the HTML/CSS/JS library interface and connects to the loopback FastAPI helper with a pairing token. FastAPI also serves a recovery/settings copy of the interface; SQLite stores canonical records and the queue. Run `python build_extension.py` after changing the canonical frontend in `unscroll/static/`. One worker handles media, entry generation, categorisation, local embeddings and explicit downloads. Media/extraction is committed before AI writing, so later failures reuse the extracted text. A fresh launch pauses the queue and returns interrupted jobs to queued state.

Configuration: `UNSCROLL_HOME`, `UNSCROLL_DOWNLOAD_DIR`, `UNSCROLL_WHISPER_MODEL`, `UNSCROLL_CLAUDE_MODEL`, `UNSCROLL_COOKIES_FILE`. Restart after changing `.env`. Run the server with one process on port 8765; the lock prevents concurrent instances. User data is separate from this source folder, so updating the project need not replace the library database. If the earlier Sift build has an existing application-support directory and database, Unscroll continues using that location rather than losing the old library. Legacy `SIFT_` environment settings are accepted as fallback values; new setup uses `UNSCROLL_` names.

Primary implementation references checked during this build:

- [faster-whisper: CPU and int8 inference](https://github.com/SYSTRAN/faster-whisper)
- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create)
- [Claude tool schemas](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [Claude model IDs](https://platform.claude.com/docs/en/models/overview)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [Chrome extension permissions](https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions)
- [Chrome match patterns](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns)
- [FastEmbed](https://github.com/qdrant/fastembed)
