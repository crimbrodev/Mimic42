from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool
from telethon import functions, types
from telethon.extensions import markdown


class TelethonRequestClient(Protocol):
    async def __call__(self, request: object) -> object: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def is_user_authorized(self) -> bool: ...
    async def send_message(self, entity: Any, message: str, **kwargs: Any) -> Any: ...
    async def send_file(self, entity: Any, file: Any, **kwargs: Any) -> Any: ...
    async def edit_message(self, entity: Any, message: Any, text: str, **kwargs: Any) -> Any: ...
    async def delete_messages(self, entity: Any, message_ids: list[int], **kwargs: Any) -> Any: ...
    async def forward_messages(
        self, entity: Any, messages: list[int], from_peer: Any, **kwargs: Any
    ) -> Any: ...
    async def pin_message(self, entity: Any, message: Any, **kwargs: Any) -> Any: ...
    async def unpin_message(self, entity: Any, message: Any, **kwargs: Any) -> Any: ...
    async def get_entity(self, entity: Any) -> Any: ...
    async def get_input_entity(self, entity: Any) -> Any: ...
    async def get_messages(self, entity: Any, **kwargs: Any) -> Any: ...
    async def get_dialogs(self, **kwargs: Any) -> Any: ...
    async def get_permissions(self, entity: Any, user: Any) -> Any: ...
    async def edit_permissions(self, entity: Any, user: Any, **kwargs: Any) -> Any: ...
    async def edit_admin(self, entity: Any, user: Any, **kwargs: Any) -> Any: ...
    async def kick_participant(self, entity: Any, user: Any) -> Any: ...
    async def upload_file(self, file: Any, **kwargs: Any) -> Any: ...
    async def download_media(self, message: Any, file: Any = None, **kwargs: Any) -> Any: ...
    def iter_messages(self, entity: Any, **kwargs: Any) -> Any: ...
    def iter_participants(self, entity: Any, **kwargs: Any) -> Any: ...
    def iter_admin_log(self, entity: Any, **kwargs: Any) -> Any: ...


class CustomMarkdown:
    """Telethon parse mode to format premium custom emoji and markdown formatting."""

    @staticmethod
    def parse(text: str) -> tuple[str, list[types.TypeMessageEntity]]:
        if not text:
            return "", []
        parsed_text, entities = markdown.parse(text)
        new_entities = []
        for entity in entities:
            if isinstance(entity, types.MessageEntityTextUrl) and entity.url.startswith("emoji/"):
                try:
                    doc_id = int(entity.url.split("/")[1])
                    new_entities.append(
                        types.MessageEntityCustomEmoji(
                            offset=entity.offset,
                            length=entity.length,
                            document_id=doc_id,
                        )
                    )
                except (ValueError, IndexError):
                    new_entities.append(entity)
            else:
                new_entities.append(entity)
        return parsed_text, new_entities

    @staticmethod
    def unparse(text: str, entities: list[types.TypeMessageEntity]) -> str:
        if not text:
            return ""
        if not entities:
            return markdown.unparse(text, [])

        temp_entities = []
        for entity in entities:
            if isinstance(entity, types.MessageEntityCustomEmoji):
                temp_entities.append(
                    types.MessageEntityTextUrl(
                        offset=entity.offset,
                        length=entity.length,
                        url=f"emoji/{entity.document_id}",
                    )
                )
            else:
                temp_entities.append(entity)
        return markdown.unparse(text, temp_entities)


def parse_media_id(media_id: str) -> tuple[str, int, int, bytes, int]:
    """Parse media ID in format type:id:access_hash:file_reference_hex:dc_id."""
    parts = media_id.split(":")
    if len(parts) < 5:
        raise ValueError(f"Invalid media ID format: {media_id}")
    media_type = parts[0]
    obj_id = int(parts[1])
    access_hash = int(parts[2])
    file_reference = bytes.fromhex(parts[3])
    dc_id = int(parts[4])
    return media_type, obj_id, access_hash, file_reference, dc_id


