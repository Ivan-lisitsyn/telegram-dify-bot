# -*- coding: utf-8 -*-
"""
@Time    : 2025/8/14 22:16
@Author  : QIN2DIM
@GitHub  : https://github.com/QIN2DIM
@Desc    :
"""

from pathlib import Path
from typing import Dict, Any, Optional, List

import httpx
from loguru import logger
from telegram import InputMediaPhoto, InputMediaDocument, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from settings import DATA_DIR


async def _handle_answer_parts_image_generation(
    context: ContextTypes.DEFAULT_TYPE,
    chat: Any,
    trigger_message: Message,
    initial_message: Message,
    final_answer: str,
    extras: Dict[str, Any],
):
    # Send the generated images with caption, using the initial message for visual streaming effect
    await _send_imagine_result(
        context=context,
        chat_id=chat.id,
        image_urls=extras.get("all_image_urls", []),
        params=extras.get("params", {}),
        reply_to_message_id=trigger_message.message_id,
        initial_message=initial_message,
        final_answer=final_answer,
        trigger_message=trigger_message,
    )


async def _download_image_from_url(url: str) -> Optional[Path]:
    """Download image from URL and save to temporary directory"""
    try:
        # Create temp directory for generated images
        temp_dir = DATA_DIR / "generated_images"
        temp_dir.mkdir(exist_ok=True)

        # Extract filename from URL or generate a unique one
        import uuid
        from urllib.parse import urlparse

        parsed_url = urlparse(url)
        filename = Path(parsed_url.path).name
        if not filename or not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            filename = f"{uuid.uuid4().hex}.jpeg"

        # Download the image
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Save to file
            file_path = temp_dir / filename
            file_path.write_bytes(response.content)
            logger.info(f"Downloaded image from {url} to {file_path}")
            return file_path

    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None


async def _send_single_photo_with_caption(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    caption: str,
    reply_to_message_id: int,
    parse_mode: str,
    delete_message_id: int,
    photo: bytes,
) -> Optional[Message]:
    """Send single photo with caption and return the sent message"""
    try:
        sent_message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            parse_mode=parse_mode,
        )
        await context.bot.delete_message(chat_id=chat_id, message_id=delete_message_id)
        return sent_message
    except Exception as e:
        if "Message caption is too long" in str(e):
            logger.warning(f"Caption too long, sending photo without caption: {e}")
            sent_message = await context.bot.send_photo(
                chat_id=chat_id, photo=photo, reply_to_message_id=reply_to_message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=delete_message_id)
            return sent_message
        else:
            raise


async def _send_photo_group_with_caption(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    caption: str,
    reply_to_message_id: int,
    parse_mode: str,
    delete_message_id: int,
    downloaded_files: list,
) -> Optional[List[Message]]:
    """Send photo group with caption and return the sent messages"""
    # Send as media group
    media_group = []
    for i, file_path in enumerate(downloaded_files):
        photo = Path(file_path).read_bytes()
        if i == 0:
            media_group.append(InputMediaPhoto(media=photo, caption=caption, parse_mode=parse_mode))
        else:
            media_group.append(InputMediaPhoto(media=photo))

    try:
        sent_messages = await context.bot.send_media_group(
            chat_id=chat_id, media=media_group, reply_to_message_id=reply_to_message_id
        )
        await context.bot.delete_message(chat_id=chat_id, message_id=delete_message_id)
        return sent_messages
    except Exception as e:
        if "Message caption is too long" in str(e):
            logger.warning(f"Caption too long, sending media group without caption: {e}")
            # Rebuild media group without caption
            media_group = []
            for file_path in downloaded_files:
                photo = Path(file_path).read_bytes()
                media_group.append(InputMediaPhoto(media=photo))
            sent_messages = await context.bot.send_media_group(
                chat_id=chat_id, media=media_group, reply_to_message_id=reply_to_message_id
            )
            await context.bot.delete_message(chat_id=chat_id, message_id=delete_message_id)
            return sent_messages
        else:
            raise


