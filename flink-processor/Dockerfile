# Use official Flink image as base
FROM flink:1.18.0-scala_2.12

# Install Python and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create symbolic link for python
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install PyFlink
RUN pip3 install apache-flink==1.18.0

# Download Kafka SQL connector JAR
RUN wget -P /opt/flink/lib/ \
    https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.1.0-1.18/flink-sql-connector-kafka-3.1.0-1.18.jar

# Copy application code
COPY main.py /opt/flink/main.py

# Set working directory
WORKDIR /opt/flink

# Set environment variables
ENV PYFLINK_CLIENT_EXECUTABLE=python3

# Run the application
CMD ["python3", "main.py"]