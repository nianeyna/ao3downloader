FicFairy keeps five kinds of log. Only the first two are ones you would normally open - the rest are for when something has gone wrong with the app itself.

| Log | What it holds | Where it is | How long it lasts |
| --- | --- | --- | --- |
| **Run log** | Everything a run said in its window, one line each, stamped in UTC. | In the run's record in your library's `runs/` folder. **History > Download log**. | Up to 5,000 lines a run (the oldest give way). Only the 100 most recent runs keep theirs. |
| **Visit log** | What you did on this visit: tabs, clicks, library reads, windows opened, runs started and ended, settings changed, and any page error. Never what you type in a box. | In the page's memory only. **User settings > Advanced > Download the full visit log for this session**. | Gone when you close or reload the page. Keeps the last 2,000 entries. |
| **App window** | What the app prints in its own window (Windows, Mac, Linux): each request the helper answers, and each run's lines tagged with the run. | The window the app opened. Not saved anywhere. | Until you close the window. |
| **Helper's log file** | A line for each download attempt and request error, with its link and when (UTC). More with `EnableDebugLogging`. | `logs/log.jsonl`, beside the app. | Up to 100 MB, then its oldest lines give way. Nothing in the app reads it. |
| **Update log** | What **Update now** did: the swap of the old app for the new, and why it failed if it did. | `update/update.log` beside the app (and `update/swap-output.txt`, what the swap script itself printed). | Up to 10 MB each, then their oldest lines give way. |

## Run log

The one to attach to a bug report. Each History entry offers **Download log**: the run's links, file types, options and settings, then every line it said. It never names your AO3 password, and the run's settings never name your folders.

- **Longer logs**: User settings > Advanced > **Run logs** sets the **Maximum length of each log file (in lines)**, from 500 to 50,000. A run past it keeps its end, where whatever went wrong is, and says how many lines it dropped.
- **Older runs**: with **Only keep logs of the last 100 runs** on (the default), each run that ends takes the log out of runs older than the newest 100. They stay in `runs/` - History, Retry and the quick scan still read them - and History says the log was taken out. Turn it off to keep every log.
- **A run still going** is read from the helper, so its log is up to the last line said, not the last save.

On the app on your computer both settings are in `settings.ini` (`RunLogMaxLines`, `KeepLogsOfRecentRunsOnly`). On the hosted copy they are this browser's, sent with every run.

## Visit log

For a problem that is not a run - a tab that will not load, a button that does nothing. It is never written anywhere. Lower its length in User settings > Advanced to drop the oldest entries at once.


## App window and helper's log file

`EnableConsoleLogging` (on in the downloaded app) is what fills the app's window. A hosted helper prints the same lines to its host's own log, only with it on. `EnableDebugLogging` adds detail to `logs/log.jsonl`. Neither the window nor the host's log ever shows the passcode or your AO3 password.

On the app on your computer, User settings > Advanced > **Log files on this computer** sets how large the helper's log file and the update logs may grow (0 for no limit), and shows where each one is. The hosted copy has neither.

Every step of an **Update now** - asked, refused and why, downloading, the app closing and coming back, or failing - goes in the visit log too.
