## AO3 asked me to slow down

AO3 limits how fast requests arrive. When it says wait, the run waits - often a few minutes - then carries on by itself. Nothing is lost.

If it happens a lot, raise `ExtraWaitTime` in [[Settings]] (default 15 seconds).

## The app won't open

- **Windows:** "Windows protected your PC" → **More info** → **Run anyway**.
- **Mac:** **System Settings > Privacy & Security > Open Anyway**. From Terminal, `xattr -dr com.apple.quarantine <the folder>` does the same.
- **Linux:** run `./"Start ao3downloader.sh"` from a terminal to see why. It needs a glibc at least as new as Ubuntu 22.04's.
- **"Seems to be running already":** close every ao3downloader window and start it again.

## I can't choose a folder

Saving to a folder needs Chrome, Chromium, Edge, Brave, Opera or Arc on a computer. Firefox, Safari and phones can't. Use Dropbox instead, or switch browsers. With a folder open in one of those, in the downloaded app (or in another browser on a computer), the run buttons and History's **Retry** are greyed out - hover for why, or click one to be told. You can still read the library.

## A run says Interrupted

The helper stopped mid-run - closed, crashed, or a deploy. **Resume** it from History, or run it again. See [[History and resuming]].

## Still stuck

[Open an issue](https://github.com/alexandria-p/FicFairy/issues). Say what you did, what happened, and your version (bottom of the page). If a run went wrong, attach its log: **History > Download log**. [[Logs]] lists every log the app keeps and where it is.
