#!/bin/sh
# If they exist, we're copying the external settings files to the expected place
if [ -f /app/settings/settings.ini ]; then
	cp /app/settings/settings.ini /app
fi
if [ -f /app/settings/settings.json ]; then
	cp /app/settings/settings.json /app
fi
python ao3downloader.py $@
# Since we are done, copying the updated settings.json file to the external storage
if [ -f /app/settings.json ]; then
	cp /app/settings.json /app/settings
fi