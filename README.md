## What is this?
This is a program intended to help you download fanfiction from the [Archive of Our Own](https://archiveofourown.org/) in bulk. This program is primarily intended to work with links to the Archive of Our Own itself, but has a secondary function of downloading any [Pinboard](https://pinboard.in/) bookmarks that link to the Archive of Our Own. You can ignore the Pinboard functionality if you don't know what Pinboard is or don't use Pinboard. This program is lightly tested and is currently very likely to have bugs.

## Instructions

- install [python](https://www.python.org/downloads/) 
    - make sure to choose the option "add to PATH" when you are installing python. if you do not do this the program is even less likely to work correctly than it already was.
- clone (or download and unzip) the repository. the "repository" means the folder containing the code. you can download the repository by clicking on the "Code" button in github and selecting "Download ZIP"
- windows: double-click on "ao3downloader.cmd"
- other platforms: ao3downloader should work on any platform that supports python, however, you will need to do your own research into how to run python programs on your system.

## Menu Options Explanation

- 'download from ao3 link' - this works for most links to [ao3](https://archiveofourown.org/). for example, you can use this to download a single work, a series, or any ao3 page that contains links to works or series (such as your bookmarks or an author's works). the program will download multiple pages automatically without the need to enter the next page link manually.
- 'download latest version of incomplete fics (ao3 epub files only)' - you can use this to check a folder on your computer (and any subfolders) for epub files downloaded from ao3 that are incomplete works. for each incomplete fic found, the program will check ao3 to see if there are any new chapters, and if so, will download the new version to the downloads folder. apologies but this does not work for filetypes other than epub.
- 'download pinboard xml document' - this is the first step in downloading your ao3 bookmarks from [pinboard](https://pinboard.in/). ignore this if you don't use pinboard. to get the api token go to settings -> password on the pinboard website.
- 'download bookmarks from pinboard xml document' - this is the second step in downloading your ao3 bookmarks from pinboard. ignore this if you don't use pinboard or if you haven't yet downloaded the pinboard xml document.
- 'convert logfile into interactable html' - all downloads from ao3 (and some other actions) are logged in a file called log.jsonl in the downloads folder, along with information such as whether or not the download was successful, details about errors encountered, and so on. this option converts log.jsonl into a much more human-readable, searchable and sortable html file that can be opened in any browser. the file is saved in the downloads folder and is called 'logvisualization.html'

## Notes

- The purpose of entering your ao3 login information is to download archive-locked works or anything else that is not visible when you are not logged in. If you don't care about that, there is no need to enter your login information.
- You should be able to guess the approximate runtime in seconds by taking the number of works to be downloaded times five. This is a very rough estimate as many factors can affect the total runtime.
- For multi-page downloads from ao3, a message will be printed to the console each time a new page starts downloading. If you need to stop the download in the middle, take note of the last page downloaded. When you restart, enter the link to that specific page instead of the first page, to avoid repeating downloads as much as possible. Note that pinboard bookmarks are not paginated in the same way, so this will not work if you are downloading bookmarks from pinboard.
- **IMPORTANT**: some of your input choices are saved in settings.json. In some cases you will not be able to change these choices unless you clear your settings by deleting settings.json. In addition, please note that saved settings include passwords and keys and are saved in plain text. Use appropriate caution with this file.
