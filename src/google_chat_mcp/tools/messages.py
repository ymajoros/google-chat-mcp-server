"""Message management tools for Google Chat."""

import base64
import binascii
import io
import logging
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from mcp.types import Tool
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .base import BaseTool

logger = logging.getLogger(__name__)


class MessageTools(BaseTool):
    """Tools for managing Google Chat messages."""
    
    def get_tools(self) -> List[Tool]:
        """Return list of message-related tools."""
        return [
            Tool(
                name="send_message",
                description="Send a message to a Google Chat space",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "space": {
                            "type": "string",
                            "description": "Space name (e.g., 'spaces/AAAA1234567') or leave empty for default space"
                        },
                        "text": {
                            "type": "string",
                            "description": "Plain text message to send"
                        },
                        "cards": {
                            "type": "array",
                            "description": "Card messages (rich content)",
                            "items": {"type": "object"}
                        },
                        "thread": {
                            "type": "string",
                            "description": "Thread key to reply to (optional)"
                        }
                    },
                    "required": ["text"]
                }
            ),
            Tool(
                name="list_messages",
                description="List messages in a Google Chat space",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "space": {
                            "type": "string",
                            "description": "Space name (e.g., 'spaces/AAAA1234567') or leave empty for default space"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of messages to return (default: 25, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 25
                        },
                        "order_by": {
                            "type": "string",
                            "description": "Order messages by (create_time desc or create_time)",
                            "enum": ["create_time desc", "create_time"],
                            "default": "create_time desc"
                        }
                    }
                }
            ),
            Tool(
                name="get_message",
                description="Get a specific message by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Full message name (e.g., 'spaces/AAAA1234567/messages/xyz')"
                        }
                    },
                    "required": ["message"]
                }
            ),
            Tool(
                name="update_message",
                description="Update an existing message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Full message name (e.g., 'spaces/AAAA1234567/messages/xyz')"
                        },
                        "text": {
                            "type": "string",
                            "description": "New text content"
                        },
                        "cards": {
                            "type": "array",
                            "description": "New card content",
                            "items": {"type": "object"}
                        },
                        "update_mask": {
                            "type": "string",
                            "description": "Fields to update (default: 'text,cards')",
                            "default": "text,cards"
                        }
                    },
                    "required": ["message"]
                }
            ),
            Tool(
                name="delete_message",
                description="Delete a message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Full message name (e.g., 'spaces/AAAA1234567/messages/xyz')"
                        }
                    },
                    "required": ["message"]
                }
            ),
            Tool(
                name="download_attachment",
                description=(
                    "Download a file attached to a Google Chat message and return its "
                    "content inline (images as an image block, other files as an embedded "
                    "resource). Works for uploaded-content attachments (the common case). "
                    "Provide either a 'message' name (the tool picks the attachment at "
                    "'attachment_index', default 0) or a raw 'resource_name'. "
                    "Drive-file attachments are not supported (they need the Drive API)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Full message name (e.g. 'spaces/AAA/messages/xyz'). The message's attachments are looked up automatically."
                        },
                        "resource_name": {
                            "type": "string",
                            "description": "Attachment data resource name (attachmentDataRef.resourceName). Use instead of 'message' when you already have it."
                        },
                        "attachment_index": {
                            "type": "integer",
                            "description": "Which attachment to download when a message has several (default: 0).",
                            "minimum": 0,
                            "default": 0
                        },
                        "filename": {
                            "type": "string",
                            "description": "Override the reported file name (optional; defaults to the attachment's contentName)."
                        }
                    }
                }
            ),
            Tool(
                name="send_image_message",
                description=(
                    "Post a message to a Google Chat space with a file/image attachment. "
                    "Provide the file inline as base64 ('file_base64') or as an http(s) URL "
                    "to fetch ('file_url'). Optional 'text' caption. The file is uploaded via "
                    "the Chat media API and then posted as a message attachment."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "space": {
                            "type": "string",
                            "description": "Space name (e.g. 'spaces/AAAA1234567') or leave empty for the default space."
                        },
                        "text": {
                            "type": "string",
                            "description": "Optional caption text to send with the attachment."
                        },
                        "file_base64": {
                            "type": "string",
                            "description": "The file contents, base64-encoded. Use this or 'file_url'."
                        },
                        "file_url": {
                            "type": "string",
                            "description": "An http(s) URL the server will fetch the file from. Use this or 'file_base64'."
                        },
                        "filename": {
                            "type": "string",
                            "description": "File name to attach (e.g. 'chart.png'). Recommended; used to infer content type."
                        },
                        "content_type": {
                            "type": "string",
                            "description": "MIME type (optional; inferred from filename/URL when omitted)."
                        },
                        "thread": {
                            "type": "string",
                            "description": "Thread key to reply into (optional)."
                        }
                    }
                }
            )
        ]

    def get_tool_names(self) -> List[str]:
        """Return list of tool names."""
        return [
            "send_message",
            "list_messages",
            "get_message",
            "update_message",
            "delete_message",
            "download_attachment",
            "send_image_message"
        ]
    
    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a message tool."""
        await self._ensure_authenticated()
        
        if tool_name == "send_message":
            return await self.send_message(arguments)
        elif tool_name == "list_messages":
            return await self.list_messages(arguments)
        elif tool_name == "get_message":
            return await self.get_message(arguments)
        elif tool_name == "update_message":
            return await self.update_message(arguments)
        elif tool_name == "delete_message":
            return await self.delete_message(arguments)
        elif tool_name == "download_attachment":
            return await self.download_attachment(arguments)
        elif tool_name == "send_image_message":
            return await self.send_image_message(arguments)
        else:
            raise ValueError(f"Unknown message tool: {tool_name}")
    
    async def send_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Send a message to a space."""
        try:
            service = self._get_service()
            space = self._validate_space(args.get("space"))
            
            # Build message body
            message_body = {}
            
            if "text" in args:
                message_body["text"] = args["text"]
            
            if "cards" in args:
                message_body["cards"] = args["cards"]
            
            # Add thread if specified
            if "thread" in args:
                message_body["thread"] = {"name": args["thread"]}
            
            # Send the message
            result = service.spaces().messages().create(
                parent=space,
                body=message_body
            ).execute()
            
            logger.info(f"Message sent successfully to {space}")
            return {
                "success": True,
                "message": result,
                "message_id": result.get("name"),
                "space": space
            }
            
        except HttpError as e:
            return self._handle_api_error(e, "send_message")
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return {"error": str(e)}
    
    async def list_messages(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List messages in a space."""
        try:
            service = self._get_service()
            space = self._validate_space(args.get("space"))
            limit = args.get("limit", 25)
            order_by = args.get("order_by", "create_time desc")
            
            result = service.spaces().messages().list(
                parent=space,
                pageSize=min(limit, 100),
                orderBy=order_by
            ).execute()
            
            messages = result.get("messages", [])
            logger.info(f"Retrieved {len(messages)} messages from {space}")
            
            return {
                "success": True,
                "messages": messages,
                "count": len(messages),
                "space": space
            }
            
        except HttpError as e:
            return self._handle_api_error(e, "list_messages")
        except Exception as e:
            logger.error(f"Unexpected error listing messages: {e}")
            return {"error": str(e)}
    
    async def get_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get a specific message."""
        try:
            service = self._get_service()
            message_name = args["message"]
            
            result = service.spaces().messages().get(
                name=message_name
            ).execute()
            
            logger.info(f"Retrieved message {message_name}")
            return {
                "success": True,
                "message": result
            }
            
        except HttpError as e:
            return self._handle_api_error(e, "get_message")
        except Exception as e:
            logger.error(f"Unexpected error getting message: {e}")
            return {"error": str(e)}
    
    async def update_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing message."""
        try:
            service = self._get_service()
            message_name = args["message"]
            update_mask = args.get("update_mask", "text,cards")
            
            # Build update body
            message_body = {}
            if "text" in args:
                message_body["text"] = args["text"]
            if "cards" in args:
                message_body["cards"] = args["cards"]
            
            result = service.spaces().messages().patch(
                name=message_name,
                updateMask=update_mask,
                body=message_body
            ).execute()
            
            logger.info(f"Updated message {message_name}")
            return {
                "success": True,
                "message": result
            }
            
        except HttpError as e:
            return self._handle_api_error(e, "update_message")
        except Exception as e:
            logger.error(f"Unexpected error updating message: {e}")
            return {"error": str(e)}
    
    async def delete_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a message."""
        try:
            service = self._get_service()
            message_name = args["message"]
            
            service.spaces().messages().delete(
                name=message_name
            ).execute()
            
            logger.info(f"Deleted message {message_name}")
            return {
                "success": True,
                "message": f"Message {message_name} deleted successfully"
            }
            
        except HttpError as e:
            return self._handle_api_error(e, "delete_message")
        except Exception as e:
            logger.error(f"Unexpected error deleting message: {e}")
            return {"error": str(e)}

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Strip path separators / dodgy chars so an attachment name can't escape the dir."""
        name = os.path.basename(name or "")
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip()
        return name or "attachment"

    async def download_attachment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Download an uploaded-content attachment to disk and return its path."""
        try:
            service = self._get_service()

            resource_name = args.get("resource_name")
            content_name = args.get("filename")
            content_type = None

            # Resolve resource_name from the message when not given directly.
            if not resource_name:
                message_name = args.get("message")
                if not message_name:
                    return {"error": "Provide either 'message' or 'resource_name'."}

                message = service.spaces().messages().get(name=message_name).execute()
                attachments = message.get("attachment") or message.get("attachments") or []
                if not attachments:
                    return {"error": f"Message {message_name} has no attachments."}

                index = args.get("attachment_index", 0)
                if index < 0 or index >= len(attachments):
                    return {
                        "error": f"attachment_index {index} out of range "
                                 f"({len(attachments)} attachment(s) on this message)."
                    }

                attachment = attachments[index]
                content_name = content_name or attachment.get("contentName")
                content_type = attachment.get("contentType")

                data_ref = attachment.get("attachmentDataRef") or {}
                resource_name = data_ref.get("resourceName")
                if not resource_name:
                    if attachment.get("driveDataRef"):
                        return {
                            "error": "This attachment is a Google Drive file, not uploaded "
                                     "content. Downloading it needs the Drive API and a "
                                     "'drive.readonly' scope this server doesn't have.",
                            "drive_data_ref": attachment.get("driveDataRef"),
                        }
                    return {"error": "Attachment has no downloadable attachmentDataRef."}

            # Fetch the raw bytes via the Chat media download endpoint.
            request = service.media().download_media(resourceName=resource_name)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()

            data = buffer.getvalue()
            filename = self._safe_filename(content_name or resource_name)
            mime_type = content_type or "application/octet-stream"

            logger.info(f"Downloaded attachment {resource_name} ({filename}, {len(data)} bytes)")
            return {
                "success": True,
                "filename": filename,
                "content_type": mime_type,
                "size_bytes": len(data),
                "resource_name": resource_name,
                # Consumed by the server's call_tool handler to emit an inline
                # image / embedded-resource block instead of plain text.
                "_media": {
                    "data_b64": base64.b64encode(data).decode("ascii"),
                    "mime_type": mime_type,
                    "filename": filename,
                },
            }

        except HttpError as e:
            return self._handle_api_error(e, "download_attachment")
        except Exception as e:
            logger.error(f"Unexpected error downloading attachment: {e}")
            return {"error": str(e)}

    async def send_image_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Upload a file/image and post it as a message attachment."""
        try:
            service = self._get_service()
            space = self._validate_space(args.get("space"))
            text = args.get("text")
            filename = args.get("filename")
            content_type = args.get("content_type")

            # Resolve the file bytes from exactly one source.
            file_b64 = args.get("file_base64")
            file_url = args.get("file_url")
            if bool(file_b64) == bool(file_url):
                return {"error": "Provide exactly one of 'file_base64' or 'file_url'."}

            if file_b64:
                try:
                    data = base64.b64decode(file_b64, validate=True)
                except (binascii.Error, ValueError) as e:
                    return {"error": f"file_base64 is not valid base64: {e}"}
            else:
                if not (file_url.startswith("http://") or file_url.startswith("https://")):
                    return {"error": "file_url must be an http(s) URL."}
                with urllib.request.urlopen(file_url, timeout=30) as resp:  # noqa: S310 (scheme checked)
                    data = resp.read()
                    content_type = content_type or resp.headers.get("Content-Type")
                    if not filename:
                        filename = os.path.basename(urllib.parse.urlparse(file_url).path) or None

            if not data:
                return {"error": "Resolved file is empty."}

            filename = self._safe_filename(filename or "upload")
            if not content_type or content_type == "application/octet-stream":
                guessed, _ = mimetypes.guess_type(filename)
                content_type = guessed or content_type or "application/octet-stream"
            # Strip any charset suffix from a fetched Content-Type header.
            content_type = content_type.split(";")[0].strip()

            # Stage the upload; returns an attachmentUploadToken.
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type, resumable=False)
            upload = service.media().upload(
                parent=space,
                body={"filename": filename},
                media_body=media,
            ).execute()
            data_ref = upload.get("attachmentDataRef")
            if not data_ref:
                return {"error": "Upload did not return an attachmentDataRef.", "response": upload}

            # Post the message referencing the staged attachment.
            body: Dict[str, Any] = {"attachment": [{"attachmentDataRef": data_ref}]}
            if text:
                body["text"] = text

            create_kwargs = {"parent": space, "body": body}
            if args.get("thread"):
                body["thread"] = {"threadKey": args["thread"]}
                create_kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

            message = service.spaces().messages().create(**create_kwargs).execute()
            logger.info(f"Posted image message to {space} ({filename}, {len(data)} bytes)")
            return {
                "success": True,
                "space": space,
                "message": message.get("name"),
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(data),
            }

        except HttpError as e:
            return self._handle_api_error(e, "send_image_message")
        except Exception as e:
            logger.error(f"Unexpected error sending image message: {e}")
            return {"error": str(e)}