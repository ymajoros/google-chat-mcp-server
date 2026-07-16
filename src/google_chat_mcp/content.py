"""Helpers for turning tool results into MCP content blocks."""

import json
import urllib.parse
from typing import Any, List, Union

from mcp.types import (
    TextContent,
    ImageContent,
    EmbeddedResource,
    BlobResourceContents,
)

Content = Union[TextContent, ImageContent, EmbeddedResource]


def to_content_blocks(result: Any) -> List[Content]:
    """Convert a tool result into a list of MCP content blocks.

    Tools that return binary data (e.g. ``download_attachment``) set a
    ``_media`` key on their result dict holding ``{data_b64, mime_type,
    filename}``. Those become a text summary plus an inline ``ImageContent``
    (for ``image/*``) or an ``EmbeddedResource`` blob. Everything else is
    serialized to a single ``TextContent``.
    """
    if isinstance(result, dict) and "_media" in result:
        summary = {k: v for k, v in result.items() if k != "_media"}
        payload = result["_media"]
        mime = payload.get("mime_type") or "application/octet-stream"
        data_b64 = payload["data_b64"]
        blocks: List[Content] = [
            TextContent(type="text", text=json.dumps(summary, indent=2))
        ]
        if mime.startswith("image/"):
            blocks.append(ImageContent(type="image", data=data_b64, mimeType=mime))
        else:
            safe_name = urllib.parse.quote(payload.get("filename", "file"), safe="")
            blocks.append(
                EmbeddedResource(
                    type="resource",
                    resource=BlobResourceContents(
                        uri=f"attachment://download/{safe_name}",
                        mimeType=mime,
                        blob=data_b64,
                    ),
                )
            )
        return blocks

    if isinstance(result, str):
        return [TextContent(type="text", text=result)]
    if isinstance(result, dict):
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    return [TextContent(type="text", text=str(result))]
