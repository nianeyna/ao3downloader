from datetime import datetime
import ao3downloader.fileio as fileio
import ao3downloader.pinboard as pinboard
import ao3downloader.strings as strings

def action():

    # get api token
    api_token = fileio.setting(
        strings.PINBOARD_PROMPT_API_TOKEN, 
        strings.SETTINGS_FILE_NAME, 
        strings.SETTING_API_TOKEN)

    # get date
    print(strings.PINBOARD_PROMPT_DATE)
    getdate = True if input() == strings.PROMPT_YES else False
    if getdate:
        date_format = 'mm/dd/yyyy'
        print(strings.PINBOARD_PROMPT_ENTER_DATE.format(date_format))
        inputdate = input()
        date = datetime.strptime(inputdate, '%m/%d/%Y')
    else:
        date = None

    print(strings.PINBOARD_INFO_GETTING_BOOKMARKS)
    pinboard.download_xml(api_token, date, strings.PINBOARD_FILE_NAME)
