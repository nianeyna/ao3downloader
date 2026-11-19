Your library is one folder - on your computer, or `/Apps/FicFairy` in Dropbox. The app never keeps a copy anywhere else, but for one thing: to open a Dropbox library faster, your browser keeps a copy of its index (see below).

## Folders

| Folder | Holds |
| --- | --- |
| `works/` | Downloaded fics: html, epub, pdf... The listing shows a button per format beside each title: PDF opens in a tab, EPUB, MOBI and AZW3 are saved for your e-reader. |
| `indexing/` | The index: one JSON file per work, plus `series/` and `external/` |
| `collections/` | One JSON file per collection |
| `runs/` | One JSON file per run - the History tab |
| `hidden-works.json` | The fics you hid from the list (only the page reads it) |
| `images/` | Images saved separately, if you asked for them |

## File names

Every downloaded file is named the same way, and it can't be changed:

```
{work number} {title} - {author} {date AO3 last updated it}
1234567 The Trees Are Burning - library_of_alexandria 2026-08-23.html
```

- **The work number comes first** - that's how a file is matched to its index entry. To bring in a file from elsewhere, start its name with the AO3 work number and a space, `_`, `.` or `-`.
- **The date comes last** - it's the version the file holds, not when you downloaded it. That's how a later run knows AO3 has something newer.
- Long titles are shortened to fit `FileNameLength`. The date is never cut.
- Index JSON files carry no date, since each one is the fic's whole history.

## When a file is downloaded again

A copy is **outdated** when AO3's update date in the index is newer than the date in its name. Runs download a format only when you have no copy of it, or yours is outdated. **Overwrite** is the one exception.

An older copy is removed only once the new one is confirmed saved at full length. If it can't be removed, both stay, and the run lists it under *copies to check by hand*. A new file that arrives damaged is deleted and counted as a failure, leaving the old copy where it was.

A fic can finish on AO3 and be updated later. The update-incomplete pass won't see that; a full scan will.

## Index files

Each fic's JSON keeps a history: a new reading is added only when something changed, so you can see when it gained chapters.

```json
{
  "id": "1234567",
  "link": "https://archiveofourown.org/works/1234567",
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    { "indexed_on": "2026-09-01T10:00:00+00:00", "kudos": 12 },
    { "indexed_on": "2026-09-10T12:34:56+00:00", "kudos": 15 }
  ]
}
```

- `bookmarked` - whether you bookmarked it yourself. Works found through a series or collection are `false` until you do.
- `from_series`, `from_collections` - where else it was found.

## Collection files

A collection's file records what it holds, by number: `work_ids`, `bookmark_ids`, `external_ids` (external works have their own numbering) and `series_ids`. Opening a collection in the page shows the works you have indexed in full, and the rest by number with a link to AO3.

**Opening a Dropbox library.** Your browser keeps a copy of the library's index, so opening it again shows your works and collections straight away while Dropbox is checked, and only the index files that changed since are downloaded - after a run that updated 30 fics, that is 30 files, not thousands. The refresh icon beside *List refreshed* downloads the whole index again instead, and replaces the saved copy. Dropbox always has the last word: until the check is done the loading bar says the list is the saved copy, and runs and *Resolve issues* wait. **Clear cache** in User settings forgets the copy, and so does signing out of Dropbox, or Dropbox ending the app's access; nothing in Dropbox changes.

**After a run.** A run you watch to the end shows its changes in the list straight away. A background run, or one from another tab or device, writes without this page - once it has finished (successfully, or partly), the list reads the library again by itself and keeps your filters. *List refreshed* above the list says when it was last brought up to date from your library. The refresh icon beside *List refreshed* does the same on demand. While a run is going you can't change the library (switch between this computer and Dropbox, sign out, pick another folder) or refresh - the buttons say why when you hover over them.

