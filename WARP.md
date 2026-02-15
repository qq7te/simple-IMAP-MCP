# WARP.md - Agent Development Guide

## Project Overview

**mcp-imap-server** is a Model Context Protocol (MCP) server implementation that exposes IMAP email functionality through standardized tools. This enables AI assistants (like those in Warp) to interact with email accounts programmatically.

### Architecture

- **Framework**: FastMCP (MCP SDK for Python)
- **Protocol**: Model Context Protocol 1.0+
- **Transport Modes**: 
  - `streamable-http` (default) - HTTP-based for remote clients
  - `stdio` - Standard I/O for local subprocess communication
  - `sse` - Server-Sent Events (supported but not commonly used)
- **Primary Dependencies**:
  - `mcp>=1.0.0` - MCP SDK
  - `imapclient>=3.0.1` - IMAP client library
  - `python-dotenv>=1.0.1` - Environment variable management

### Key Design Decisions

1. **Stateless HTTP Mode**: The server uses `stateless_http=True` to ensure each HTTP request is independent, avoiding session ID issues common with MCP over HTTP.

2. **Security Disabled for Non-Localhost**: When binding to non-localhost addresses (e.g., `0.0.0.0`), DNS rebinding protection is disabled. This is necessary for remote access but should be documented as a security consideration for users.

3. **Read-Only by Default**: Most operations (search, fetch, list) are read-only. Only `set_seen` modifies server state, making the tool safer for exploratory use.

4. **Connection Pooling**: Each tool call creates a fresh IMAP connection via context manager, ensuring clean state but potentially impacting performance for rapid sequential operations.

## Project Structure

```
src/mcp_imap_server/
├── __init__.py          # Package initialization
├── __main__.py          # Entry point for python -m execution
├── server.py            # Main MCP server, tool definitions, FastMCP setup
├── config.py            # Configuration dataclass and env variable parsing
└── imap.py              # IMAP client wrapper, message parsing utilities
```

### Module Responsibilities

**server.py**:
- Defines the FastMCP instance with transport settings
- Implements 4 MCP tools: `list_mailboxes`, `search_messages`, `get_message`, `set_seen`
- Contains extensive logging for debugging HTTP transport issues
- Handles transport selection and server startup

**config.py**:
- `ImapConfig` dataclass for IMAP connection parameters
- Environment variable parsing with sensible defaults
- Validation of required credentials

**imap.py**:
- IMAP connection management via context manager
- Email message parsing (RFC822, MIME multipart)
- Body extraction (text/html with encoding handling)
- Attachment metadata extraction
- Date parsing utilities

## Tool Specifications

### 1. `list_mailboxes()`
Returns all mailboxes/folders in the IMAP account.

**Output Schema**:
```python
[
  {
    "name": str,          # Folder name (e.g., "INBOX", "Sent")
    "delimiter": str,     # Hierarchy delimiter (usually "/" or ".")
    "flags": [str]        # IMAP flags (e.g., "\\Noselect", "\\HasChildren")
  }
]
```

### 2. `search_messages(...)`
Search for messages with flexible criteria.

**Parameters**:
- `mailbox: str = "INBOX"` - Target folder
- `from_: str | None` - Sender filter
- `to: str | None` - Recipient filter
- `subject: str | None` - Subject substring match
- `text: str | None` - Body text search
- `unseen: bool | None` - Filter by seen/unseen status
- `since: str | None` - Date filter (YYYY-MM-DD format)
- `before: str | None` - Date filter (YYYY-MM-DD format)
- `limit: int = 20` - Max results (returns most recent N)

**Output Schema**:
```python
[
  {
    "uid": int,                    # Unique message ID (stable)
    "mailbox": str,                # Source mailbox
    "envelope": {                  # Parsed envelope data
      "date": str,
      "subject": str,
      "from": [{"name": str, "email": str}],
      "to": [{"name": str, "email": str}],
      # ... other envelope fields
    },
    "flags": [str],                # IMAP flags (e.g., "\\Seen")
    "size_bytes": int | None,      # RFC822 size
    "internaldate": str | None     # Server's internal date (ISO format)
  }
]
```

