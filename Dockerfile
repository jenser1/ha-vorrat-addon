FROM python:3.11-alpine

# Install bash
RUN apk add --no-cache bash

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy app
COPY app/ .

# Copy and register run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
