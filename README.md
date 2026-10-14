# Science Olympiad Test Exchange Batch Converter

A separate, local workspace for turning Division B and C competition PDFs into reviewable practice drafts. Local extraction needs no API key. Optional Gemini repair uses a key that each user enters locally. This is a preparation tool for content reviewers; students still take tests in Akoizo.

## Start on Windows

For the portable Windows download, extract the entire ZIP to a writable folder, then double-click **Test Exchange Converter.exe**. Keep the `_internal` folder beside the executable. Python and OCR models are included. The app opens its own desktop window and starts processing the saved queue automatically. It does not open a browser by default. Windows requires the Microsoft Edge WebView2 Runtime, which is commonly installed already.

In the source folder, double-click **Start Converter.cmd**. The source edition requires Python 3.11 or newer; initial setup downloads the dependencies. Your configured copy already has its own Python environment.

Some Windows Application Control policies block newly built, unsigned executables. If that happens, use **Start Converter.cmd**, which prefers an already installed local Python environment and can fall back to source setup. The portable ZIP includes the source files too. Python 3.11+ is required for this fallback; do not disable your security settings. This computer is running the source launcher because Windows blocked the rebuilt executable.

Use **Pause** to finish the current paper and wait. Minimizing the desktop window leaves the worker running. Closing the desktop window stops it safely; previously uploaded PDFs, saved reviews and the queue reappear automatically the next time you open it. **Stop app** exits the worker safely. Start it again after restarting your computer; there is no hidden startup service. Queued or interrupted papers resume, completed drafts are skipped, and manual review edits are preserved.

## What to provide

- The complete, unlocked test PDF.
- Ideally the published answer-key PDF, including its rubric and point values.
- Any separate image or answer sheet PDFs.
- Competition name, event, division, year and original HTTPS source link.

Use **Add tests → Multiple tests / folder** to select many PDFs at once, drag in a batch, or choose a folder including subfolders. The app suggests pairings from filenames; review each file’s group and role, apply shared event/division/year details, and adjust individual packets. Confirm the pairings, then upload all ready tests. It uploads packets sequentially, keeps successes when another fails, skips duplicate papers in the same division, and lets you retry failures or stop after the current packet. Missing keys are accepted and flagged. Each packet is limited to 100 MB; there is no fixed batch file-count limit. Keep the app open until uploading finishes. A successful upload is saved locally; selecting files without pressing Upload does not save them.

Use **Add tests → One test** for individual papers. For a batch, copy the `inbox-example` template into `data/inbox/my-test`, edit `metadata.json`, and add `test.pdf`, `key.pdf` and any supplement PDFs. Each test gets its own folder. The running app scans for changes every 15 seconds. Source files are copied into an independent, content-addressed store, so no connection to Akoizo is needed afterward.

The optional `import_akoizo.py PATH_TO_AKOIZO` imports its existing bulk queue and available local PDFs without modifying the project. It copies no credentials. Files not downloaded are flagged, not fetched through a browser or invented. Non-PDF attachments require manual preparation.

## What happens automatically

The app extracts PDF text and attempts local OCR on scanned pages, identifies numbered items and choices, matches uniquely numbered answers, and checks explicit printed points and totals. It processes one paper at a time in an isolated worker. A paper taking over ten minutes is marked failed so it cannot stall the batch. Failed jobs can be retried after their files are corrected.

It flags **missing answers**, **unclear formatting** and **conflicting scores**. It also flags missing files, repeated numbering, diagrams, scans, possible columns, uncertain metadata and incomplete question coverage. Difficulty starts as a question-count suggestion and needs content review. Competition level remains unconfirmed unless the source reports a level; it is never inferred from the competition name.

## Review and export

1. Open a paper from **Review queue**. Compare the draft with every page of the original test, key and supplements.
2. Correct prompts, answers and points. Use the advanced JSON editor to split multipart questions, change choices or add rubric criteria. Load form edits into the editor first; apply editor changes and then save.
3. Record how each flag was resolved. Verify topics, 2027 alignment, difficulty, source evidence and scoring basis. A note alone does not fix an incorrect draft.
4. Enter the reviewer name and save. Approve only after factual accuracy and coverage are verified. Editing afterward invalidates approval.
5. Export a ZIP with Akoizo-format JSON, original PDFs, hashes and review evidence. Validate and import it into Akoizo separately. Nothing is automatically published.

