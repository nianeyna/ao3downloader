'''Extremely crunchy parser intended to yell at me if I forget to update references to string constants in the readme'''

import re
import ao3downloader.strings as strings

def get_text():
    with open('README.md') as f:
        return f.read()

def check_values(text, pos):
    start = re.search('<!--', text[pos:])
    value = text[pos:pos+start.start()]
    pos = pos + start.end()
    end = re.search('-->', text[pos:])
    variable = text[pos:pos+end.start()]
    realval = getattr(strings, variable)
    if value not in realval: return (realval, value)

text = get_text()
errors = list(filter(lambda e: e is not None, [check_values(text, x.end()) for x in re.finditer('<!--CHECK-->', text)]))
if errors:
    output = ';'.join([f'Expected: {error[0]} Actual: {error[1]}' for error in errors])
    print(output)
