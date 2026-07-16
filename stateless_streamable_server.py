#!/usr/bin/env python3
"""
Google Chat MCP Server - Stateless Streamable HTTP
Based on the official MCP SDK example for stateless HTTP transport
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import click
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolRequest,
    ListToolsRequest,
    Tool,
    TextContent,
    ServerCapabilities,
)

# Import our existing Google Chat tools
from src.google_chat_mcp.auth.google_auth import GoogleChatAuth
from src.google_chat_mcp.content import to_content_blocks
from src.google_chat_mcp.tools import (
    MessageTools,
    SpaceTools,
    MemberTools,
    SearchTools,
    WebhookTools,
)

# Configure logging
logger = logging.getLogger("google-chat-mcp-server")


class GoogleChatMCPApplication:
    """Google Chat MCP Server Application."""
    
    def __init__(self):
        """Initialize the MCP application."""
        # Create the MCP server
        self.app = Server("google-chat-mcp")
        
        # Tools will be initialized later
        self.auth = None
        self.message_tools = None
        self.space_tools = None
        self.member_tools = None
        self.search_tools = None
        self.webhook_tools = None
        
        # Configure initialization options
        self.app.create_initialization_options = lambda: InitializationOptions(
            server_name="google-chat-mcp",
            server_version="0.1.0",
            capabilities=ServerCapabilities(
                tools={},  # We support tools
            ),
        )
        
        # Register handlers
        self._register_handlers()
    
    async def initialize_tools(self):
        """Initialize Google Chat API tools."""
        try:
            # Initialize authentication
            self.auth = GoogleChatAuth(
                service_account_path=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
                client_id=os.getenv("GOOGLE_CLIENT_ID"),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            )
            await self.auth.initialize()
            
            # Initialize tool handlers
            default_space = os.getenv("GOOGLE_CHAT_DEFAULT_SPACE")
            self.message_tools = MessageTools(self.auth, default_space)
            self.space_tools = SpaceTools(self.auth)
            self.member_tools = MemberTools(self.auth)
            self.search_tools = SearchTools(self.auth)
            self.webhook_tools = WebhookTools(self.auth)
            
            logger.info("Google Chat tools initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Chat tools: {e}")
            raise
    
    def _register_handlers(self):
        """Register MCP protocol handlers."""
        
        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            """List all available Google Chat tools."""
            logger.debug("Handling list_tools request")
            
            if not self.message_tools:
                logger.warning("Tools not initialized yet")
                return []
            
            tools = []
            
            # Collect all tools from each category
            tools.extend(self.message_tools.get_tools())
            tools.extend(self.space_tools.get_tools())
            tools.extend(self.member_tools.get_tools())
            tools.extend(self.search_tools.get_tools())
            tools.extend(self.webhook_tools.get_tools())
            
            logger.info(f"Returning {len(tools)} tools")
            return tools
        
        @self.app.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
            """Execute a Google Chat tool."""
            tool_name = name
            arguments = arguments or {}
            
            logger.info(f"Executing tool: {tool_name} with arguments: {arguments}")
            
            try:
                # Route to appropriate tool handler
                result = None
                
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
                    error_msg = f"Unknown tool: {tool_name}"
                    logger.error(error_msg)
                    return [TextContent(type="text", text=error_msg)]
                
                # download_attachment and friends may return inline binary data;
                # to_content_blocks turns that into image / embedded-resource blocks.
                logger.debug(f"Tool {tool_name} executed successfully")
                return to_content_blocks(result)
                    
            except Exception as e:
                error_msg = f"Error executing tool {tool_name}: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return [TextContent(type="text", text=error_msg)]


# Global app instance
mcp_app = GoogleChatMCPApplication()


# ASGI app creation


def create_starlette_app(json_response: bool = False) -> Starlette:
    """Create the Starlette application."""
    # Session manager will be created in lifespan
    session_manager_container = {"manager": None}
    
    @asynccontextmanager
    async def app_lifespan(app: Starlette):
        """Application lifespan with session manager."""
        # Initialize tools first
        await mcp_app.initialize_tools()
        logger.info("Google Chat MCP server started")
        
        # Create and run session manager
        session_manager = StreamableHTTPSessionManager(
            mcp_app.app,
            stateless=True,  # Use stateless mode
            json_response=json_response,
        )
        
        session_manager_container["manager"] = session_manager
        
        async with session_manager.run():
            yield
        
        logger.info("Google Chat MCP server shutting down")
    
    # Create the endpoint handler
    async def mcp_endpoint(scope: Scope, receive: Receive, send: Send):
        """Handle MCP requests."""
        if session_manager_container["manager"] is None:
            # Send error response if manager not ready
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [[b"content-type", b"text/plain"]],
            })
            await send({
                "type": "http.response.body",
                "body": b"Service not ready",
            })
            return
            
        await session_manager_container["manager"].handle_request(scope, receive, send)
    
    app = Starlette(
        lifespan=app_lifespan,
        routes=[
            Mount("/mcp", app=mcp_endpoint),
        ],
    )
    
    return app


@click.command()
@click.option("--port", "-p", default=8004, help="Port to listen on")
@click.option(
    "--log-level",
    "-l",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
    help="Log level",
)
@click.option(
    "--response", 
    "-r",
    type=click.Choice(["sse", "json"]),
    default="sse",
    help="Response type (sse for streaming, json for single response)",
)
def main(port: int, log_level: str, response: str):
    """Run the Google Chat MCP server with Streamable HTTP transport."""
    # Load environment variables
    import dotenv
    dotenv.load_dotenv()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Create ASGI app
    use_json_response = response == "json"
    app = create_starlette_app(json_response=use_json_response)
    
    # Print startup message
    print("🤖 Google Chat MCP Server (Stateless Streamable HTTP)")
    print("🔗 Google Chat API integration enabled")
    print("📋 Using proper MCP protocol over HTTP")
    print(f"📡 Response type: {'JSON' if use_json_response else 'SSE streaming'}")
    print(f"\n🌐 Server will be available at: http://localhost:{port}/mcp")
    print("\n🚀 Starting server...")
    
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=log_level.lower())


if __name__ == "__main__":
    main()