**Implementation Notes**:
- Criteria combined with AND logic
- Results sorted by UID (ascending), limit takes last N for recency
- Fetches ENVELOPE, FLAGS, RFC822.SIZE, INTERNALDATE for efficiency

### 3. `get_message(...)`
Retrieve full message content by UID.

**Parameters**:
- `uid: int` - Message UID (from search results)
- `mailbox: str = "INBOX"` - Source folder
- `include_body: bool = True` - Fetch body content
- `include_html: bool = False` - Include HTML body (only if include_body=True)
- `max_body_chars: int = 20000` - Truncation limit for body text

**Output Schema**:
```python
{
  "uid": int,
  "mailbox": str,
  "headers": {
    "subject": str,
    "from": str,
    "to": str,
    "cc": str,
    "date": str,
    "message_id": str
  },
  "flags": [str],
  "size_bytes": int | None,
  "internaldate": str | None,
  "attachments": [
    {
      "filename": str | None,
      "content_type": str,
      "size_bytes": int | None
    }
  ],
  "text": str,          # Plain text body (if include_body=True)
  "html": str | None  # HTML body (if include_html=True)
}
```

**Implementation Notes**:
- Fetches full RFC822 message and parses locally
- Body extraction handles multipart MIME, encoding detection
- Attachments are metadata-only (no content download)
- Body truncation applies per-part for multipart messages

### 4. `set_seen(...)`
Mark a message as read or unread.

**Parameters**:
- `uid: int` - Target message UID
- `mailbox: str = "INBOX"` - Source folder
- `seen: bool = True` - True to mark read, False to mark unread

**Output Schema**:
```python
{
  "uid": int,
  "mailbox": str,
  "flags": [str]  # Updated flags after operation
}
```

**Implementation Notes**:
- Only tool that modifies server state
- Uses IMAP `STORE` command to add/remove `\Seen` flag
- Requires readonly=False folder selection

## Configuration

### Environment Variables

**Required**:
- `IMAP_HOST` - IMAP server hostname
- `IMAP_USERNAME` - Account username or email
- `IMAP_PASSWORD` - Account password (app-specific recommended)

**Optional**:
- `IMAP_PORT` (default: 993) - IMAP server port
- `IMAP_SSL` (default: true) - Use SSL/TLS
- `IMAP_STARTTLS` (default: false) - Use STARTTLS upgrade
- `IMAP_TIMEOUT_SECONDS` (default: 30) - Connection timeout

**MCP Transport Configuration**:
- `MCP_TRANSPORT` (default: "streamable-http") - Transport mode: stdio, sse, or streamable-http
- `MCP_HOST` (default: "127.0.0.1") - Bind address for HTTP transports
- `MCP_PORT` (default: 8993) - Port for HTTP transports
- `MCP_MOUNT_PATH` (optional) - Mount path for SSE transport

### Files

- `.env` - Local configuration (gitignored)
- `.env.example` - Template with example values
- `pyproject.toml` - Package metadata, dependencies, build config

## Development Workflows

### Local Testing

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Edit .env with valid IMAP credentials

# Run in stdio mode (for MCP client testing)
MCP_TRANSPORT=stdio mcp-imap-server

# Run in HTTP mode (for remote testing)
MCP_HOST=127.0.0.1 MCP_PORT=8993 mcp-imap-server

# Test HTTP health endpoint
curl http://localhost:8993/health
```

### Adding New Tools

1. **Define the tool function** in `server.py` with the `@mcp.tool()` decorator
2. **Add docstring** - becomes the tool description in MCP
3. **Type hints** - used for parameter schema generation
4. **Implement with `get_config()`** for IMAP access
5. **Use `imap_connect(cfg)` context manager** for connection handling
6. **Handle errors gracefully** - tools should not crash the server

Example pattern:
```python
@mcp.tool()
def my_tool(param: str, optional: int = 10) -> dict[str, Any]:
    """Tool description shown to AI."""
    cfg = get_config()
    with imap_connect(cfg) as client:
        # ... IMAP operations
        pass
    return {"result": "data"}
