FROM python:3.12-slim
WORKDIR /app
COPY pool /app/pool
RUN useradd --uid 10001 --create-home pool
USER 10001:10001
EXPOSE 8765
ENTRYPOINT ["python", "-m", "pool.server"]
CMD ["--root", "/srv/homebrew-pool", "--bind", "0.0.0.0", "--port", "8765", "--token-file", "/run/secrets/pool.token"]