def format_media_object(msg: Any) -> str | None:
    """Format message media to serialized media ID string."""
    if not msg or not getattr(msg, "media", None):
        return None
    media = msg.media

    if isinstance(media, types.MessageMediaPhoto) and media.photo:
        photo = media.photo
        if isinstance(photo, types.Photo):
            ref_hex = photo.file_reference.hex() if photo.file_reference else ""
            return f"photo:{photo.id}:{photo.access_hash}:{ref_hex}:{photo.dc_id}"

    elif isinstance(media, types.MessageMediaDocument) and media.document:
        doc = media.document
        if isinstance(doc, types.Document):
            ref_hex = doc.file_reference.hex() if doc.file_reference else ""

            # Check for sticker attribute
            sticker_attr = next(
                (
                    attr
                    for attr in doc.attributes
                    if isinstance(attr, types.DocumentAttributeSticker)
                ),
                None,
            )
            if sticker_attr:
                emoji = sticker_attr.alt or ""
                pack_name = ""
                if isinstance(sticker_attr.stickerset, types.InputStickerSetShortName):
                    pack_name = sticker_attr.stickerset.short_name
                elif isinstance(sticker_attr.stickerset, types.InputStickerSetID):
                    pack_name = str(sticker_attr.stickerset.id)
                return (
                    f"sticker:{doc.id}:{doc.access_hash}:{ref_hex}:{doc.dc_id}:"
                    f"{emoji}:{pack_name}"
                )

            # Check for voice note
            audio_attr = next(
                (
                    attr
                    for attr in doc.attributes
                    if isinstance(attr, types.DocumentAttributeAudio)
                ),
                None,
            )
            if audio_attr and audio_attr.voice:
                return f"voice:{doc.id}:{doc.access_hash}:{ref_hex}:{doc.dc_id}"

            # Check for round video note
            video_attr = next(
                (
                    attr
                    for attr in doc.attributes
                    if isinstance(attr, types.DocumentAttributeVideo)
                ),
                None,
            )
            if video_attr and video_attr.round_message:
                return f"round:{doc.id}:{doc.access_hash}:{ref_hex}:{doc.dc_id}"

            # General file
            filename_attr = next(
                (
                    attr
                    for attr in doc.attributes
                    if isinstance(attr, types.DocumentAttributeFilename)
                ),
                None,
            )
            filename = filename_attr.file_name if filename_attr else "file"
            return f"doc:{doc.id}:{doc.access_hash}:{ref_hex}:{doc.dc_id}:{filename}"

    return None


