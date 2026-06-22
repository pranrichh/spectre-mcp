"""Pydantic models for clean MCP tool responses."""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """X/Twitter user profile."""
    id: int
    username: str
    display_name: str
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    followers: int = 0
    following: int = 0
    tweets: int = 0
    likes: int = 0
    media_count: int = 0
    verified: bool = False
    blue_verified: bool = False
    profile_image_url: Optional[str] = None
    banner_url: Optional[str] = None
    created_at: Optional[str] = None


class Tweet(BaseModel):
    """X/Twitter tweet/post."""
    id: int
    url: str
    text: str
    author_username: str
    author_name: str
    created_at: str
    lang: Optional[str] = None
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0
    quote_count: int = 0
    view_count: int = 0
    bookmark_count: int = 0
    is_retweet: bool = False
    is_quote: bool = False
    is_reply: bool = False
    media_urls: list[str] = Field(default_factory=list)
    media_types: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    mentioned_users: list[str] = Field(default_factory=list)
    quoted_tweet: Optional[str] = None  # quoted tweet text if any
    in_reply_to_id: Optional[int] = None
    conversation_id: Optional[int] = None


class Trend(BaseModel):
    """Trending topic."""
    name: str
    tweet_count: Optional[int] = None
    category: Optional[str] = None
    domain: Optional[str] = None


class CommunityInfo(BaseModel):
    """X/Twitter community info."""
    id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    created_at: Optional[str] = None
    admin_ids: list[int] = Field(default_factory=list)


class AccountStatus(BaseModel):
    """Account pool status."""
    total: int = 0
    active: int = 0
    locked: int = 0
    error: int = 0
    accounts: list[dict] = Field(default_factory=list)
