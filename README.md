## What is this?
This is a program intended to help you download fanfiction from the [Archive of Our Own](https://archiveofourown.org/) in bulk. This program is primarily intended to work with links to the Archive of Our Own itself, but has a secondary function of downloading any [Pinboard](https://pinboard.in/) bookmarks that link to the Archive of Our Own. You can ignore the Pinboard functionality if you don't know what Pinboard is or don't use Pinboard.

## Instructions

- install python [version 3.9.9](https://www.python.org/downloads/release/python-399/)
    - as of the time of writing, any version of python that was released after version 3.9.9 WILL NOT work with this script. MAKE SURE you are using version 3.9.9 or earlier. To check which version of python you have installed:
        - windows: open a command prompt and enter "python --version"
        - mac: open a terminal window and enter "python3 --version"
    - make sure to choose the option "add to PATH" when you are installing python.
- download the repository as a zip file. the "repository" means the folder containing the code. you can download the repository by clicking on the "Code" button in github and selecting "Download ZIP"
- unzip the zip file you just downloaded. this will create a folder. open it. if you see a file called "ao3downloader.py" then you're in the right place.
- windows: double-click on "ao3downloader.cmd"
- mac:
    - open a terminal window pointed to the folder containing "ao3downloader.py"
    - enter the following commands one by one:
        ```
        python3 -m venv venv
        source venv/bin/activate
        python3 -m pip install --upgrade pip
        pip install -r requirements.txt
        python3 ao3downloader.py
        ```
    - after this initial setup, when you want to run the program you only need to enter:
        ```
        source venv/bin/activate
        python3 ao3downloader.py
        ```
    - note that if you delete the "venv" folder for any reason you will need to do the initial setup again.
- other platforms: ao3downloader should work on any platform that supports python, however, you will need to do your own research into how to run python programs on your system.

## Menu Options Explanation

- 'download from ao3 link' - this works for most links to [ao3](https://archiveofourown.org/). for example, you can use this to download a single work, a series, or any ao3 page that contains links to works or series (such as your bookmarks or an author's works). the program will download multiple pages automatically without the need to enter the next page link manually.
- 'download latest version of incomplete fics (ao3 epub files only)' - you can use this to check a folder on your computer (and any subfolders) for epub files downloaded from ao3 that are incomplete works. for each incomplete fic found, the program will check ao3 to see if there are any new chapters, and if so, will download the new version to the downloads folder. apologies but this does not work for filetypes other than epub.
- 'download pinboard xml document' - this is the first step in downloading your ao3 bookmarks from [pinboard](https://pinboard.in/). ignore this if you don't use pinboard. to get the api token go to settings -> password on the pinboard website.
- 'download bookmarks from pinboard xml document' - this is the second step in downloading your ao3 bookmarks from pinboard. ignore this if you don't use pinboard or if you haven't yet downloaded the pinboard xml document.
- 'convert logfile into interactable html' - all downloads from ao3 (and some other actions) are logged in a file called log.jsonl in the downloads folder, along with information such as whether or not the download was successful, details about errors encountered, and so on. this option converts log.jsonl into a much more human-readable, searchable and sortable html file that can be opened in any browser. the file is saved in the downloads folder and is called 'logvisualization.html'

## Notes

- The purpose of entering your ao3 login information is to download archive-locked works or anything else that is not visible when you are not logged in. If you don't care about that, there is no need to enter your login information.
- Try to keep your ao3 browsing to a minimum while the script is running. It won't break anything, but it may cause you to hit ao3's limit on how many hits to the site you are allowed within a certain time frame. This limit is per user, or per IP if you are not logged in. If this happens, the script will pause for 5 minutes to let the limit reset, and you may see a "Retry later" message when you try to open an ao3 page during that time. Don't be alarmed by this, just wait it out.
- You should be able to guess the approximate runtime in seconds by taking the number of works to be downloaded times five. This is a very rough estimate as many factors can affect the total runtime.
- If the script encounters a work that is part of a series, it will also download the entire series that the work is a part of.
- For multi-page downloads from ao3, a message will be printed to the console each time a new page starts downloading. If you need to stop the download in the middle, take note of the last page downloaded before you close the window. When you restart, enter the link to that specific page instead of the first page, to avoid repeating downloads as much as possible. Note that pinboard bookmarks are not paginated in the same way, so this will not work if you are downloading bookmarks from pinboard.
- **IMPORTANT**: some of your input choices are saved in settings.json. In some cases you will not be able to change these choices unless you clear your settings by deleting settings.json (or editing it, if you are comfortable with json). In addition, please note that saved settings include passwords and keys and are saved in plain text. **Use appropriate caution with this file.**

## Troubleshooting
- If you are able to create logvisualization.html (menu option 'v'), take a look through the logs to see if there are any helpful error messages.
- If there are no logs or the logs are unhelpful, look for a folder called "venv" inside the repository. Delete "venv" and try re-running the script.
- If deleting venv doesn't work, try deleting the entire repository and re-downloading from github (but remember to save your existing downloads if you have any!)
- If re-downloading the repository doesn't work, try uninstalling and reinstalling python. 
    - Make sure you install python 3 version 3.9.9 or earlier.
    - Make sure to choose the option "add to PATH" during the installation.
- If reinstalling python doesn't work, [see this stackoverflow answer](https://stackoverflow.com/a/58773979).
- If you have tried all of the above and it still doesn't work, see below for how to send me a bug report.

## Questions? Comments? Bug reports?
Feel free to email me at nianeyna@gmail.com. Please include "ao3downloader" in the subject line. If you are reporting a bug, please describe exactly what you did to make the bug happen to the best of your ability. (More is more! Be as detailed as possible.) Optionally when reporting bugs, it is also helpful if you include log.jsonl in the email as an attachment. 

(Please note that while I will absolutely do my best to get back to you, I can't make any promises - I have a job, etc.)