class TelegramToolbox:
    """High-level business-friendly Telegram tools for the agent."""

    def __init__(self, client: Any) -> None:
        self._client = client

    # Category 1: Messages and Basic Communication (1-12)

    async def send_text_message(
        self, peer: str, message: str, reply_to_msg_id: int | None = None
    ) -> dict[str, Any]:
        """Send a text message (markdown supported)."""
        try:
            entity = await self._client.get_input_entity(peer)
            msg = await self._client.send_message(
                entity, message, reply_to=reply_to_msg_id, parse_mode=CustomMarkdown()
            )
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def edit_text_message(
        self, peer: str, message_id: int, new_message: str
    ) -> dict[str, Any]:
        """Edit a message previously sent by the bot."""
        try:
            entity = await self._client.get_input_entity(peer)
            msg = await self._client.edit_message(
                entity, message_id, new_message, parse_mode=CustomMarkdown()
            )
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_messages(
        self, peer: str, message_ids: list[int], revoke: bool = True
    ) -> dict[str, Any]:
        """Delete messages by ID."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client.delete_messages(entity, message_ids, revoke=revoke)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def forward_messages(
        self, from_peer: str, to_peer: str, message_ids: list[int]
    ) -> dict[str, Any]:
        """Forward messages from one chat to another."""
        try:
            from_entity = await self._client.get_input_entity(from_peer)
            to_entity = await self._client.get_input_entity(to_peer)
            await self._client.forward_messages(to_entity, message_ids, from_peer=from_entity)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def pin_message(self, peer: str, message_id: int, silent: bool = False) -> dict[str, Any]:
        """Pin a message in a chat."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client.pin_message(entity, message_id, silent=silent)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unpin_message(self, peer: str, message_id: int | None = None) -> dict[str, Any]:
        """Unpin a message in a chat."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client.unpin_message(entity, message_id)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unpin_all_messages(self, peer: str) -> dict[str, Any]:
        """Unpin all pinned messages in a chat."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client(functions.messages.UnpinAllMessagesRequest(peer=entity))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_chat_action(self, peer: str, action: str) -> dict[str, Any]:
        """Send a chat action indicator (typing, record_audio, etc.)."""
        try:
            entity = await self._client.get_input_entity(peer)
            # Map simple strings to Telethon actions
            action_obj: Any = types.SendMessageTypingAction()
            if action == "record_audio":
                action_obj = types.SendMessageRecordAudioAction()
            elif action == "upload_document":
                action_obj = types.SendMessageUploadDocumentAction()
            elif action == "record_video":
                action_obj = types.SendMessageRecordVideoAction()

            async with self._client.action(entity, action_obj):
                pass
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_reaction(self, peer: str, message_id: int, emoji: str) -> dict[str, Any]:
        """Set a reaction on a message."""
        try:
            entity = await self._client.get_input_entity(peer)
            reaction_list = [types.ReactionEmoji(emoticon=emoji)] if emoji else []
            await self._client(
                functions.messages.SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=reaction_list,
                )
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_message_reactions(self, peer: str, message_id: int) -> dict[str, Any]:
        """Get the reactions of a message."""
        try:
            entity = await self._client.get_input_entity(peer)
            result = await self._client(
                functions.messages.GetMessageReactionsListRequest(
                    peer=entity,
                    id=message_id,
                    limit=100,
                )
            )
            reactions = []
            for r in result.reactions:
                reactions.append(
                    {
                        "peer_id": str(r.peer_id),
                        "emoji": r.reaction.emoticon
                        if isinstance(r.reaction, types.ReactionEmoji)
                        else "",
                    }
                )
            return {"reactions": reactions}
        except Exception as e:
            return {"error": str(e)}

    async def mark_chat_as_read(self, peer: str, max_id: int | None = None) -> dict[str, Any]:
        """Mark messages in a chat as read."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client(
                functions.messages.ReadHistoryRequest(peer=entity, max_id=max_id or 0)
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_messages(
        self, peer: str, limit: int = 20, offset_id: int = 0
    ) -> list[dict[str, Any]]:
        """Get message history (annotated with Media IDs)."""
        try:
            entity = await self._client.get_entity(peer)
            messages = []
            async for msg in self._client.iter_messages(entity, limit=limit, offset_id=offset_id):
                text = msg.text or ""
                media_id = format_media_object(msg)
                if media_id:
                    if media_id.startswith("photo:"):
                        text = f"[Фото id={media_id}]" + (f" {text}" if text else "")
                    elif media_id.startswith("sticker:"):
                        emoji = media_id.split(":")[-1]
                        text = f"[Стикер {emoji} id={media_id}]" + (f" {text}" if text else "")
                    elif media_id.startswith("doc:"):
                        text = f"[Файл id={media_id}]" + (f" {text}" if text else "")

                messages.append(
                    {
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "text": text,
                    }
                )
            return messages
        except Exception as e:
            return [{"error": str(e)}]

    # Category 2: Navigation and Dialogs (13-18)

    async def get_dialogs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent dialogs."""
        try:
            dialogs_list = await self._client.get_dialogs(limit=limit)
            result = []
            for d in dialogs_list:
                result.append(
                    {
                        "id": d.id,
                        "title": d.title,
                        "username": getattr(d.entity, "username", None),
                        "unread_count": d.unread_count,
                    }
                )
            return result
        except Exception as e:
            return [{"error": str(e)}]

    async def search_messages(self, peer: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search messages in a chat."""
        try:
            entity = await self._client.get_entity(peer)
            messages = []
            async for msg in self._client.iter_messages(entity, search=query, limit=limit):
                messages.append(
                    {
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "text": msg.text or "",
                    }
                )
            return messages
        except Exception as e:
            return [{"error": str(e)}]

    async def delete_dialog(self, peer: str, revoke: bool = True) -> dict[str, Any]:
        """Delete a dialog or leave a group/channel."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client.delete_dialog(entity, revoke=revoke)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def archive_dialogs(self, peers: list[str]) -> dict[str, Any]:
        """Archive dialogs."""
        try:
            for p in peers:
                entity = await self._client.get_input_entity(p)
                await self._client(
                    functions.folders.EditPeerFoldersRequest(
                        folder_peers=[types.InputFolderPeer(peer=entity, folder_id=1)]
                    )
                )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def unarchive_dialogs(self, peers: list[str]) -> dict[str, Any]:
        """Unarchive dialogs."""
        try:
            for p in peers:
                entity = await self._client.get_input_entity(p)
                await self._client(
                    functions.folders.EditPeerFoldersRequest(
                        folder_peers=[types.InputFolderPeer(peer=entity, folder_id=0)]
                    )
                )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_common_chats(self, peer: str) -> list[dict[str, Any]]:
        """Get common groups/channels with a user."""
        try:
            entity = await self._client.get_input_entity(peer)
            res = await self._client(
                functions.messages.GetCommonChatsRequest(user_id=entity, max_id=0, limit=100)
            )
            chats = []
            for chat in res.chats:
                chats.append(
                    {
                        "id": chat.id,
                        "title": getattr(chat, "title", ""),
                        "username": getattr(chat, "username", None),
                    }
                )
            return chats
        except Exception as e:
            return [{"error": str(e)}]

    # Category 3: Memory-based Media Handling (19-23)

    async def send_file(
        self,
        peer: str,
        file_source: str,
        caption: str | None = None,
        reply_to_msg_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a file by URL or Media ID."""
        try:
            entity = await self._client.get_input_entity(peer)
            if file_source.startswith("http://") or file_source.startswith("https://"):
                msg = await self._client.send_file(
                    entity, file_source, caption=caption, reply_to=reply_to_msg_id
                )
                return {"success": True, "message_id": msg.id}

            media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(file_source)
            if media_type == "photo":
                file_input = types.InputPhoto(
                    id=obj_id,
                    access_hash=access_hash,
                    file_reference=file_reference,
                )
            elif media_type in ("sticker", "doc", "voice", "round"):
                file_input = types.InputDocument(
                    id=obj_id,
                    access_hash=access_hash,
                    file_reference=file_reference,
                )
            else:
                return {"success": False, "error": f"Invalid media type: {media_type}"}

            msg = await self._client.send_file(
                entity, file_input, caption=caption, reply_to=reply_to_msg_id
            )
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def view_image(self, media_id: str) -> list[dict[str, Any]]:
        """View image/sticker and return Base64 image payload."""
        try:
            media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(media_id)
            if media_type == "photo":
                media_obj = types.Photo(
                    id=obj_id,
                    access_hash=access_hash,
                    file_reference=file_reference,
                    date=datetime.now(),
                    sizes=[types.PhotoSize(type="x", w=0, h=0, size=0)],
                    dc_id=dc_id,
                )
                mime_type = "image/jpeg"
            elif media_type == "sticker":
                media_obj = types.Document(
                    id=obj_id,
                    access_hash=access_hash,
                    file_reference=file_reference,
                    date=datetime.now(),
                    mime_type="image/webp",
                    size=0,
                    dc_id=dc_id,
                    attributes=[
                        types.DocumentAttributeSticker(
                            alt="", stickerset=types.InputStickerSetEmpty()
                        )
                    ],
                )
                mime_type = "image/webp"
            elif media_type == "doc":
                media_obj = types.Document(
                    id=obj_id,
                    access_hash=access_hash,
                    file_reference=file_reference,
                    date=datetime.now(),
                    mime_type="image/png",
                    size=0,
                    dc_id=dc_id,
                    attributes=[],
                )
                mime_type = "image/png"
            else:
                return [{"type": "text", "text": f"Unsupported media type: {media_type}"}]

            data = await self._client.download_media(media_obj, file=bytes)
            if not data:
                return [{"type": "text", "text": "Failed to download media."}]

            base64_str = base64.b64encode(data).decode("utf-8")
            return [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_str}"},
                }
            ]
        except Exception as e:
            return [{"type": "text", "text": f"Error loading image: {str(e)}"}]

    async def set_profile_photo(self, media_id: str) -> dict[str, Any]:
        """Set profile photo by URL or Media ID in memory."""
        try:
            if media_id.startswith("http://") or media_id.startswith("https://"):
                import httpx

                async with httpx.AsyncClient() as http_client:
                    r = await http_client.get(media_id)
                    if r.status_code != 200:
                        return {"success": False, "error": f"URL fetch status: {r.status_code}"}
                    photo_bytes = r.content
            else:
                media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(media_id)
                if media_type == "photo":
                    media_obj = types.Photo(
                        id=obj_id,
                        access_hash=access_hash,
                        file_reference=file_reference,
                        date=datetime.now(),
                        sizes=[types.PhotoSize(type="x", w=0, h=0, size=0)],
                        dc_id=dc_id,
                    )
                elif media_type in ("sticker", "doc", "voice", "round"):
                    media_obj = types.Document(
                        id=obj_id,
                        access_hash=access_hash,
                        file_reference=file_reference,
                        date=datetime.now(),
                        mime_type="image/png",
                        size=0,
                        dc_id=dc_id,
                        attributes=[],
                    )
                else:
                    return {"success": False, "error": f"Invalid media type: {media_type}"}

                photo_bytes = await self._client.download_media(media_obj, file=bytes)
                if not photo_bytes:
                    return {"success": False, "error": "Failed to download media."}

            uploaded_file = await self._client.upload_file(photo_bytes)
            await self._client(functions.photos.UploadProfilePhotoRequest(file=uploaded_file))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_voice_note(
        self,
        peer: str,
        file_source: str,
        duration: int | None = None,
        reply_to_msg_id: int | None = None,
    ) -> dict[str, Any]:
        """Send voice note by URL or Media ID."""
        try:
            entity = await self._client.get_input_entity(peer)
            if file_source.startswith("http://") or file_source.startswith("https://"):
                msg = await self._client.send_file(
                    entity, file_source, voice_note=True, reply_to=reply_to_msg_id
                )
                return {"success": True, "message_id": msg.id}

            media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(file_source)
            file_input = types.InputDocument(
                id=obj_id,
                access_hash=access_hash,
                file_reference=file_reference,
            )
            msg = await self._client.send_file(
                entity, file_input, voice_note=True, reply_to=reply_to_msg_id
            )
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_video_note(
        self,
        peer: str,
        file_source: str,
        duration: int | None = None,
        reply_to_msg_id: int | None = None,
    ) -> dict[str, Any]:
        """Send video note (round video) by URL or Media ID."""
        try:
            entity = await self._client.get_input_entity(peer)
            if file_source.startswith("http://") or file_source.startswith("https://"):
                msg = await self._client.send_file(
                    entity, file_source, video_note=True, reply_to=reply_to_msg_id
                )
                return {"success": True, "message_id": msg.id}

            media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(file_source)
            file_input = types.InputDocument(
                id=obj_id,
                access_hash=access_hash,
                file_reference=file_reference,
            )
            msg = await self._client.send_file(
                entity, file_input, video_note=True, reply_to=reply_to_msg_id
            )
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Category 4: Sticker Management (24-29)

    async def get_sticker_sets(self) -> list[dict[str, Any]]:
        """Get user's installed sticker sets."""
        try:
            res = await self._client(functions.messages.GetAllStickersRequest(hash=0))
            sets = []
            for s in res.sets:
                sets.append(
                    {
                        "id": s.id,
                        "title": s.title,
                        "short_name": s.short_name,
                        "count": s.count,
                    }
                )
            return sets
        except Exception as e:
            return [{"error": str(e)}]

    async def get_stickers_in_set(self, set_short_name: str) -> list[dict[str, Any]]:
        """Get list of stickers inside a specific set."""
        try:
            res = await self._client(
                functions.messages.GetStickerSetRequest(
                    stickerset=types.InputStickerSetShortName(short_name=set_short_name),
                    hash=0,
                )
            )
            stickers = []
            for doc in res.documents:
                ref_hex = doc.file_reference.hex() if doc.file_reference else ""
                emoji = ""
                sticker_attr = next(
                    (
                        attr
                        for attr in doc.attributes
                        if isinstance(attr, types.DocumentAttributeSticker)
                    ),
                    None,
                )
                if sticker_attr:
                    emoji = sticker_attr.alt or ""

                media_id = f"sticker:{doc.id}:{doc.access_hash}:{ref_hex}:{doc.dc_id}:{emoji}"
                stickers.append(
                    {
                        "media_id": media_id,
                        "emoji": emoji,
                    }
                )
            return stickers
        except Exception as e:
            return [{"error": str(e)}]

    async def search_sticker_sets(self, query: str) -> list[dict[str, Any]]:
        """Search sticker sets globally by name."""
        try:
            res = await self._client(functions.messages.SearchStickerSetsRequest(q=query, hash=0))
            sets = []
            for s in res.sets:
                if isinstance(s, types.StickerSet):
                    sets.append(
                        {
                            "id": s.id,
                            "title": s.title,
                            "short_name": s.short_name,
                            "count": s.count,
                        }
                    )
            return sets
        except Exception as e:
            return [{"error": str(e)}]

    async def install_sticker_set(self, set_short_name: str) -> dict[str, Any]:
        """Add a sticker set to user's list."""
        try:
            await self._client(
                functions.messages.InstallStickerSetRequest(
                    stickerset=types.InputStickerSetShortName(short_name=set_short_name),
                    archived=False,
                )
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def uninstall_sticker_set(self, set_short_name: str) -> dict[str, Any]:
        """Remove a sticker set from user's list."""
        try:
            await self._client(
                functions.messages.UninstallStickerSetRequest(
                    stickerset=types.InputStickerSetShortName(short_name=set_short_name)
                )
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_sticker(
        self, peer: str, media_id: str, reply_to_msg_id: int | None = None
    ) -> dict[str, Any]:
        """Send a sticker by its Media ID."""
        try:
            entity = await self._client.get_input_entity(peer)
            media_type, obj_id, access_hash, file_reference, dc_id = parse_media_id(media_id)
            if media_type != "sticker":
                return {"success": False, "error": "media_id is not a sticker"}

            sticker_input = types.InputDocument(
                id=obj_id,
                access_hash=access_hash,
                file_reference=file_reference,
            )
            msg = await self._client.send_file(entity, sticker_input, reply_to=reply_to_msg_id)
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Category 5: Business Profile and Contacts (30-35)

    async def get_profile(self, peer: str) -> dict[str, Any]:
        """Get high-level user profile details (bio/about, common chats)."""
        try:
            entity = await self._client.get_entity(peer)
            if isinstance(entity, types.User):
                full_info = await self._client(functions.users.GetFullUserRequest(id=entity))
                full_user = full_info.full_user

                status_str = "offline"
                if entity.status:
                    if isinstance(entity.status, types.UserStatusOnline):
                        status_str = "online"
                    elif isinstance(entity.status, types.UserStatusRecently):
                        status_str = "recently"

                return {
                    "id": entity.id,
                    "first_name": entity.first_name,
                    "last_name": entity.last_name,
                    "username": entity.username,
                    "phone": entity.phone,
                    "is_bot": bool(entity.bot),
                    "bio": full_user.about or "",
                    "common_chats_count": full_user.common_chats_count,
                    "status": status_str,
                }
            else:
                return {
                    "id": entity.id,
                    "title": getattr(entity, "title", ""),
                    "username": getattr(entity, "username", None),
                    "type": "chat" if isinstance(entity, types.Chat) else "channel",
                }
        except Exception as e:
            return {"error": str(e)}

    async def update_profile_info(
        self, first_name: str | None = None, last_name: str | None = None, bio: str | None = None
    ) -> dict[str, Any]:
        """Update bot's name and bio."""
        try:
            if first_name is not None or last_name is not None:
                await self._client(
                    functions.account.UpdateProfileRequest(
                        first_name=first_name,
                        last_name=last_name or "",
                    )
                )
            if bio is not None:
                await self._client(functions.account.UpdateProfileRequest(about=bio))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_username(self, username: str) -> dict[str, Any]:
        """Update bot's public @username."""
        try:
            await self._client(functions.account.UpdateUsernameRequest(username=username))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def add_contact(self, phone: str, first_name: str, last_name: str = "") -> dict[str, Any]:
        """Add contact by phone."""
        try:
            await self._client(
                functions.contacts.ImportContactsRequest(
                    contacts=[
                        types.InputPhoneContact(
                            client_id=0,
                            phone=phone,
                            first_name=first_name,
                            last_name=last_name,
                        )
                    ]
                )
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_contact(self, peer: str) -> dict[str, Any]:
        """Delete user from contact list."""
        try:
            entity = await self._client.get_input_entity(peer)
            await self._client(functions.contacts.DeleteContactsRequest(id=[entity]))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_contacts(self) -> list[dict[str, Any]]:
        """Get contacts list."""
        try:
            res = await self._client(functions.contacts.GetContactsRequest(hash=0))
            contacts = []
            for u in res.users:
                if isinstance(u, types.User):
                    contacts.append(
                        {
                            "id": u.id,
                            "first_name": u.first_name,
                            "last_name": u.last_name,
                            "username": u.username,
                            "phone": u.phone,
                        }
                    )
            return contacts
        except Exception as e:
            return [{"error": str(e)}]

    # Category 6: Groups, Channels and Permissions (36-48)

    async def get_chat_info(self, peer: str) -> dict[str, Any]:
        """Get high-level details of a group/channel (participants, about description)."""
        try:
            entity = await self._client.get_entity(peer)
            if isinstance(entity, types.User):
                return {"error": "Target entity is a user, not a chat/channel"}

            info = {
                "id": entity.id,
                "title": getattr(entity, "title", ""),
                "username": getattr(entity, "username", None),
                "is_channel": isinstance(entity, types.Channel) and not entity.megagroup,
                "is_group": isinstance(entity, types.Chat)
                or (isinstance(entity, types.Channel) and entity.megagroup),
            }

            if isinstance(entity, types.Channel):
                full_info = await self._client(
                    functions.channels.GetFullChannelRequest(channel=entity)
                )
                full_chat = full_info.full_chat
                info["about"] = full_chat.about or ""
                info["participants_count"] = full_chat.participants_count or 0
                info["admins_count"] = full_chat.admins_count or 0
            elif isinstance(entity, types.Chat):
                full_info = await self._client(
                    functions.messages.GetFullChatRequest(chat_id=entity.id)
                )
                full_chat = full_info.full_chat
                info["about"] = ""
                participants = full_chat.participants
                info["participants_count"] = (
                    len(participants.participants) if hasattr(participants, "participants") else 0
                )

            return info
        except Exception as e:
            return {"error": str(e)}

    async def check_admin_permissions(self, peer: str) -> dict[str, Any]:
        """Check administrative rights of the bot inside a chat/group."""
        try:
            entity = await self._client.get_entity(peer)
            if isinstance(entity, types.User):
                return {"is_admin": False, "reason": "Target is a user"}

            permissions = await self._client.get_permissions(entity, "me")
            return {
                "is_admin": permissions.is_admin,
                "is_creator": permissions.is_creator,
                "can_pin_messages": permissions.pin_messages,
                "can_delete_messages": permissions.delete_messages,
                "can_edit_messages": permissions.edit_messages,
                "can_invite_users": permissions.invite_users,
                "can_ban_users": permissions.ban_users,
                "can_change_info": permissions.change_info,
                "can_post_messages": permissions.post_messages,
                "can_add_admins": permissions.add_admins,
            }
        except Exception as e:
            return {"error": str(e)}

    async def create_group(self, title: str, users: list[str]) -> dict[str, Any]:
        """Create a simple group chat."""
        try:
            await self._client(functions.messages.CreateChatRequest(title=title, users=users))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_channel(
        self, title: str, about: str = "", megagroup: bool = False
    ) -> dict[str, Any]:
        """Create a channel or supergroup."""
        try:
            await self._client(
                functions.channels.CreateChannelRequest(
                    title=title, about=about, megagroup=megagroup
                )
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def invite_to_channel(self, channel: str, users: list[str]) -> dict[str, Any]:
        """Invite users to channel/supergroup."""
        try:
            ch_entity = await self._client.get_input_entity(channel)
            await self._client(
                functions.channels.InviteToChannelRequest(channel=ch_entity, users=users)
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def kick_chat_member(self, peer: str, user: str) -> dict[str, Any]:
        """Kick participant from chat."""
        try:
            await self._client.kick_participant(peer, user)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def ban_chat_member(
        self, peer: str, user: str, until_date: int | None = None
    ) -> dict[str, Any]:
        """Ban participant."""
        try:
            until = datetime.fromtimestamp(until_date) if until_date else None
            await self._client.edit_permissions(peer, user, view_messages=False, until_date=until)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def restrict_chat_member(
        self,
        peer: str,
        user: str,
        send_messages: bool = True,
        send_media: bool = True,
        send_stickers: bool = True,
        until_date: int | None = None,
    ) -> dict[str, Any]:
        """Restrict user permissions in chat."""
        try:
            until = datetime.fromtimestamp(until_date) if until_date else None
            await self._client.edit_permissions(
                peer,
                user,
                send_messages=send_messages,
                send_media=send_media,
                send_stickers=send_stickers,
                until_date=until,
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def promote_chat_member(
        self,
        peer: str,
        user: str,
        post_messages: bool = False,
        delete_messages: bool = False,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Promote user to admin with custom title."""
        try:
            await self._client.edit_admin(
                peer,
                user,
                post_messages=post_messages,
                delete_messages=delete_messages,
                title=title,
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_chat_members(
        self, peer: str, filter_type: str = "all", limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get members of a group/channel (with custom titles)."""
        try:
            entity = await self._client.get_entity(peer)
            filter_obj = types.ChannelParticipantsRecent()
            if filter_type == "admins":
                filter_obj = types.ChannelParticipantsAdmins()
            elif filter_type == "banned":
                filter_obj = types.ChannelParticipantsKicked()
            elif filter_type == "bots":
                filter_obj = types.ChannelParticipantsBots()

            participants = []
            async for u in self._client.iter_participants(entity, limit=limit, filter=filter_obj):
                title = None
                if hasattr(u, "participant") and u.participant:
                    title = getattr(u.participant, "title", None)

                participants.append(
                    {
                        "id": u.id,
                        "first_name": u.first_name,
                        "last_name": u.last_name,
                        "username": u.username,
                        "is_bot": bool(u.bot),
                        "title": title,
                    }
                )
            return participants
        except Exception as e:
            return [{"error": str(e)}]

    async def get_chat_admin_log(self, peer: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get administrative audit log."""
        try:
            entity = await self._client.get_entity(peer)
            log_entries = []
            async for event in self._client.iter_admin_log(entity, limit=limit):
                log_entries.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "user_id": event.user_id,
                        "action": event.action.stringify() if event.action else "unknown",
                    }
                )
            return log_entries
        except Exception as e:
            return [{"error": str(e)}]

    async def join_channel(self, channel: str) -> dict[str, Any]:
        """Join a public channel/group."""
        try:
            entity = await self._client.get_input_entity(channel)
            await self._client(functions.channels.JoinChannelRequest(channel=entity))
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_poll(
        self,
        peer: str,
        question: str,
        options: list[str],
        is_anonymous: bool = True,
        is_quiz: bool = False,
        correct_option_id: int | None = None,
    ) -> dict[str, Any]:
        """Send a poll or quiz."""
        try:
            entity = await self._client.get_input_entity(peer)
            poll = types.Poll(
                id=0,
                hash=0,
                question=question,
                answers=[
                    types.PollAnswer(text=opt, option=bytes([i])) for i, opt in enumerate(options)
                ],
                closed=False,
                public_voters=not is_anonymous,
                multiple_choice=False,
                quiz=is_quiz,
            )
            media = types.InputMediaPoll(
                poll=poll,
                correct_answers=[bytes([correct_option_id])]
                if correct_option_id is not None
                else None,
            )
            msg = await self._client.send_file(entity, media)
            return {"success": True, "message_id": msg.id}
        except Exception as e:
            return {"success": False, "error": str(e)}


def build_telegram_langchain_tools(client: TelethonRequestClient) -> list[BaseTool]:
    """Expose all 48 tools as LangChain StructuredTools."""
    toolbox = TelegramToolbox(client)

    return [
        StructuredTool.from_function(
            coroutine=toolbox.send_text_message,
            name="send_text_message",
            description="Send a text message (markdown supported).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.edit_text_message,
            name="edit_text_message",
            description="Edit a message previously sent by the bot.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.delete_messages,
            name="delete_messages",
            description="Delete messages in a chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.forward_messages,
            name="forward_messages",
            description="Forward messages from one chat to another.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.pin_message,
            name="pin_message",
            description="Pin a message in a chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.unpin_message,
            name="unpin_message",
            description="Unpin a message in a chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.unpin_all_messages,
            name="unpin_all_messages",
            description="Unpin all pinned messages in a chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_chat_action,
            name="send_chat_action",
            description=(
                "Send a chat action indicator (typing, record_audio, "
                "upload_document, record_video)."
            ),
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_reaction,
            name="send_reaction",
            description="Set or remove a reaction emoji on a message.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_message_reactions,
            name="get_message_reactions",
            description="Get the detailed reactions list of a message.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.mark_chat_as_read,
            name="mark_chat_as_read",
            description="Mark messages in a chat as read.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_messages,
            name="get_messages",
            description="Get message history (annotated with Media IDs: photo, sticker, doc).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_dialogs,
            name="get_dialogs",
            description="Get recent dialogs (chats, channels, users).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.search_messages,
            name="search_messages",
            description="Search messages inside a specific chat by keyword query.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.delete_dialog,
            name="delete_dialog",
            description="Delete a dialog (leaves a chat or channel).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.archive_dialogs,
            name="archive_dialogs",
            description="Archive dialogs.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.unarchive_dialogs,
            name="unarchive_dialogs",
            description="Unarchive dialogs.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_common_chats,
            name="get_common_chats",
            description="Get the list of common groups/channels with a user.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_file,
            name="send_file",
            description="Send a file or photo by URL or Media ID.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.view_image,
            name="view_image",
            description=(
                "View an image or sticker by its Media ID. Returns "
                "base64 image data in LangChain multimodal format."
            ),
        ),
        StructuredTool.from_function(
            coroutine=toolbox.set_profile_photo,
            name="set_profile_photo",
            description="Set the bot's profile photo by URL or Media ID in memory.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_voice_note,
            name="send_voice_note",
            description="Send a voice note audio file by URL or Media ID.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_video_note,
            name="send_video_note",
            description="Send a video note (round video message) by URL or Media ID.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_sticker_sets,
            name="get_sticker_sets",
            description="Get user's installed sticker sets.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_stickers_in_set,
            name="get_stickers_in_set",
            description="Get list of stickers inside a specific set by set short name.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.search_sticker_sets,
            name="search_sticker_sets",
            description="Search sticker sets globally by name query.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.install_sticker_set,
            name="install_sticker_set",
            description="Install/add a sticker set to user's list.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.uninstall_sticker_set,
            name="uninstall_sticker_set",
            description="Uninstall/remove a sticker set from user's list.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_sticker,
            name="send_sticker",
            description="Send a sticker by its Media ID.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_profile,
            name="get_profile",
            description=(
                "Get high-level details of a user: bio/about, name, "
                "online status, common chats count."
            ),
        ),
        StructuredTool.from_function(
            coroutine=toolbox.update_profile_info,
            name="update_profile_info",
            description="Update bot's name and bio (about).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.update_username,
            name="update_username",
            description="Update bot's public @username.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.add_contact,
            name="add_contact",
            description="Add a contact by phone number.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.delete_contact,
            name="delete_contact",
            description="Delete user from contact list.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_contacts,
            name="get_contacts",
            description="Get contacts list.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_chat_info,
            name="get_chat_info",
            description=(
                "Get high-level details of a group/channel "
                "(about, title, participants count)."
            ),
        ),
        StructuredTool.from_function(
            coroutine=toolbox.check_admin_permissions,
            name="check_admin_permissions",
            description="Check administrative rights of the bot itself in a group or channel.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.create_group,
            name="create_group",
            description="Create a simple group chat with list of user IDs/usernames.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.create_channel,
            name="create_channel",
            description="Create a channel or supergroup.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.invite_to_channel,
            name="invite_to_channel",
            description="Invite/add users to channel/supergroup.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.kick_chat_member,
            name="kick_chat_member",
            description="Kick/remove participant from chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.ban_chat_member,
            name="ban_chat_member",
            description="Ban participant in group/channel.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.restrict_chat_member,
            name="restrict_chat_member",
            description="Restrict permissions of participant in chat.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.promote_chat_member,
            name="promote_chat_member",
            description="Promote participant to administrator with custom title (member tag).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_chat_members,
            name="get_chat_members",
            description="Get members of a group/channel (with custom titles).",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.get_chat_admin_log,
            name="get_chat_admin_log",
            description="Get administrative audit log.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.join_channel,
            name="join_channel",
            description="Join a public channel/group.",
        ),
        StructuredTool.from_function(
            coroutine=toolbox.send_poll,
            name="send_poll",
            description="Send a poll or quiz.",
        ),
    ]
