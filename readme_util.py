'''Extremely crunchy parser intended to yell at me if I forget to update references to string constants in the readme'''

import re
import ao3downloader.strings as strings

def get_text() -> str:
    with open('README.md') as f:
        return f.read()

def check_value(text: str, pos: int) -> str:
    start = re.search('<!--', text[pos:])
    value = text[pos:pos+start.start()]
    pos = pos + start.end()
    end = re.search('-->', text[pos:])
    variable = text[pos:pos+end.start()]
    try:
        realval = str(getattr(strings, variable)).replace('{', '').replace('}', '')
    except AttributeError:
        return f'Bad variable name. Variable: {variable} Value: {value}'
    if value not in realval: 
        return f'Bad value. Variable: {variable} Expected: {realval} Actual: {value}'
    return None

text = get_text()
errors = list(filter(lambda e: e is not None, [check_value(text, x.end()) for x in re.finditer('<!--CHECK-->', text)]))
if errors:
    output = '; '.join(errors)
    print(output)
