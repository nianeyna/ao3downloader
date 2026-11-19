## 1. Download the app

Get the zip for your computer from the [latest release](https://github.com/alexandria-p/FicFairy/releases/latest).

| Computer | Zip | Start it by |
| --- | --- | --- |
| Windows | `ficfairy-ao3downloader-windows.zip` | double-clicking `ficfairy.exe` |
| Mac, M1 or later | `ficfairy-ao3downloader-macos-apple-silicon.zip` | double-clicking `Start FicFairy.command` |
| Intel Mac | `ficfairy-ao3downloader-macos-intel.zip` | double-clicking `Start FicFairy.command` |
| Linux (x86_64) | `ficfairy-ao3downloader-linux-x86_64.zip` | running `Start FicFairy.sh` |

Unzip it somewhere you'll keep it. A window opens, and your browser opens the app at `http://localhost:4200`. **Leave the window open** while you use the app; close it to stop.

The app isn't signed, so the first start is blocked once:

- **Windows:** "Windows protected your PC" - click **More info**, then **Run anyway**.
- **Mac:** click **Done**, then **System Settings > Privacy & Security > Open Anyway**. The script then clears the warning for the whole folder.
- **Linux:** your file manager may ask whether to run the script - choose **Run**.

## 2. Choose where your library lives

Choose **This computer** or **Dropbox** at the top of the page.

- **Dropbox** - works in any browser, on any device. A run can carry on with the page closed ([background runs](Runs#background-runs)).
- **A folder on this computer** - needs a Chromium browser on a computer: Chrome, Chromium, Edge, Brave, Opera or Arc. Firefox, Safari and phones can't write to a folder. **Keep the page open for the whole run**

## 3. Run a Quick Scan

On the **Bookmarks** tab, press **Quick Scan**, choose file types, and log in to AO3.

The first one reads your whole bookmarks listing and downloads everything. Every Quick Scan after that only looks at what changed since the last one. See [[Runs]].

## Running it without the app

For development, or to run from source with [uv](https://docs.astral.sh/uv/):

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\generate_build_artifacts.ps1   # bundle into build\
cd build
powershell.exe -ExecutionPolicy Bypass -File .\Start-Application.ps1
```
