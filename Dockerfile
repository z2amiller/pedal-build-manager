FROM python:3.11-slim

WORKDIR /app

# Install app dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.9" \
    "uvicorn[standard]>=0.29" \
    "pydantic>=2.0" \
    "jsonschema>=4.0" \
    "referencing>=0.28" \
    "git+https://github.com/z2amiller/kicad-pedal-common.git"

# Copy application code
COPY app/ app/

# Data directory — override with a bind mount or named volume in production
RUN mkdir -p /data
VOLUME /data

ENV BUILDER_DB_PATH=/data/builder.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
