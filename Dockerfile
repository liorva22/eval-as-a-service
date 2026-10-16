FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY eaas ./eaas
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "eaas.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
