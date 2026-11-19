A **run** is one press of a button: it logs in to AO3, indexes, downloads, and reports.

## Which run to use

| Run | Where | Use it for | Cost |
| --- | --- | --- | --- |
| **Quick Scan** | Bookmarks | Everyday use: new bookmarks, and anything AO3 updated since your last scan | Small |
| **(Full scan) Reindex & Update All** | Bookmarks | Repairing the index, or catching a finished fic that was added to | Reads everything - hours on a large library |
| **Download/update a specific fic** | Bookmarks | One fic, by link or work number. Always re-downloads it | One fic |
| **Download/update several fics** | Bookmarks | A pasted list of links or work numbers (any separators, up to 500). Always re-downloads them | One fic each |
| **Import works found in your library** | Offered when a library opens, and under the tabs | Files in `works/` with no index entry: date them, index them, add formats | One fic each |
| **Custom run** | Bookmarks | A slice of your bookmarks by page range or date range, or just the works already in your index | Depends |
| **Index my collections** | Collections | Your own collections | 1 request per 20 works |
| **Index collection by URL** | Collections | Any collection, from a link | 1 request per 20 works |

Three more - *new bookmarks + incomplete fics*, *just incomplete*, *just new bookmarks* - are the pieces Quick Scan is made of. They only show while **debug mode** is on (User settings, under *Advanced*; **Leave debug mode** on its banner turns it off), which also turns on the quick scan's date range and a debug panel in the run window.

## Quick Scan

It measures back to the start of your last **finished** Quick Scan or full scan, and walks your bookmarks twice:

1. **by date bookmarked** - catches old fics you only just bookmarked
2. **by date updated** - catches fics you bookmarked long ago that have since changed

It then downloads whatever either walk found. With nothing to measure back to, the first walk reads everything.

- **Choose which earlier scan to measure back to** - go further back if you think a recent scan missed something.
- What it gives up: anything missed before that date stays missed. Run a full scan now and then.

## Options

Each run asks its options, then which file types, then your login.

