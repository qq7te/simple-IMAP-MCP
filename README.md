# MCP IMAP Server

A lightweight [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that exposes your IMAP mailbox through tools, enabling AI assistants to interact with your email.

## Features

- 🔍 **Search emails** with flexible criteria (sender, subject, date range, text, etc.)
- 📬 **List mailboxes** and folders in your IMAP account
- 📧 **Retrieve messages** with full headers, body content, and attachment metadata
- 📎 **Download attachments** (base64 encoded)
- ✅ **Mark messages** as seen/unseen
- 🔒 **Secure** - uses standard IMAP authentication
- 🌐 **Flexible deployment** - supports both local (stdio) and remote (HTTP) modes

## Installation

### Prerequisites

- Python 3.10 or higher
- An IMAP-enabled email account (Gmail, Outlook, etc.)

### Setup

1. Clone this repository:
```bash
git clone <repository-url>
cd mcp-imap-server
```

2. Create and activate a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install the package:
```bash
pip install -U pip
pip install -e .
```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure your IMAP settings:

```bash
cp .env.example .env
```

#### Required Settings

- `IMAP_HOST` - Your IMAP server hostname (e.g., `imap.gmail.com`)
- `IMAP_USERNAME` - Your email address or username
- `IMAP_PASSWORD` - Your password or app-specific password

#### Optional Settings

- `IMAP_PORT` - IMAP server port (default: `993`)
- `IMAP_SSL` - Use SSL/TLS connection (default: `true`)
- `IMAP_STARTTLS` - Use STARTTLS (default: `false`)
- `IMAP_TIMEOUT_SECONDS` - Connection timeout (default: `30`)

### Email Provider Examples

**Gmail:**
```env
IMAP_HOST=imap.gmail.com
IMAP_USERNAME=your-email@gmail.com
IMAP_PASSWORD=your-app-password
```
*Note: Gmail requires [app-specific passwords](https://support.google.com/accounts/answer/185833) when 2FA is enabled.*

**Outlook/Office 365:**
```env
IMAP_HOST=outlook.office365.com
IMAP_USERNAME=your-email@outlook.com
IMAP_PASSWORD=your-password
```

## Usage

### Running with Docker (Recommended)

The easiest way to run the server is using Docker:

1. Build the Docker image:
```bash
docker build -t mcp-imap-server .
```

2. Run with environment variables:
```bash
docker run -d \
  --name mcp-imap-server \
  -p 8993:8993 \
  -e IMAP_HOST=imap.gmail.com \
  -e IMAP_USERNAME=your-email@gmail.com \
  -e IMAP_PASSWORD=your-app-password \
  mcp-imap-server
```

3. Or use docker-compose with your `.env` file:
```bash
docker-compose up -d
```

The server will be available at `http://localhost:8993/mcp`

To view logs:
```bash
docker logs -f mcp-imap-server
```

To stop:
```bash
docker-compose down
# or
docker stop mcp-imap-server
```

### Running as HTTP Server (Native)

This mode allows AI clients on other machines (like Warp) to connect to your email server:

```bash
source .venv/bin/activate

# Listen on all interfaces
MCP_HOST=0.0.0.0 MCP_PORT=8993 mcp-imap-server

# Or listen on localhost only (more secure)
MCP_HOST=127.0.0.1 MCP_PORT=8993 mcp-imap-server
```

The MCP endpoint will be available at:
- Local: `http://127.0.0.1:8993/mcp`
- Remote: `http://<server-ip>:8993/mcp`

You can test the server with:
```bash
curl http://localhost:8993/health
```

### Running in stdio Mode (Local Process)

For local AI clients that spawn the server as a subprocess:

```bash
source .venv/bin/activate
MCP_TRANSPORT=stdio mcp-imap-server
```

### Connecting with Warp

In Warp, configure the MCP server by adding to your MCP settings:

```json
{
  "mcpServers": {
    "imap": {
      "url": "http://<server-ip>:8993/mcp"
    }
  }
}
```

## Available Tools

The server exposes the following MCP tools:

### `list_mailboxes`
Returns all available mailboxes/folders in your IMAP account.

**Returns:** List of mailboxes with names, delimiters, and flags.

### `search_messages`
Search for messages with various criteria.

**Parameters:**
- `mailbox` (str, default: "INBOX") - Mailbox to search in
- `from_` (str, optional) - Filter by sender email
- `to` (str, optional) - Filter by recipient email
- `subject` (str, optional) - Filter by subject text
- `text` (str, optional) - Search in message body
- `unseen` (bool, optional) - Filter by read/unread status
- `since` (str, optional) - Messages since date (YYYY-MM-DD)
- `before` (str, optional) - Messages before date (YYYY-MM-DD)
- `limit` (int, default: 20) - Maximum number of results

**Returns:** List of message summaries with UID, subject, sender, date, flags, and size.

### `get_message`
Retrieve full message content by UID.

**Parameters:**
- `uid` (int, required) - Message UID
- `mailbox` (str, default: "INBOX") - Mailbox containing the message
- `include_body` (bool, default: true) - Include message body
- `include_html` (bool, default: false) - Include HTML body
- `max_body_chars` (int, default: 20000) - Maximum body length

**Returns:** Full message with headers, body, flags, and attachment metadata.

### `download_attachment`
Download a message attachment by UID.

**Parameters:**
- `uid` (int, required) - Message UID
- `mailbox` (str, default: "INBOX") - Mailbox containing the message
- `attachment_index` (int, default: 0) - 0-based index among attachments
- `filename` (str, optional) - Exact filename match (preferred when known)
- `offset_bytes` (int, default: 0) - Start offset into the attachment payload (for chunked downloads)
- `max_bytes` (int, default: 10000000) - If > 0, truncate returned bytes to this limit

**Returns:** Attachment metadata plus `content_base64`.

### `set_seen`
Mark a message as read or unread.

**Parameters:**
- `uid` (int, required) - Message UID
- `mailbox` (str, default: "INBOX") - Mailbox containing the message
- `seen` (bool, default: true) - Mark as seen (true) or unseen (false)

**Returns:** Updated message flags.

## Security Considerations

- ⚠️ **App-Specific Passwords**: Use app-specific passwords instead of your main account password when possible
- 🔒 **Firewall**: If running in HTTP mode on `0.0.0.0`, ensure your firewall restricts access appropriately
- 🌐 **Network**: For remote access, consider using a VPN or SSH tunnel instead of exposing the server directly to the internet
- 📝 **Environment Variables**: Never commit your `.env` file - it's already in `.gitignore`
- 🔑 **Read-Only by Default**: Most operations are read-only except `set_seen`

## Development

### Project Structure

```
mcp-imap-server/
├── src/
│   └── mcp_imap_server/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py      # Main MCP server and tool definitions
│       ├── config.py      # Configuration management
│       └── imap.py        # IMAP client wrapper
├── pyproject.toml
├── README.md
├── .env.example
└── .gitignore
```

### Running Tests

To test the server functionality:

1. Ensure your `.env` file is configured correctly
2. Start the server in one terminal
3. Use an MCP client or curl to test the endpoints

## Troubleshooting

### Connection Errors

- Verify your IMAP credentials are correct
- Check if your email provider requires app-specific passwords
- Ensure the IMAP port (usually 993) is not blocked by your firewall
- Try enabling debug logging by checking server output

### Authentication Failures

- Some providers (like Gmail) require enabling "Less secure app access" or using OAuth2
- Use app-specific passwords when 2FA is enabled
- Verify the username format (some providers need full email, others just the username)

### Performance

- Use the `limit` parameter in `search_messages` to reduce result size
- Adjust `max_body_chars` in `get_message` to limit body content size
- Consider using the `unseen` filter to only fetch unread messages

## License

GPL-3.0-only – see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

If you encounter issues or have questions, please open an issue on the GitHub repository.