**Not just your bookmarks.** The Bookmarks list shows every fic in your index. One that isn't an AO3 bookmark of yours - downloaded by its link, or brought in by a collection - has a badge saying so. Every entry also has a small icon in its top right corner, beside the date, saying where it came from - a ribbon for your AO3 bookmarks, a stack for a collection, a link for one downloaded by ID or URL, a download arrow for imported from an external source (a file already in your library that an import indexed - see [[Runs]]; hover it for the name) - and **Came from** in the Filter narrows by it: your AO3 bookmarks, an AO3 collection, imported, or downloaded by ID or URL. A **private** bookmark of yours has a small lock just left of its ribbon. **Your AO3 bookmarks always win**: a fic first found another way shows as your bookmark once a scan finds it on your bookmarks, and a bookmark you download again by ID or URL stays your bookmark. The Filter can also show just **bookmarks with a note** or **bookmarks you recommended**.

**Files with no index entry are listed too.** A file in `works/` that no index entry matches - one you put there yourself, say - still shows in the Works tab, marked **Not in your index**, with what its file name says: the title, the author, and a button for each format you have of it. Files with the same work number are one entry. Its date is the one in its name; if the name has none written the app's way, a date read loosely out of the name (marked *(best guess from filename)*), or failing that when the file last changed (*(best guess from filedate)*). These entries are only shown - nothing is renamed or fetched for them. **Look up its index from AO3 here** (also in the entry's ⋯ menu as **Look up its index**, and on the selection bar as **Look up N indexes** for the ticked entries) opens Resolve issues on its index question - for just those works, or every work with no entry - or **download the latest version of this work** fetches it. Each entry lists the full names of the files it was made from. A file whose name has no work number at all is shown by its name alone.

**Hiding a fic.** The eye button hides it from your lists; its files stay. To get it back, tick **Show hidden works** in the Filter and press **Unhide**. Each fic has a **⋯** menu too, with Hide/Unhide and Add to a collection for that fic. Series can be ticked and hidden, but not added to a collection - adding with one ticked tells you which series will be left out and asks first. Ticked fics can be hidden or unhidden together: the bar offers **Hide**/**Unhide** for one, **Hide all**/**Unhide all** for several, and both when they're a mix.

**Downloading from the list.** The **⋯** menu has **Download/update now**, which opens *Download/update a specific fic* with that fic filled in; with several ticked, the bar's **Download/update N works now** opens *several fics* with all of them. Series and external works don't have it, and are left out when ticked - download a series' fics from their own entries, and an external work isn't on AO3. An open collection has **Download/update all N works now** above its list. A fic only known by its number (one a collection lists that isn't in your index) says **download it now** too.

**Marking something as a bookmark yourself.** The **⋯** menu on a fic, external work or series also has **Mark as bookmark** / **Unmark as bookmark**, and the bar does the same for everything ticked. Only an entry marked as a bookmark counts as one - an entry from an older version of the app that says nothing either way is not, so mark those yourself. Your notes, tags and bookmark date are kept when you unmark something (they're just not shown); the next scan of your AO3 bookmarks puts back whatever AO3 says. Not while a run is going.

**Filtering the list.** The **Filter** panel narrows by title, author, dates and bookmark type, by **Downloaded as** (works with a copy in HTML, EPUB, PDF, MOBI or AZW3, or *Not downloaded*), and by tag: **Include** and **Exclude**, each with a fold per kind (Ratings, Warnings, Categories, Fandoms, Characters, Relationships, Additional Tags) and a box that suggests any tag in your library as you type. Every included tag must be on a work, and no excluded one. When a run you're watching ends, the list updates itself.

**Your own collections.** They are listed with the rest, their first pill saying *Collection made in Fic Fairy*. Make one with **+ New collection** on the Collections tab, or tick works in any listing and choose **Add to a collection** (one of yours, or **+ A new collection...**; closing that window unsaved makes nothing and keeps your ticks). A work is only ever in a collection once. Inside one of yours, **Remove from this collection** takes ticked works out and **Update collection details** (or the pencil beside its name, there or in the list) changes its name, description and tags - **Show every field AO3 collections have** offers the rest. They live in `collections/custom/` with `"custom": true`. Collections from AO3 can't be changed. Ticking needs a library the page can save to: a folder opened in Chrome or Edge, or Dropbox.

Re-indexing a collection whose counts haven't changed costs two requests, not hundreds. The one thing that misses is a work added and another removed between runs - delete the collection's JSON to force a full read.

**Opening a fic.** Any link to a fic - its title, or its number in History or a run's window - opens your downloaded HTML copy in a new tab when you have one. Ctrl-click (cmd-click on a Mac) to go to AO3 instead.