- **File types** - JSON is the index and always on. HTML starts ticked. Untick everything else for a metadata-only run, about a twentieth of the requests.
- **If a work is a part of a series, download all its other works too** - downloads every work of each series found, even ones you haven't bookmarked.
- **Check all non-bookmarks for updates too** - re-checks works you have indexed but not bookmarked: works added by URL or id, imported works, works indexed from a collection (with *Index and download encountered works*), and works in a series you have indexed. Their series are read first; it is not limited by a date range.
- **Overwrite existing downloads** - full scan and custom run only. Replaces everything, whether or not AO3 updated it, in the formats you choose on the next page, for when you suspect a damaged file. Every run that replaces a file with one of the same name writes the new copy beside yours (`.ficfairy-new`), checks it, and only then swaps it in - your old copy is set aside (`.ficfairy-old`) until then, so a download cut off midway never loses it. If a file you have is **newer** than the version it would be replaced with, the run asks first (no, keep it, if you don't answer). The fic runs, which always replace, ask the same.
- **A slice of your bookmarks listing** - custom run only, under *What this run covers*, with two choices nested under it: **Choose my own page range** or **Choose my own date range**. Each has **Order by**: *Date bookmarked* or *Date updated*. A page range reads your bookmarks in the order you bookmarked them unless you choose date updated (where a fic AO3 updates moves to the top, so the same pages hold different fics from day to day). A date range picks works AO3 updated in it unless you choose date bookmarked, which picks the works you bookmarked in it - only your own bookmarks have a date bookmarked. Leave the newer date empty for today, or the older one empty to read all the way back. Dates are shown written out (`3 March 2024`); a start date later than the end date, or later than today, is pointed out and **Continue** waits until it is fixed.
- **Just update existing works** - custom run only, one of its choices under *What this run covers*. Works through every work already in your index, bookmarked or not, without reading AO3's listing first. Then choose how a file is judged outdated:
  - **Check for outdated against latest on AO3** - each work is looked up on AO3, one at a time, its index entry updated, and its files judged against that. One request per work, so slow on a large library. This is the default.
  - **Check for outdated against current index** - missing formats are downloaded, and a file whose name is dated before your index's date is replaced. Nothing is looked up on AO3, so a fic AO3 has updated since it was last indexed is not seen as needing an update, and the index itself is not updated. A work with no date in its index entry can't be judged; only its missing formats are downloaded, named with no date. A file of a work with no index entry at all is never touched.

  Either way, works AO3 won't give are offered to FicHub at the end, as on every run.
- **Save embedded images separately** - custom run only. Usually unnecessary: images are already inside the downloaded work.
- **Index and download encountered works** - collection runs only. Off: just records which works the collection holds. On: indexes and downloads them too.
- **Include subcollections / parent collections** - collection runs only. Follows the family, each collection once, up to 200.
- **Skip AO3 login?** - on every run's login page, below the username and password, off by default. Not recommended: logged out, private bookmarks are missed and fics restricted to AO3 users can't be reached, so they may have to come from FicHub instead. Scans of your own bookmarks or collections still ask for your username, never your password.

## How files are compared

Three dates are involved whenever a run decides whether to download a format:

- **The incoming date** - when the source says the fic was last updated: AO3, as read during this run, or FicHub's copy.
- **Your file's date** - the version the file holds, read from its name.
- **The index entry's date** - when AO3 (or FicHub) said the fic was last updated, the last time its entry was read. It says how current the entry's summary, tags and stats are. **It is never what a file is compared against** - each file is compared with the incoming date.

Each format is judged on its own, so a work can have a current HTML and an outdated EPUB, and only the EPUB is fetched. A new file is named with the incoming date, and an older copy is deleted only once the new one is saved whole.

**Where AO3's date comes from.** Every scan reads it off your bookmarks listing (or a collection's) as it walks it. The fic runs and the pass over unfinished fics open each fic's own page. Two exceptions use an older date: a **Custom run with *Just update existing works***, which judges files against your index as it stands, and a **retry carrying on an earlier attempt's downloads**, which uses what that attempt read - unless you answer yes when it asks whether to read each work again first.

**More than one file of a format - the nominated file for comparison.** When a work has two or more files of the same format, a run picks one of them to compare against what is coming in (from AO3 or FicHub, overwriting or not), its **nominated file for comparison**:

1. the newest one dated the way this app dates files (`... 2026-05-10.epub`); otherwise
2. the newest one by a date guessed from its name (`(10 May 2026)`, `2026.05.10` ...); otherwise
3. the first one by name, alphabetically.

Everything else then works as it does for a single file: a nominated file dated the app's way is replaced without asking when it is older, and one whose date is only guessed (or can't be read) is asked about, with a recommendation. Any question that names the nominated file lists the other copies under it - *You also have other copies of this EPUB - these will be kept for now, and can be cleaned up later.* Only the nominated file is ever replaced; the others are always kept, and the end of the run says how many works still have duplicates, with a button to sort them in **Resolve issues**.

### Three kinds of file name

- **The app's own date** - a space, then `YYYY-MM-DD`, at the very end of the name: `12345 Title - Author 2026-11-04.epub`. This is how the app names what it downloads. **Only a file named this way is ever replaced without asking.**
- **A date that can only be guessed** - written any other way, or anywhere else in the name: `(4 Nov 2026)`, `2026.11.04`, `11-04-2026`, `2026-11-04 v2`. The run reads it the way *Infer date* does on *Resolve issues*, but it is a guess, so the run never acts on it alone: it **always asks**, says what it *thinks* and what it recommends, and **keeps your file** if you don't answer.
- **No readable date at all** - `12345 Title.epub`. Nothing says which version it holds, so it is never replaced without asking either.