```

### Debugging

The server includes extensive logging (level: DEBUG by default):
- All HTTP requests/responses logged
- IMAP connection lifecycle logged
- Tool invocations logged with parameters

Check logs for:
- Transport initialization issues
- IMAP authentication failures
- Message parsing errors
- MCP protocol errors

### Common Pitfalls

1. **Binary vs String Keys**: IMAPClient sometimes returns `bytes` or `str` keys in fetch results depending on server. Use `_normalize_fetch_item()` helper.

2. **UID vs Sequence Number**: Always use UIDs (unique, stable) not sequence numbers (change on expunge).

3. **Readonly Selection**: Most operations use `readonly=True` for safety. Only `set_seen` requires `readonly=False`.

4. **Encoding Issues**: Email bodies can have various encodings. The `extract_bodies()` function handles common cases but may fail on exotic encodings.

5. **Connection Timeout**: Long operations may hit IMAP timeout. Consider increasing `IMAP_TIMEOUT_SECONDS` for slow servers.

## Extending the Server

### Potential Enhancements

1. **Additional IMAP Operations**:
   - `delete_message(uid)` - Move to trash or expunge
   - `move_message(uid, to_mailbox)` - Move between folders
   - `add_flag(uid, flag)` - Generic flag management
   - `create_mailbox(name)` - Folder management

2. **Advanced Search**:
   - Support for IMAP SEARCH extensions (if available)
   - Saved search queries
   - Full-text search on body content

3. **Attachment Handling**:
   - `download_attachment(uid, attachment_index)` - Fetch attachment content
   - Base64 encoding for binary attachments

4. **Caching**:
   - Connection pooling for performance
   - Message metadata caching (with invalidation)
   - Folder list caching

5. **OAuth2 Support**:
   - Replace password auth with OAuth2 for Gmail/Outlook
   - Token refresh handling

6. **Error Recovery**:
   - Automatic reconnection on connection drops
   - Retry logic for transient failures

### Security Enhancements

1. **Authentication**:
   - Add API key or bearer token auth for HTTP mode
   - Support for multiple IMAP accounts

2. **Network Security**:
   - TLS for HTTP transport
   - Proper CORS configuration
   - Rate limiting

3. **Access Control**:
   - Mailbox-level permissions
   - Read-only mode enforcement

## Testing Strategy

### Manual Testing

```bash
# Test with MCP inspector (if available)
mcp-inspector http://localhost:8993/mcp

# Test with curl (for HTTP transport)
curl -X POST http://localhost:8993/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### Integration Testing

For automated testing:
1. Use a test IMAP account (not production)
2. Set up known test messages
3. Verify tool outputs match expected schemas
4. Test edge cases (empty mailboxes, large messages, etc.)

### Unit Testing

Key areas to unit test:
- `config.py`: Environment variable parsing, validation
- `imap.py`: Message parsing, encoding handling, date parsing
- `server.py`: Tool parameter validation, error handling

## Deployment Considerations

### Production Deployment

1. **Environment Variables**: Use secure secret management (not `.env` files)
2. **Network**: Deploy behind reverse proxy with TLS
3. **Monitoring**: Log aggregation, health check monitoring
4. **Resource Limits**: Set connection limits, timeout policies
5. **User Isolation**: If supporting multiple users, ensure IMAP connection isolation

### Docker Deployment (Potential)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8993
EXPOSE 8993
CMD ["mcp-imap-server"]
```

## Related Resources

- [Model Context Protocol Spec](https://modelcontextprotocol.io)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [IMAPClient Documentation](https://imapclient.readthedocs.io/)
- [RFC 3501 - IMAP4rev1](https://tools.ietf.org/html/rfc3501)

## Maintenance Notes

### Known Issues

1. **Stateless HTTP**: Each request creates a new IMAP connection. For high-frequency usage, consider adding connection pooling.

2. **Large Messages**: Very large emails may hit the `max_body_chars` limit. Consider streaming or chunked retrieval.

3. **DNS Rebinding Protection**: Disabled for non-localhost binding. Document this security tradeoff clearly for users.

### Future Roadmap

- OAuth2 authentication support
- WebSocket transport for real-time push notifications
- Message composition and sending (SMTP integration)
- Advanced search with IMAP extensions
- Performance optimization with connection pooling
