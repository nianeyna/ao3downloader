## What is this?
This is a program intended to help you download fanfiction from the [Archive of Our Own](https://archiveofourown.org/) in bulk. This program is primarily intended to work with links to the Archive of Our Own itself, but has a secondary function of downloading any [Pinboard](https://pinboard.in/) bookmarks that link to the Archive of Our Own. You can ignore the Pinboard functionality if you don't know what Pinboard is or don't use Pinboard.

## Announcements

As of March 8, 2022 I have changed how file names are generated to allow for the inclusion of non-alphanumeric characters (cnovel fans rejoice). If you have a Process going on which relies on file names for the same fic being the same, please take note of this if/when you download the new version of the code.

## Instructions

- install python [version 3.9.9](https://www.python.org/downloads/release/python-399/)
    - as of the time of writing, any version of python that was released *after* version 3.9.9 or *before* 3.9.0 WILL NOT work with this script. MAKE SURE you are using a version of python between 3.9.0 and 3.9.9. To check which version of python you have installed:
        - windows: open a command prompt and enter "python --version"
        - mac: open a terminal window and enter "python3 --version"
    - make sure to choose the option "add to PATH" when you are installing python.
- download the repository as a zip file. the "repository" means the folder containing the code. you can download the repository by clicking on the "Code" button in github and selecting "Download ZIP"
- unzip the zip file you just downloaded. this will create a folder. open it. if you see a file called "ao3downloader.py" then you're in the right place.
- windows: double-click on "ao3downloader.cmd"
- mac:
    - open a terminal window pointed to the folder containing "ao3downloader.py".
        - You can do this by right-clicking on the folder, going to Services at the bottom of the menu, and clicking "New Terminal at Folder". Alternatively, you can type "cd " and drag the folder to the terminal to copy the folder path.
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

- **'<!--CHECK-->download from ao3 link<!--ACTION_DESCRIPTION_AO3-->'** - this works for most links to [ao3](https://archiveofourown.org/). for example, you can use this to download a single work, a series, or any ao3 page that contains links to works or series (such as your bookmarks or an author's works). the program will download multiple pages automatically without the need to enter the next page link manually.
- **'<!--CHECK-->get all work links from an ao3 listing (saves links only)<!--ACTION_DESCRIPTION_LINKS_ONLY-->'** - instead of downloading works, this will simply get a list of all the work links on the page you specify (as well as subsequent pages) and save them in a .txt file inside the downloads folder (one link on each line). this is useful if you prefer to download fics through FanFicFare or some other method, rather than using the ao3 download buttons. this option is much, much faster than a full download - usually only a few seconds per page.
- **'<!--CHECK-->download latest version of incomplete fics<!--ACTION_DESCRIPTION_UPDATE-->'** - you can use this to check a folder on your computer (and any subfolders) for files downloaded from ao3 that are incomplete works. for each incomplete fic found, the program will check ao3 to see if there are any new chapters, and if so, will download the new version to the downloads folder.
- **'<!--CHECK-->download missing fics from series<!--ACTION_DESCRIPTION_UPDATE_SERIES-->'** - checks for files downloaded from ao3 that are part of a series, and for each series found, checks the series page on ao3 and downloads any fics in the series that are not already in your library.
- **'<!--CHECK-->re-download fics saved in one format in a different format<!--ACTION_DESCRIPTION_REDOWNLOAD-->'** - checks for *all* files downloaded from ao3 and redownloads every fic it finds (if possible - failed downloads due to deletion or other reasons will be logged). good if you change your mind about what format you want your library to be in. (file type choices for this option are not saved to settings.)
- **'<!--CHECK-->download bookmarks from pinboard<!--ACTION_DESCRIPTION_PINBOARD-->'** - download ao3 bookmarks from [pinboard](https://pinboard.in/). ignore this if you don't use pinboard. to get the api token go to settings -> password on the pinboard website.
- **'<!--CHECK-->convert logfile into interactable html<!--ACTION_DESCRIPTION_VISUALIZATION-->'** - all downloads from ao3 (and some other actions) are logged in a file called <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> in the '<!--CHECK-->logs<!--LOG_FOLDER_NAME-->' folder (if this folder does not exist it means no logs have been generated yet), along with information such as whether or not the download was successful, details about errors encountered, and so on. this option converts <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> into a much more human-readable, searchable and sortable (click on the column headers to sort) html file that can be opened in any browser. the file is called '<!--CHECK-->logvisualization.html<!--VISUALIZATION_FILE_NAME-->' and is saved in the same place as <!--CHECK-->log.jsonl<!--LOG_FILE_NAME-->.

## Notes

- **The purpose of entering your ao3 login information** is to download archive-locked works or anything else that is not visible when you are not logged in. If you don't care about that, there is no need to enter your login information.
- **Try to keep your ao3 browsing to a minimum** while the script is running. It won't break anything, but it may cause you to hit ao3's limit on how many hits to the site you are allowed within a certain time frame. This limit is per user, or per IP if you are not logged in. If this happens, the script will pause for 5 minutes to let the limit reset, and you may see a "Retry later" message when you try to open an ao3 page during that time. Don't be alarmed by this, just wait it out.
- **If you choose to '<!--CHECK-->get works from series links<!--AO3_PROMPT_SERIES-->'** then if the script encounters a work that is part of a series, it will also download the entire series that the work is a part of. This can *dramatically* extend the amount of time the script takes to run. If you don't want this, choose 'n' when you get this prompt. (Note that this will cause the program to ignore *all* series links, including e.g. series that you have bookmarked.)
- **If you choose to '<!--CHECK-->download embedded images<!--AO3_PROMPT_IMAGES-->'** the script will look for image links on all works it downloads and attempt to save those images to an '<!--CHECK-->images<!--IMAGE_FOLDER_NAME-->' subfolder. Images will be titled with the name of the fic + 'imgxxx' to distinguish them. If you are saving in PDF format, images will also be saved inside the PDF file itself (regardless of whether you choose this option or not). For all other formats, only the image *link* is preserved inside the file.
    - Note that this feature does not encode any association between the downloaded images and the fic file aside from the file name. 
    - Should an image download fail, the details of the failure will be logged in the log file with the message '<!--CHECK-->Problem getting image<!--ERROR_IMAGE-->' along with the work link and the image link. It's a good idea to check the log file for these messages, since you may still be able to download the image manually or track it down some other way.
- **If you need to stop a download in the middle,** you can just close the window. When you restart the script:
    - If you are using the option '<!--CHECK-->download from ao3 link<!--ACTION_DESCRIPTION_AO3-->', you will be given an option to restart the download from the page you left off on. Some downloads may be repeated.
    - If you are using the option '<!--CHECK-->download bookmarks from pinboard<!--ACTION_DESCRIPTION_PINBOARD-->' or '<!--CHECK-->re-download fics saved in one format in a different format<!--ACTION_DESCRIPTION_REDOWNLOAD-->', the list of fics to download will be retrieved as normal but will then be filtered to remove work links that meet the following conditions:
        - A record of a download attempt for that link is present in the log file AND
            - There is a fic with the same title already in the downloads folder OR
            - The download was marked as unsuccessful
    - If you are using the option '<!--CHECK-->download latest version of incomplete fics<!--ACTION_DESCRIPTION_UPDATE-->' or '<!--CHECK-->download missing fics from series<!--ACTION_DESCRIPTION_UPDATE_SERIES-->', just make sure to add any fics you don't want to download again to your library (that is, the folder you entered when prompted '<!--CHECK-->input path to folder containing files you want to check for updates<!--UPDATE_PROMPT_INPUT-->') and clean up any old versions before re-starting the download.
    - Most methods of avoiding repeat downloads rely on a file called <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> which is generated by the script. Make sure not to move, delete, or modify <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> if you want these features to work. (Using the option to generate the log visualization file is fine.)
- **When checking for incomplete fics,** the code makes certain assumptions about how fic files are formatted. I have tried to make this logic as flexible as possible, but there is still some possibility that not all incomplete fics will be properly identified by the updater, especially if the files are old (since ao3 may have made changes to how they format fics for download over time) or have been edited.
- **IMPORTANT**: some of your input choices are saved in <!--CHECK-->settings.json<!--SETTINGS_FILE_NAME-->. In some cases you will not be able to change these choices unless you clear your settings by deleting <!--CHECK-->settings.json<!--SETTINGS_FILE_NAME--> (or editing it, if you are comfortable with json). In addition, please note that saved settings include passwords and keys and are saved in plain text. **Use appropriate caution with this file.**

## Troubleshooting
- If you are able to create <!--CHECK-->logvisualization.html<!--VISUALIZATION_FILE_NAME--> (menu option 'v'), take a look through the logs to see if there are any helpful error messages.
- If there are no logs or the logs are unhelpful, look for a folder called "venv" inside the repository. Delete "venv" and try re-running the script.
- If deleting venv doesn't work, try deleting the entire repository and re-downloading from github (but remember to save your existing downloads if you have any!)
- If re-downloading the repository doesn't work, try uninstalling and reinstalling python. 
    - Make sure you install a version between 3.9.0 and 3.9.9 (inclusive). Version 3.9.9 exactly is strongly preferred.
    - Make sure to choose the option "add to PATH" during the installation.
- If reinstalling python doesn't work, [see this stackoverflow answer](https://stackoverflow.com/a/58773979).
- If you have tried all of the above and it still doesn't work, see below for how to send me a bug report.

## Questions? Comments? Bug reports?
Feel free to head over to [the discussion board](https://github.com/nianeyna/ao3downloader/discussions) and make a post, or create an [issue](https://github.com/nianeyna/ao3downloader/issues). You can also email me at nianeyna@gmail.com if you prefer. Please include "ao3downloader" in the subject line of emails about the downloader. If you are reporting a bug, please describe exactly what you did to make the bug happen to the best of your ability. (More is more! Be as detailed as possible.)

(Please note that while I will absolutely do my best to get back to you, I can't make any promises - I have a job, etc.)
