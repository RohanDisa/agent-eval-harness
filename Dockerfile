FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

COPY pyproject.toml README.md ./
COPY src ./src
COPY suites ./suites
COPY fixtures ./fixtures
COPY tests ./tests

RUN pip install --no-cache-dir -e ".[dev]"

ENTRYPOINT ["aeh"]
CMD ["tasks", "validate"]
