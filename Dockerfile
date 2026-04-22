# 1. Use the official lightweight Python image
FROM python:3.11-slim

# 2. Set the working directory
WORKDIR /app

# 3. Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# 4. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application
COPY . .

# 6. Expose the port (Cloud Run defaults to 8080)
EXPOSE 8080

# 7. Run the application using Gunicorn for production
# Workers = 2 * CPU + 1 (For small Cloud Run instance, 1-2 workers is perfect)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "run:app"]
