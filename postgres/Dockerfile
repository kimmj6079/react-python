FROM postgres:16-alpine

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD pg_isready -U postgres

# docker build -t react-python-db .
# docker run -d --name react-python-db -p 5432:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=app -v db-data:/var/lib/postgresql/data react-python-db
