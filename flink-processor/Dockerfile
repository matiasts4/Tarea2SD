# Use official Flink image as base
FROM flink:1.18.0-scala_2.12

# Install Python and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create symbolic link for python
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install kafka-python instead of PyFlink (simpler and faster)
RUN pip3 install kafka-python==2.0.2

# Copy application code
COPY main.py /opt/flink/main.py

# Set working directory
WORKDIR /opt/flink

# Run the application
CMD ["python3", "-u", "main.py"]