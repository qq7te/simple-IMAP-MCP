# Use Alpine Linux with Python 3.12 for smallest image size
FROM python:3.12-alpine

# Set working directory
WORKDIR /app

# Install build dependencies (required for some Python packages)
# These will be removed after installation to keep image small
RUN apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    libffi-dev \
    && apk add --no-cache \
    libffi

# Copy package metadata and source code
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

# Remove build dependencies to reduce image size
RUN apk del .build-deps

# Expose the default MCP port
EXPOSE 8993

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8993/health || exit 1

# Set default environment variables
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8993

# Run the MCP server
CMD ["mcp-imap-server"]
