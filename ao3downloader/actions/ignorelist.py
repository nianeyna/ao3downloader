from ao3downloader import strings
from ao3downloader.fileio import FileOps

def action():
    fileops = FileOps()

    with open('ignorelist.txt', 'a', encoding='utf-8'): pass

    message = (
        '''ignorelist.txt has been added to the main script folder. 
           you can use this file to perma-skip downloading works 
           or series that you know you don't want to download. 
           to use this file open it in a text editor (the default 
           text editor for Windows is called Notepad. on Mac, you can 
           use TextEdit) and add the links you want to ignore, one on 
           each line. these should be links to ao3 works or series. 
           other links will be ignored. each link MUST begin with 
           https://archiveofourown.org and be placed at the start of a 
           new line. you may also *optionally* add a comment after each 
           link. comments must begin with a SEMICOLON followed by a 
           SPACE: `; ` and must not contain any newline characters 
           (the entire comment must be on the same line as the link). 
           otherwise, you can write anything you want in the comment. 
           comments are for your personal reference only and are not 
           used by the script.
           ''')

    print(message)

    print('do you want to check the log file for deleted links and add them to the ignore list automatically?')

    logfile = fileops.load_logfile()
