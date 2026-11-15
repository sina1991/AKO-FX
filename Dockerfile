FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AKO_DB=/data/ako.db
WORKDIR /app
RUN groupadd --gid 10001 ako && useradd --uid 10001 --gid ako --no-create-home ako && mkdir /data && chown ako:ako /data
COPY --chown=ako:ako ako_fx /app/ako_fx
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "ako_fx.server", "--host", "0.0.0.0"]
