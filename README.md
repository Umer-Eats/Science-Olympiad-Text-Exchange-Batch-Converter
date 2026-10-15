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

## Local files and archive listings

The default review queue shows only entries with an existing local test PDF whose stored checksum matches. Imported archive listings are not downloaded papers. Use the **Listings missing test PDFs** filter to inspect missing entries; they do not count as extracted drafts or enter the processing queue. AI repair is disabled when a required local PDF or answer key is missing. A skipped repair now reports its specific reason. Public archive downloads retain their source links and original-source backups. A combined test-and-key packet may reference the same unchanged PDF in both roles.

## Find missing PDFs with Firecrawl

Open **Find missing PDFs**, choose **Firecrawl automated search**, enter your own Firecrawl API key (separate from Gemini), and save it. Keys are session-only unless you choose encrypted Windows storage. Select up to 20 tests, confirm credit usage, and click **Find and download with Firecrawl**. This is a standalone REST integration and does not use Codex or GPT tokens.

The app scrapes Scioly's public archive, searches for missing filenames with event/competition/year context, and downloads readable public Scioly archive PDFs up to 50 MB. Each run makes at most one archive request plus 16 Firecrawl search/scrape requests per test, covering four missing files per test. Exact SHA-256 matches attach automatically. Other downloaded copies remain candidates: preview and confirm the correct competition, year, division and role before attaching. Prior sources and reviews are backed up, and local extraction is queued; AI repair does not start automatically.

Results and downloaded PDFs survive restart. Interrupted searches do not resume paid requests automatically. Stop search prevents further requests after an in-flight request returns. For sign-in-only Scioly documents, use the cloud sign-in flow below. Unsupported external file hosts still require manual download. This feature cannot guarantee finding every file or infer missing test/key roles from an incomplete listing. Firecrawl documentation: https://docs.firecrawl.dev/features/search and https://docs.firecrawl.dev/features/scrape .

## Use your own browser for Scioly PDFs

Open **Find missing PDFs** and select up to 10 test listings. **Automatic local browser** is the default search method. For manual downloads, choose **Open 10 tabs in my browser**. Click **Open selected tests in my browser** to open their Scioly test pages in your default browser, then click **Download PDFs automatically** to save them with the converter-controlled Chrome window. You can still download them yourself and click **Check Downloads**. The converter checks only filenames matching missing attachments for those selected listings. You can also click **Open in my browser** on one listing to open just that page. If you use a custom browser download folder, click **Import PDFs** on an individual listing to choose its files manually. The converter matches exact filenames to missing files, checks that each is a readable PDF, and attaches an exact checksum match automatically. If the PDF differs from the archive checksum, preview it and confirm the match before attaching. Browser search and local import use no Firecrawl credits. Choose **Firecrawl automated search** only when you want its paid public web search. Firecrawl cannot reuse login cookies from your regular browser. **Verify Firecrawl sign-in** checks only the separate cloud browser, not your Chrome login.

## Sign in for Scioly account downloads

In **Find missing PDFs**, save your Firecrawl key, accept the cloud-browser credit notice, and click **Open Scioly sign-in**. A Firecrawl interactive browser opens in your default browser. Enter your credentials directly on Scioly there, then return to the converter and click **Verify Firecrawl sign-in**. Signing into an ordinary Chrome tab does not sign in this separate cloud browser.

Once verified, the downloader uses that session to visit selected Scioly test pages and request their download links. Only the expected filename on Scioly or its known PDF host is accepted. It then validates the downloaded PDF and uses the existing checksum/preview confirmation workflow. Unsupported checkout layouts remain unresolved rather than being guessed. Signed URLs and session-control links are not written into download reports or exports.

The temporary browser uses additional Firecrawl credits, expires after at most 30 minutes (or 10 inactive minutes), and is closed when you click **Close session** or exit the app. No persistent Firecrawl profile is created. The converter does not collect your Scioly password, copy cookies from your local browser or store the cloud login on disk. If a verification or download fails because the session expired, open sign-in again. This integration is limited to Scioly; other websites still need manual downloads.

Firecrawl Browser Sandbox API: https://docs.firecrawl.dev/features/browser .

## Automatic local downloads

In **Find missing PDFs**, choose **Automatic local browser** and select up to 10 listings to start. The converter opens a separate visible Chrome or Edge profile on this computer. Sign in to Scioly there on the first run; the login is retained locally. The converter handles every listed attachment in each selected test, then advances without another click. With **continue through every remaining listing** checked, it queues all other Scioly listings with missing files too. PDFs are validated; images and text files are converted locally into PDFs. Office documents and slides are converted with LibreOffice or Microsoft Office when installed. Converted copies have different hashes from the original listing and therefore remain review candidates until you confirm them. Unsupported or failed conversions are flagged rather than silently attached. The downloader releases each checkout slot it used before continuing and restarts its browser once to recover an interrupted release. Closing and reopening Chrome does not reset Scioly's account checkout limit; if Scioly still reports five occupied slots, the run stops without opening another checkout. You can stop the queue at any time; files already saved remain available. This mode uses no Firecrawl credits. The **Open 10 tabs** option opens listings in your regular browser for manual downloads; its **Download PDFs automatically** button can also continue through the remaining listings when the option is checked.