### From AO3

| Your file | Ordinary run | Overwriting run |
|---|---|---|
| No file in that format | Downloaded | Downloaded |
| **App's own date**, older than AO3's | Replaced | Replaced |
| **App's own date**, the same | Kept | Replaced |
| **App's own date**, newer than AO3's | Kept | Asks (default: keep) |
| **Guessed date**, looks older than AO3's | Asks - we think AO3's is newer, recommend replacing (default: keep) | Same |
| **Guessed date**, looks the same | Asks - recommend keeping (default: keep) | Asks - recommend replacing, as a file with the app's own date would be (default: keep) |
| **Guessed date**, looks newer than AO3's | Asks - we think yours is newer, recommend keeping (default: keep) | Same |
| **No readable date** | Asks - warns we can't tell, but the incoming copy is AO3's own, so replacing is probably safe: recommend replacing (default: keep) | Same |

The index is updated with a new reading whenever AO3's details have changed - whatever happens to the files.

### From FicHub

FicHub is only asked at the end of a run, for works AO3 wouldn't give. If AO3 is down for maintenance when a fic run or a repair (*Resolve issues*) tries to log in, the run carries on without AO3: every work fails at once and is offered to FicHub at the end. A scan of your bookmarks or collections can't - it needs AO3's listing - so it stops at the login. What happens depends on how FicHub's copy compares with your **index**.

**FicHub's copy is as new as your index, or newer** (or the work has no indexed date): the AO3 table above, with FicHub's date - except a file with **no readable date**, where keeping is recommended overwriting or not, since FicHub's copy may be an older cached one, not up to date with AO3's latest. If the run writes JSON, the index gets a new reading from FicHub, marked **From FicHub**.

**FicHub's copy is older than the last known update date we have** (AO3 had a newer version that FicHub never caught): each file is still compared with FicHub's date, and **the index is left alone** - its reading is newer.

| Your file | Ordinary run | Overwriting run |
|---|---|---|
| No file in that format | Taken - an older version beats none - and warned about | Same |
| **App's own date**, older than FicHub's | Replaced | Replaced |
| **App's own date**, the same | Kept | Replaced |
| **App's own date**, newer than FicHub's | Kept | Asks (default: keep) |
| **Guessed date** - older, same or newer | Asks, with a recommendation as in the AO3 table (default: keep) | Same (the same date: recommend replacing) |
| **No readable date** | Asks - we can't tell, and FicHub's copy may be an older cached one: recommend keeping (default: keep) | Same |

The log says which case applied to each file. A work FicHub can give nothing newer for stays on the run's failure list.

**A format from an older FicHub copy.** Whenever FicHub gives a format - one you had no file of, or one that replaced an older file of yours - and its copy is dated before the last known update date we have - from your index, or from the date in the name of another of the work's files (never a guessed one) - it is still kept, named with FicHub's own date. The log says it *may be an older cached copy*, and so do the end of the run, History and the issues file.

### A work your index didn't have

If the index had no entry for a work when the run began, but your library holds a file of it, that file didn't come from this app. It is still judged only by the date in its own name - the index never dates a file - but before replacing such a file - from AO3 or FicHub, overwriting or not, whatever its name - the run asks, and recommends replacing a copy when the incoming version is newer than the date in its name (or the same, on an overwriting run) - or, from AO3, when its name has no date at all, since AO3's own copy is probably safe. **No** if you don't answer.

### Resolve issues

A repair started from *Resolve issues* asks none of these questions about your files: its own window has already decided. When it updates works, it replaces a copy only when AO3 or FicHub has a newer version than the date in the file's name, and fetches the formats you ticked that a work doesn't have. With **Overwrite existing downloads** ticked it downloads each dated file again, current or not. Files with no date in their name - ones you left undated in the window - stay as they are either way.

## Questions a run may stop to ask

