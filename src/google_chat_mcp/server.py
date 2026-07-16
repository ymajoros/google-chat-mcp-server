"""Main server implementation for Google Chat MCP."""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    CallToolRequest,
    GetPromptRequest,
    ListPromptsRequest,
    ListToolsRequest,
    ListResourcesRequest,
    ReadResourceRequest,
    ListResourceTemplatesRequest,
    Resource,
    Prompt,
    PromptMessage,
    LATEST_PROTOCOL_VERSION,
)
from pydantic import BaseModel

from .auth.google_auth import GoogleChatAuth
from .content import to_content_blocks
from .tools import (
    MessageTools,
    SpaceTools,
    MemberTools,
    SearchTools,
    WebhookTools,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Config(BaseModel):
    """Server configuration."""
    
    # Authentication
    service_account_path: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None
    
    # Defaults
    default_space: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            service_account_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            default_space=os.getenv("GOOGLE_CHAT_DEFAULT_SPACE"),
        )


class GoogleChatMCPServer:
    """Main MCP server for Google Chat integration."""
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize the server with configuration."""
        self.config = config or Config.from_env()
        self.server = Server("google-chat-mcp")
        
        # Initialize authentication
        self.auth = GoogleChatAuth(
            service_account_path=self.config.service_account_path,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            refresh_token=self.config.refresh_token,
        )
        
        # Initialize tool handlers
        self.message_tools = MessageTools(self.auth, self.config.default_space)
        self.space_tools = SpaceTools(self.auth)
        self.member_tools = MemberTools(self.auth)
        self.search_tools = SearchTools(self.auth)
        self.webhook_tools = WebhookTools(self.auth)
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all MCP protocol handlers."""
        
        @self.server.list_tools()
        async def handle_list_tools(request: ListToolsRequest) -> List[Tool]:
            """Return all available tools."""
            tools = []
            
            # Add all tool categories
            tools.extend(self.message_tools.get_tools())
            tools.extend(self.space_tools.get_tools())
            tools.extend(self.member_tools.get_tools())
            tools.extend(self.search_tools.get_tools())
            tools.extend(self.webhook_tools.get_tools())
            
            return tools
        
        @self.server.call_tool()
        async def handle_call_tool(request: CallToolRequest) -> List[TextContent | ImageContent]:
            """Execute a tool and return results."""
            tool_name = request.params.name
            arguments = request.params.arguments or {}
            
            logger.info(f"Executing tool: {tool_name} with arguments: {arguments}")
            
            try:
                # Route to appropriate tool handler
                if tool_name in self.message_tools.get_tool_names():
                    result = await self.message_tools.execute(tool_name, arguments)
                elif tool_name in self.space_tools.get_tool_names():
                    result = await self.space_tools.execute(tool_name, arguments)
                elif tool_name in self.member_tools.get_tool_names():
                    result = await self.member_tools.execute(tool_name, arguments)
                elif tool_name in self.search_tools.get_tool_names():
                    result = await self.search_tools.execute(tool_name, arguments)
                elif tool_name in self.webhook_tools.get_tool_names():
                    result = await self.webhook_tools.execute(tool_name, arguments)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")
                
                # download_attachment and friends may return inline binary data;
                # to_content_blocks turns that into image / embedded-resource blocks.
                return to_content_blocks(result)
                    
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]
        
        @self.server.list_prompts()
        async def handle_list_prompts(request: ListPromptsRequest) -> List[Prompt]:
            """Return available prompts."""
            return [
                Prompt(
                    name="google-chat-help",
                    description="Get help with Google Chat MCP server",
                ),
                Prompt(
                    name="google-chat-examples",
                    description="See examples of Google Chat operations",
                ),
            ]
        
        @self.server.get_prompt()
        async def handle_get_prompt(request: GetPromptRequest) -> Prompt:
            """Return a specific prompt."""
            if request.params.name == "google-chat-help":
                return Prompt(
                    name="google-chat-help",
                    description="Get help with Google Chat MCP server",
                    messages=[
                        PromptMessage(
                            role="user",
                            content=TextContent(
                                type="text",
                                text="Show me how to use the Google Chat MCP server"
                            )
                        ),
                        PromptMessage(
                            role="assistant",
                            content=TextContent(
                                type="text",
                                text="""# Google Chat MCP Server Help

Available tools:

**Message Tools:**
- `send_message`: Send a message to a space
- `list_messages`: List recent messages
- `get_message`: Get a specific message
- `update_message`: Update a message
- `delete_message`: Delete a message

**Space Tools:**
- `create_space`: Create a new space
- `get_space`: Get space details
- `list_spaces`: List your spaces
- `update_space`: Update space settings
- `delete_space`: Delete a space

**Member Tools:**
- `add_member`: Add someone to a space
- `remove_member`: Remove someone from a space
- `list_members`: List space members
- `get_member`: Get member details

**Search Tools:**
- `search_messages`: Search across all spaces

**Webhook Tools:**
- `create_webhook`: Create an incoming webhook
- `send_webhook_message`: Send via webhook

Example usage:
```
send_message(space="spaces/AAAA1234567", text="Hello!")
```"""
                            )
                        )
                    ]
                )
            elif request.params.name == "google-chat-examples":
                return Prompt(
                    name="google-chat-examples",
                    description="See examples of Google Chat operations",
                    messages=[
                        PromptMessage(
                            role="user",
                            content=TextContent(
                                type="text",
                                text="Show me examples of using Google Chat tools"
                            )
                        ),
                        PromptMessage(
                            role="assistant",
                            content=TextContent(
                                type="text",
                                text="""# Google Chat Examples

## Send a simple message
```
send_message(
    space="spaces/AAAA1234567",
    text="Hello team! 👋"
)
```

## Send a card message
```
send_message(
    space="spaces/AAAA1234567",
    cards=[{
        "header": {
            "title": "Project Update",
            "subtitle": "Q4 2024"
        },
        "sections": [{
            "widgets": [{
                "textParagraph": {
                    "text": "Great progress on all fronts!"
                }
            }]
        }]
    }]
)
```

## Create a space and invite team
```
# Create space
space = create_space(
    display_name="Project Alpha",
    space_type="SPACE"
)

# Add members
add_member(
    space=space["name"],
    email="teammate@company.com"
)
```

## Search for messages
```
results = search_messages(
    query="budget proposal",
    spaces=["spaces/AAAA1234567"],
    limit=10
)
```"""
                            )
                        )
                    ]
                )
            else:
                raise ValueError(f"Unknown prompt: {request.params.name}")
        
        @self.server.list_resources()
        async def handle_list_resources(request: ListResourcesRequest) -> List[Resource]:
            """List available resources (spaces, etc.)."""
            resources = []
            
            try:
                # List accessible spaces as resources
                spaces = await self.space_tools.list_spaces()
                for space in spaces.get("spaces", []):
                    resources.append(
                        Resource(
                            uri=f"gchat://space/{space['name']}",
                            name=space.get("displayName", space["name"]),
                            description=f"Google Chat space: {space.get('type', 'SPACE')}",
                            mimeType="application/vnd.google.chat.space",
                        )
                    )
            except Exception as e:
                logger.error(f"Error listing resources: {e}")
            
            return resources
        
        @self.server.read_resource()
        async def handle_read_resource(request: ReadResourceRequest) -> str:
            """Read a resource (get space details, recent messages, etc.)."""
            uri = request.params.uri
            
            if uri.startswith("gchat://space/"):
                space_name = uri.replace("gchat://space/", "")
                try:
                    # Get space details
                    space = await self.space_tools.get_space({"space": space_name})
                    
                    # Get recent messages
                    messages = await self.message_tools.list_messages({
                        "space": space_name,
                        "limit": 10
                    })
                    
                    import json
                    return json.dumps({
                        "space": space,
                        "recent_messages": messages
                    }, indent=2)
                except Exception as e:
                    return f"Error reading space: {str(e)}"
            else:
                return f"Unknown resource type: {uri}"
    
    async def run(self, transport: str = "stdio", host: str = "localhost", port: int = 8000):
        """Run the MCP server with specified transport."""
        # Initialize authentication
        await self.auth.initialize()
        logger.info(f"Google Chat MCP server started with {transport} transport")
        
        if transport == "stdio":
            # Use stdio_server for MCP communication
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream, 
                    write_stream, 
                    self.server.create_initialization_options()
                )
        elif transport == "http":
            # Use HTTP transport
            from mcp.server.streamable_http import StreamableHTTPServerTransport
            
            # Create HTTP transport
            logger.info(f"Starting HTTP server on {host}:{port}")
            
            # HTTP transport needs to be implemented differently
            # For now, let's use a simple approach with uvicorn
            import uvicorn
            from fastapi import FastAPI
            from fastapi.responses import Response
            import json
            
            app = FastAPI()
            
            @app.post("/mcp")
            async def mcp_endpoint(request: dict):
                # This is a simplified HTTP endpoint for MCP
                # In a full implementation, this would handle the full MCP protocol
                return {"error": "HTTP transport not fully implemented yet"}
            
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            raise ValueError(f"Unsupported transport: {transport}")


def main():
    """Main entry point."""
    import argparse
    import dotenv
    dotenv.load_dotenv()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Google Chat MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                       help="Transport type (default: stdio)")
    parser.add_argument("--host", default="localhost",
                       help="Host for HTTP transport (default: localhost)")
    parser.add_argument("--port", type=int, default=8000,
                       help="Port for HTTP transport (default: 8000)")
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create and run server
    server = GoogleChatMCPServer()
    asyncio.run(server.run(transport=args.transport, host=args.host, port=args.port))


if __name__ == "__main__":
    main()