The published-key exporter requires the original test and answer key. A missing key remains in review until supplied. Multiple files of a single role must first be combined and checked; no supplement is silently dropped. Rules alignment still needs separate verification. AI-reviewed tests are labeled as such, and scientific accuracy is not guaranteed by automatic approval. Printed answer keys, OCR and the extraction rules can be wrong. Zero-point exclusions still require an explanation.

## Optional Gemini repair

Open **AI repair & settings** inside the desktop app. Paste **your own** Gemini API key, choose a model (default `gemini-3.5-flash-lite`), and save. Test connection checks model access without sending a test or requesting generation. Nobody needs to send their key to the app developer or put it in the source code.

Keys are session-only by default. On Windows you can choose **Remember this key**, which encrypts it for your Windows account using DPAPI. Other platforms currently use session-only keys. The backend never returns the key to the UI, includes it in an export, or packages it in a release. **Forget key** removes the saved copy. An already-running provider request can still finish. `data/`, keys, local environments and builds are excluded by `.gitignore`.

Select up to 20 tests, review the disclosure about sending PDFs to Google, and start repair. The first request repairs the actual questions, answer choices, rubric answers and scoring. The second independently checks the result against every source page. Complete source evidence, question coverage, answer keys and point totals must pass local validation. With automatic approval/export enabled, passing tests are applied, approved and exported without another manual step. A backup of the original review and an AI audit report are saved. No content is published to Akoizo automatically.

This requires a complete test PDF and its published key, plus listed supporting PDFs. Missing downloads, contradictory rubrics and unsupported answers cannot be fixed by inventing evidence. These stay flagged. If a check fails, proposed fixes are saved separately and the original draft remains intact. AI review is not human review or a guarantee of scientific accuracy. Topic compatibility with 2027 rules remains unverified because the official rule documents are not sent to the model.

Each test normally uses two paid generation requests. You supply the key and manage its Google billing/quota. There are no automatic paid retries, and interrupted AI jobs require an explicit restart. Cancelling prevents application of the current result but cannot undo a request already received by Google. Larger PDFs use Google's Files API; the app attempts deletion afterward. Inspect the audit report for cleanup failures. Do not use this option for documents you do not want to send to Google.

Implementation references: [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [document processing](https://ai.google.dev/gemini-api/docs/document-processing), and [Files API](https://ai.google.dev/api/files).

## Storage and privacy

All uploaded PDFs and saved work persist under `data/` beside the source app or portable executable. Use a writable folder such as Downloads or Documents, not Program Files. Back up the complete `data` folder with the app stopped. It contains the queue, originals, extracted text, drafts, reviews, database, logs and exports. Source PDFs are preserved byte for byte.

Local extraction makes no external API calls. Starting an optional Gemini repair sends the selected original PDFs and draft to Google using your own API key. Saving a key does not start a repair. Initial dependency installation needs internet. The dashboard listens only on your computer (127.0.0.1). Do not expose its port to other computers. Keep enough free disk space for originals, OCR dependencies and exported copies; large archives can use several GB.

## macOS and Linux source edition

Install Python 3.11+ with virtual-environment support. Open a terminal in the extracted source folder and run `sh start-converter.sh`. This creates a local environment and installs dependencies on first launch. Later conversions work offline. Linux may also need system OpenGL libraries for OpenCV. Platform support depends on available dependency wheels. The Windows desktop UI is tested here; macOS and Linux desktop builds require testing on those systems. Linux also needs a supported Qt or GTK webview backend.

## Build a portable download

On the target operating system, install requirements and PyInstaller, then run `python build.py`. ZIP the complete `dist/Test Exchange Converter` folder, including `_internal`. Build separately on Windows, macOS and Linux; Windows output does not run on other operating systems. The runtime is bundled, not an installer or code-signed release. Distribute the source and third-party license notices with your release; PyMuPDF is AGPL/commercial licensed, so review redistribution obligations before a public release.

## Maintenance

Run `python -m unittest discover -s tests -v` for structural checks. Run `python app.py --once --limit 20 --home PATH` for a bounded batch without a dashboard. `--headless` runs without a window. `--browser` is an optional fallback; the default is the dedicated desktop window. `--port 8767` selects another port. Only one instance may use a data folder at a time.

If a paper fails, inspect `data/logs/TEST-ID.log`, correct the source and retry. For updated source files, re-import them through the inbox; manual reviews are retained and must be refreshed against the new source before approval. The review screen can reset to the latest extraction while backing up the previous saved review.
