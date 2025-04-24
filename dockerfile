# Example of a basic Dockerfile
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy your application code into the container
COPY . .

# Install dependencies
RUN pip install -r requirements.txt  # Ensure Flask is in requirements.txt

# Make sure to expose the correct port if needed (default is 5000 for Flask)
EXPOSE 5000

# Set the command to run your app
CMD ["flask", "run", "--host=0.0.0.0"]