- **How far back to go** - a Quick Scan with no earlier scan, but an index already there.
- **Try FicHub?** - at the end, when AO3 wouldn't give the run some works. Try FicHub, or leave them as failures.
- **Replace a copy of a work your index has no entry for?** - when a file in your library is for a work the index did not know when the run began, so the file didn't come from this app. The question names each file, and the run reads the date in each one's name (as *Infer date* does) and recommends replacing a copy if the incoming version from AO3 or FicHub is newer - or the same, on a run that overwrites - or, from AO3, if the name has no date at all; saying why for each. You can replace only the recommended ones, all, or none. **None** if you don't answer.
- **Replace a newer copy with an older version?** - on a run that replaces files, when the copy you have is newer than what would replace it (from AO3 or FicHub). **No** if you don't answer.
- **Replace a file whose date we can't be sure of?** - when your file's name has no date written the way this app writes one. One question per work and format - from AO3 or FicHub, and whether the date we guessed from the name looks **older** (we recommend replacing), **the same or newer** (we recommend keeping - but replacing the same date on a run that overwrites), or **can't be read** (from AO3 we recommend replacing, since AO3's own copy is the version AO3 serves now; from FicHub we recommend keeping, since its copy may be an older cached one). The question shows the file's whole name. Besides **Replace it** and **Keep mine** there is **Keep both** (when the incoming version has a date): your file stays exactly as it is, and the incoming version is saved beside it as a new file, named with its own date. **Keep** if you don't answer in time (1 minute unless you change it), unless you changed that case's default. Every one is listed afterwards in the run's **Questions asked** in History, with the file, both dates and what was chosen. Tick **Always choose this...** to have every later file in that case answered the same way, without asking - in this run and every run after. Change or forget it in User settings' **Answers to always use**. A retry asks every one of these again, unless you chose an answer to always use for its case.

When a run met any of these files, it says so at the end and offers **Refresh library and resolve issues**: the library is read again and *Resolve issues* opens, where you can date them - so the next run judges them by their date instead of asking.

**A ding when it asks.** The page plays a short sound whenever a run stops to ask you something, and when *Resolve issues* stops to ask which copy to keep, so you know to come back to the tab. Turn it off, or hear it, under User settings > Appearance; it is this browser's own choice.

**How long a question waits.** Each question says, above it, how long it waits and what the run carries on with if nobody answers - in the words of the button that does it. The waits are settings: one for the questions asked once a run (30 minutes), and one each for the questions that can come up for every work - a file whose date we can't be sure of (1 minute), a newer copy, and a copy of a work your index didn't have (30 minutes each). Change them in User settings (settings.ini on a downloaded app; *Defaults used during a run* on the hosted copy). `0` takes the default without asking.

**When nobody answers, don't wait on the rest** (on unless you turn it off). Once a question goes unanswered, the rest of the same kind in that run take their default straight away, so a run you walked away from doesn't wait out every work. Off, every question is asked and waits its time. An answer you chose to always use is taken without asking either way. History's *Questions asked* says which were answered which way.

Closing the page or stopping takes the answer that changes nothing - except for the two FicHub questions, where it is yes.

## Pause and Stop

- **Pause** takes effect at once, in every workflow at every step - while logging in, while AO3 is still thinking about a request, during a rate-limit break, or between reads and writes of your library. Whatever was in flight is dropped and done again on Resume (the same fic looked up, the same file fetched, the login started again); a break carries on with only the time left of it. Nothing is ever half-written. It stays paused until you press Resume.
- **Stop** takes effect at once too, the same way, and keeps everything already saved.
- **Force stop** - in **History**, on the run pinned at the top - is the last resort for a run that will not stop or whose window has gone. It ends the run straight away, records it as *Stopped* with its log and issues, and lets another run start.
- A long pause can let your AO3 login expire. If works start failing after Resume, stop and start again.

## Background runs

Tick **Run as background task** on its own page, just before the login, to let the helper finish with the page closed.

