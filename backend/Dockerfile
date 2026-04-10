# Use the official lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the Google Cloud server
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your Python files into the server
COPY . .

# Expose port 8080 (Google Cloud Run's default port)
EXPOSE 8080

# Command to run your FastAPI application using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]