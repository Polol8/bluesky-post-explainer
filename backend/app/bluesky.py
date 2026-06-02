import re
import httpx
from .models import BlueskyPost, BlueskyImage, BlueskyExternal, BlueskyReply

BSKY_API = "https://public.api.bsky.app/xrpc"


def parse_post_url(url: str) -> tuple[str, str]:
    """Extract (handle, rkey) from a Bluesky post URL."""
    match = re.search(r"bsky\.app/profile/([^/]+)/post/([^/?#]+)", url)
    if not match:
        raise ValueError(f"Not a valid Bluesky post URL: {url}")
    return match.group(1), match.group(2)


async def fetch_post(url: str) -> BlueskyPost:
    """Fetch a Bluesky post by URL and return structured data."""
    handle, rkey = parse_post_url(url)

    async with httpx.AsyncClient(timeout=15.0) as client:
        did_resp = await client.get(
            f"{BSKY_API}/com.atproto.identity.resolveHandle",
            params={"handle": handle},
        )
        did_resp.raise_for_status()
        did = did_resp.json()["did"]

        uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        thread_resp = await client.get(
            f"{BSKY_API}/app.bsky.feed.getPostThread",
            params={"uri": uri, "depth": 1, "parentHeight": 1},
        )
        thread_resp.raise_for_status()
        thread_data = thread_resp.json()

    thread_node = thread_data["thread"]
    post_data = thread_node["post"]
    record = post_data["record"]
    author = post_data["author"]

    # Parent post (if this post is a reply in a thread)
    parent_text: str | None = None
    parent_author_handle: str | None = None
    parent_node = thread_node.get("parent")
    if parent_node and parent_node.get("$type") == "app.bsky.feed.defs#threadViewPost":
        parent_post = parent_node.get("post", {})
        parent_text = parent_post.get("record", {}).get("text", "") or None
        parent_author_handle = parent_post.get("author", {}).get("handle") or None

    # All direct replies, sorted by likes
    thread_replies: list[BlueskyReply] = []
    for reply_node in thread_node.get("replies", []):
        if reply_node.get("$type") != "app.bsky.feed.defs#threadViewPost":
            continue
        rp = reply_node.get("post", {})
        rp_text = rp.get("record", {}).get("text", "")
        if not rp_text:
            continue
        rp_author = rp.get("author", {})
        thread_replies.append(BlueskyReply(
            author_handle=rp_author.get("handle", ""),
            author_display_name=rp_author.get("displayName", "") or rp_author.get("handle", ""),
            text=rp_text,
            likes=rp.get("likeCount", 0),
            reposts=rp.get("repostCount", 0),
            replies=rp.get("replyCount", 0),
        ))
    thread_replies.sort(key=lambda r: r.likes, reverse=True)

    images: list[BlueskyImage] = []
    external: BlueskyExternal | None = None

    embed = record.get("embed", {})
    embed_type = embed.get("$type", "")

    if embed_type == "app.bsky.embed.images":
        for img in embed.get("images", []):
            cid = img["image"]["ref"]["$link"]
            images.append(
                BlueskyImage(
                    url=f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{cid}@jpeg",
                    alt=img.get("alt", ""),
                )
            )

    elif embed_type == "app.bsky.embed.external":
        ext = embed.get("external", {})
        external = BlueskyExternal(
            title=ext.get("title", ""),
            description=ext.get("description", ""),
            uri=ext.get("uri", ""),
        )

    # recordWithMedia: post embedding another post + images
    elif embed_type == "app.bsky.embed.recordWithMedia":
        media = embed.get("media", {})
        if media.get("$type") == "app.bsky.embed.images":
            for img in media.get("images", []):
                cid = img["image"]["ref"]["$link"]
                images.append(
                    BlueskyImage(
                        url=f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{cid}@jpeg",
                        alt=img.get("alt", ""),
                    )
                )

    return BlueskyPost(
        uri=post_data["uri"],
        text=record.get("text", ""),
        author_handle=author["handle"],
        author_display_name=author.get("displayName", author["handle"]),
        created_at=record.get("createdAt", ""),
        images=images,
        external=external,
        likes=post_data.get("likeCount", 0),
        reposts=post_data.get("repostCount", 0),
        replies=post_data.get("replyCount", 0),
        parent_text=parent_text,
        parent_author_handle=parent_author_handle,
        thread_replies=thread_replies,
    )