- Only on the hosted copy - the bundle and the Windows, Mac and Linux apps don't offer it, since their helper stops when you close its window.
- Dropbox libraries only - the helper can't reach a folder on your computer without the page.
- Questions are answered up front, since nobody will be there.
- One run at a time. A banner says when one is going, and **Go to this run** opens it in History.
- A background run left **paused** for 10 minutes (`PausedRunTimeoutMinutes`) is abandoned, keeping what it saved.
- Restarting the helper - closing its window, or a deploy - ends a background run. See [[History and resuming]].

## At the end

Every run finishes with **Try FicHub** (when anything failed), then **Report any failures**:

- **Try FicHub** - first, if AO3 wouldn't give the run some works, it asks whether to try [FicHub](https://fichub.net), a mirror that keeps copies of AO3 works, even some AO3 no longer has. **Yes if you don't answer** in time. What FicHub has is indexed and downloaded in your file types (not AZW3), and marked **From FicHub** in your library. If FicHub's copy is **older** than your index, each file you have is compared with FicHub's copy by the date in its own name: only a file older than FicHub's is replaced (an overwriting run asks before replacing a newer or undated one), and the index is left alone. On **Resolve issues**, FicHub follows the repair's own choices: a work only looked up gets just its index entry, your copies are kept unless you chose to replace outdated ones, and its files are renamed to match the new entry, keeping their own dates. Never tried for external works or series. Most useful for a fic you indexed before AO3 deleted it (the index keeps its number) and for a single fic fetched by link or number.
- **Failures** - works that wouldn't download. A later run tries again. A work FicHub couldn't give either says so.
- **Bookmarks that are not works** - series, external works, deleted works. Nothing to retry.
- **Copies to check by hand** - a new file saved, but an older copy couldn't be removed, or the save couldn't be confirmed.

**History > Download issues** saves all of it as one text file.

## Importing works already in your library

When a library opens and `works/` has files named for a work number that your index has no entry for, the page offers to import them. While there is anything to sort out, a **Resolve issues found with import** reminder sits just under the tabs, above whatever the tab shows, whichever tab you are on, and opens the same window - closing the window leaves it there, and its **×** hides it until you open the library again. Undated files of works already in your index are offered for dating too (with nothing else to import, the window finishes after the dates).

