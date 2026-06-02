from pydantic import BaseModel
from typing import Optional


class BlueskyImage(BaseModel):
    url: str
    alt: str


class BlueskyExternal(BaseModel):
    title: str
    description: str
    uri: str


class BlueskyReply(BaseModel):
    author_handle: str
    author_display_name: str
    text: str
    likes: int = 0
    reposts: int = 0
    replies: int = 0


class BlueskyPost(BaseModel):
    uri: str
    text: str
    author_handle: str
    author_display_name: str
    created_at: str
    images: list[BlueskyImage] = []
    external: Optional[BlueskyExternal] = None
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    parent_text: Optional[str] = None
    parent_author_handle: Optional[str] = None
    thread_replies: list[BlueskyReply] = []


class ExplainRequest(BaseModel):
    url: str
    provider: str = "openai"  # "openai" or "anthropic"


class Citation(BaseModel):
    title: str
    url: str


class ExplainResponse(BaseModel):
    bullets: list[str]
    post: BlueskyPost
    citations: list[Citation]
    provider: str
