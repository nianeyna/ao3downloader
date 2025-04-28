FROM python:3.11.4-slim

WORKDIR /app
VOLUME /app/downloads /app/settings

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . /app

# Set the command to run your application
ENTRYPOINT ["/app/ao3downloader-container.sh"]