Before anything else, if a download replacing a file of yours was left part-way (the app closed mid-swap), a first page lists those files: a copy of yours that was set aside is always **put back** (any new copy in its place is removed, in case it's damaged), and an unfinished new copy beside your file is removed. **Skip this step** leaves them for next time.

1. **Overview.** Under *Issues found in import:*, how many files are named in a way the app can't match to a work, how many are duplicates, how many have no date, and how many belong to works with no index - nothing listed yet. Choose **Repair now (recommended)**, **Not now** (reminded next time you open the library), **No, do not ask me again for these files** (listed in `import-excluded.json` and never counted or offered again), or **No, never ask me again** (no window and no reminder; User settings turns them back on).
2. **Rename** (only if some files are named another way - an old file name pattern's, or AO3's own download names like `My Fic - Author - 12345678.epub`). The formats they are named in are listed, the most files first, each with how many files and two of them as they would be renamed: tick the formats to rename to the app's own pattern, and **Rename N files** (or **Skip this step**). Each file's work number, title, author and date are read out of its name (a work in your index takes its title and author from there), and a date in it - however it was written - is written the app's way, so it is trusted from then on: leave a format unticked if its dates aren't that. Files with no work number at the start or end of the name are listed and left as they are. Nothing is renamed over another file: a file whose new name is already taken is left as it is and sent to the duplicates with the file that has that name, where it is sorted like any other duplicate: whichever you keep takes the name, and skipping keeps both, with that file still named as it was. Just after the file name pattern changed, the old pattern's formats are ticked to begin with.
3. **Duplicates** (only if a work has more than one file in the same format, however they are named). For each, **Keep most recent** (picked to begin with - it only acts alone when one file is dated the way this app dates files and that date is later than every other file's date, guessed or not; otherwise the removing step asks you), **Skip** (keeps every file and asks again next time - unless you tick **Don't ask this again for skipped files**), or **I'll choose**, which then shows each one in turn - each file with the date in its name (marked **(best guess)** when it isn't written the way this app writes dates) and when it was last changed, the most recent at the top and picked to begin with (headed **Most recent** when it's certain, **This is our best guess for 'most recent'** when it isn't; when nothing tells the files apart - no dates in the names and no file change times - nothing is picked, it says so, and **Next entry** waits until you pick a file or skip). When each file was last changed only breaks ties for a best guess - or **Skip for now** / **Skip, and don't ask me again for this file** below the files, with **Previous entry** and **Next entry** (which keeps the picked file), and, at the foot under **Sort any remaining in bulk**, **Skip for now** / **Skip, don't ask again** / **Keep most recent** with **Apply to the rest**. **Continue** waits until every one is sorted; **Back** returns to the list, and coming forward again picks up at the first one still to sort. Nothing is deleted until the next step, which removes the rest with a bar. A set marked Keep most recent that it can't tell - a guessed date looks as late or later than the one dated this app's way, no file is dated this app's way, two share the newest date, or no name has a date - stops the bar and asks: take our best guess (picked to begin with - the latest date in the names, whether dated this app's way or guessed, then the file changed most recently; if even that can't tell them apart, **Make a best guess** is greyed out for that set and you choose the file or keep them all - even after **Apply to all remaining** with a best guess, it stops and asks again for such a set), choose the file yourself, or keep them all - then **Apply and carry on** for that set alone, or (for a best guess or keeping them all) **Apply to all remaining** for every set like it. No answer in 5 minutes keeps that set. Removed files never appear on the later pages. When the repair has more than about 20 requests to make, its run window says so - leave it open until it finishes.
4. **Dates** (only if some files have none). Give each file a date, tick **Skip**, or tick **Repair from AO3** - a skipped row is greyed out. **Bulk actions**, a fold above the list, says how many files remain (no date, Skip or Repair tick yet) and answers only those, so nothing already answered changes: **Infer date for remaining** (reads a date out of each name, however it is written - 2024-03-04, 20240304, 03-04-2024, 14 Dec 2024...; what it found turns yellow and moves to the top), **Skip remaining**, **Repair remaining from AO3**, **Untick Skip on all**, and **Choose my own date...**, which opens a date box in place with **Use for remaining**. **Repair from AO3** overwrites the file with the newest version on AO3, whatever it holds, named with AO3's date - the way to date a file you can't. **Continue** first renames the files you gave a date. Then, with any ticked for repair, a page of its own asks how they are repaired. **If an index exists for the work** - **Try to date the file from an existing FicFairy index?** (off to begin with): the file keeps what it holds and is renamed to include the last known updated date FicFairy retrieved from AO3, without asking AO3 again - that date may not be the version the file actually holds. Files with no index go to AO3, then FicHub - unless you also tick **Skip any check from AO3 for remaining files**, nested under it: then a file with no date in your index is left as it is, and the AO3 and FicHub choices below are hidden. These renames are done last, after the formats page, once every question is answered. **If AO3 has the work**: **Overwrite and rename the file** (to begin with - replaced with AO3's newest version, named with its date) or **Only rename the file** (the file keeps what it holds and is renamed to include the date AO3 last updated the work - which may not be the version it actually holds; nothing is downloaded). **If AO3 can't give it, and FicHub has to be used** (a warning says FicHub keeps cached copies, which may be behind AO3): **Leave my file as it is** (to begin with); **Only rename the file** with FicHub's date; or **Overwrite and rename the file** with FicHub's copy. Picking either shows two Yes / No questions under it: *Rename (or Overwrite) files that seem to have an older date than FicHub's?* (Yes to begin with) and *... files that have no date that can be guessed?* (Yes for renaming, No for overwriting). A file whose name seems to have a later date than FicHub's is never renamed or overwritten. A repair never renames or saves over another file: if the name a file would be given is already taken, that file isn't repaired, both are kept, and it is listed as *failed to repair ... due to a name clash* - straight after the renaming for a repair from your index, and at the end of the run (also in History and the issues file) for AO3 and FicHub. Resolve issues then offers the pair as duplicates. A work with no index entry that has a file being repaired from AO3 is indexed by the repair, so the next page doesn't ask about it again - it says how many such works there are. Switch between pages and one scrolling list; hover a long name to see it whole. Every file needs an answer before you can continue: a file with none is highlighted, and a note says how many are left. The button says **Skip this step** when every file is skipped, and **Continue** otherwise. Tick **Don't ask this again for skipped files** to list every skipped file in `import-excluded.json`, so it is never offered for dating again (its work is still checked for a missing index entry).
5. **Dating.** A bar while the files are renamed, then how many were dated and any that couldn't be (folded away). Every file is renamed by the app's file name pattern, with your date - a work you have indexed takes its title and author from its entry.
6. **Index** (only if some works have no entry - otherwise you go straight to the formats): it says how many works have no index entry and what an index entry is (title, author, summary, tags, word and chapter counts, last update - what lets you browse and filter them here), then asks: fetch their index entries from AO3 now? **Yes**, **Not now** (offered again later), or **No, and do not ask again for these works** (listed in `import-excluded.json` with the files they have now - not asked about again unless a new file for that work turns up; their undated files can still be dated). A work AO3 won't give that has no entry at all is taken from FicHub's cached copy without asking - better than no entry, whatever its files' dates. **Look up its index from AO3 here** on a work in the Works tab opens Resolve issues straight on this page, asking whether to look up **just that work** - or **just these works**, from the selection bar - (even one you told it not to ask about again), **all missing indexes**, or - when an ignore list holds some - **all missing indexes, even ones you added to an ignore list**. That page is the window's first, with no Back, and doesn't ask whether to fetch - it's yes. The formats page then offers **Just this fic** (or **Just these fics**), **All fics with a missing index**, or (with an ignore list) **All fics with a missing index, including any added to an ignore-list** - any fic chosen there is looked up too.

7. **Formats**: first **Try and fetch the latest version of each fic from AO3?** or **Skip this step**. Fetching asks which fics: **For all fics found to have issues in this import** (the default), **Just the fics that had an improperly formatted date**, or **Just the fics with a missing index**. Unless skipped, a page of its own follows: **File types** to download for works without them (the formats you already have are checked for a newer version whether ticked or not), then **Overwrite existing downloads** (download each dated file again, current or not - for file integrity worries). Updating always replaces a copy when AO3 or FicHub has a newer version than the date in its name. Only files with a date in their name are updated; a file with no date in its name is kept as-is.
8. If there is a lookup to do, or something to download or replace, the window moves on to the login - titled *Resolve issues found in your library*, listing what the repair will do - with **Start repair**: background (on a hosted copy), then the **AO3 login**, asked in case some of the works are restricted to AO3 users. You can tick **Skip AO3 login?**, but those works will then fail. With nothing to do, the window just closes. Once each work is indexed, its files are renamed to match it, keeping the date each one carries.

**An import takes every work it finds, however many** - though each one looked up is a request to AO3, so a large library makes a long run. Skip the index question and nothing is indexed: only works already indexed are updated.

Imported works show as **Imported from an external source** in the Works tab, unless they turn out to be your bookmarks. While another run is going nothing is renamed or started; the offer comes back once that run has finished. **No, never ask me again** stops both the window and the reminder; turn them back on in User settings.