async def _send_original_files(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    downloaded_files: List[Path],
    preview_message_id: Optional[int] = None,
    trigger_message_id: Optional[int] = None,
) -> bool:
    """
    Send original image files without compression.

    Priority for reply_to:
    1. Preview message (the bot's preview image + prompt message)
    2. Trigger message (user's /imagine command message)

    Args:
        context: Bot context
        chat_id: Chat ID to send to
        downloaded_files: List of downloaded image file paths
        preview_message_id: Message ID of the preview image sent by bot
        trigger_message_id: Message ID of the user's trigger message

    Returns:
        True if successful, False otherwise
    """
    if not downloaded_files:
        return False

    # Determine reply target with priority
    reply_to_message_id = preview_message_id or trigger_message_id

    try:
        if len(downloaded_files) == 1:
            # Single file - send as document
            file_path = downloaded_files[0]
            await context.bot.send_document(
                chat_id=chat_id,
                document=file_path.read_bytes(),
                filename=file_path.name,
                caption="📎 Original (uncompressed)",
                reply_to_message_id=reply_to_message_id,
            )
        else:
            # Multiple files - send as document group
            media_group = []
            for i, file_path in enumerate(downloaded_files):
                doc_bytes = file_path.read_bytes()
                if i == 0:
                    media_group.append(
                        InputMediaDocument(
                            media=doc_bytes,
                            filename=file_path.name,
                            caption=f"📎 Original files ({len(downloaded_files)} images, uncompressed)",
                        )
                    )
                else:
                    media_group.append(
                        InputMediaDocument(media=doc_bytes, filename=file_path.name)
                    )

            await context.bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                reply_to_message_id=reply_to_message_id,
            )

        logger.info(
            f"Sent {len(downloaded_files)} original files (reply_to={reply_to_message_id})"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send original files: {e}")

        # Fallback: try with trigger message if preview failed
        if preview_message_id and trigger_message_id and preview_message_id != trigger_message_id:
            logger.info("Retrying with trigger message as reply target...")
            return await _send_original_files(
                context=context,
                chat_id=chat_id,
                downloaded_files=downloaded_files,
                preview_message_id=None,  # Skip preview this time
                trigger_message_id=trigger_message_id,
            )

        return False


async def _send_imagine_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    image_urls: list[str],
    params: Dict[str, Any],
    reply_to_message_id: Optional[int] = None,
    initial_message: Optional[Message] = None,
    final_answer: Optional[str] = None,
    trigger_message: Optional[Message] = None,
):
    """
    Send generated image with parameters as caption, followed by original files.

    Flow:
    1. Send preview images with caption (compressed by Telegram)
    2. Send original files as documents (uncompressed) replying to the preview
    """
    if not image_urls:
        return False

    # Download images
    downloaded_files: List[Path] = []

    # Limit to telegram's max (10 for media group)
    for url in image_urls[:10]:
        file_path = await _download_image_from_url(url)
        if file_path:
            downloaded_files.append(file_path)

    if not downloaded_files:
        logger.error("Failed to download any images")
        return False

    # Use final_answer as caption if provided, otherwise use params
    if final_answer:
        caption_markdown = final_answer
        caption_html = final_answer
    else:
        caption_markdown = params.get("caption_markdown", "")
        caption_html = params.get("caption_html", caption_markdown)

    # Try to send with HTML first (since final_answer is usually HTML formatted)
    parse_modes = [ParseMode.HTML, ParseMode.MARKDOWN_V2, None]

    # Track the preview message for reply reference
    preview_message_id: Optional[int] = None

    for parse_mode in parse_modes:
        caption = caption_html if parse_mode == ParseMode.HTML else caption_markdown
        try:
            # Send single photo with caption
            if len(downloaded_files) == 1:
                photo = Path(downloaded_files[0]).read_bytes()
                sent_message = await _send_single_photo_with_caption(
                    context=context,
                    chat_id=chat_id,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode=str(parse_mode),
                    delete_message_id=initial_message.message_id,
                    photo=photo,
                )
                if sent_message:
                    preview_message_id = sent_message.message_id
            else:
                sent_messages = await _send_photo_group_with_caption(
                    context=context,
                    chat_id=chat_id,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                    parse_mode=str(parse_mode),
                    delete_message_id=initial_message.message_id,
                    downloaded_files=downloaded_files,
                )
                # Use the first message in the group for reply reference
                if sent_messages and len(sent_messages) > 0:
                    preview_message_id = sent_messages[0].message_id

            logger.info(f"Successfully sent {len(downloaded_files)} generated preview images")

            # Send original files (uncompressed) after preview
            trigger_message_id = trigger_message.message_id if trigger_message else None
            await _send_original_files(
                context=context,
                chat_id=chat_id,
                downloaded_files=downloaded_files,
                preview_message_id=preview_message_id,
                trigger_message_id=trigger_message_id,
            )

            return True

        except Exception as e:
            if "Message caption is too long" not in str(e):
                logger.exception(f"Failed to send with parse_mode={parse_mode}: {e}")
                continue
            else:
                # For caption too long error, it's already handled in the sub-functions
                # Still try to send original files
                logger.info(
                    f"Successfully sent {len(downloaded_files)} generated images (without caption due to length)"
                )

                # Send original files even if caption was too long
                trigger_message_id = trigger_message.message_id if trigger_message else None
                await _send_original_files(
                    context=context,
                    chat_id=chat_id,
                    downloaded_files=downloaded_files,
                    preview_message_id=preview_message_id,
                    trigger_message_id=trigger_message_id,
                )

                return True

    return False
