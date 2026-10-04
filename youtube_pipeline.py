"""
YouTube channel analytics pipeline.

Extracts channel and video statistics for a list of data-education YouTube
channels from the YouTube Data API v3, cleans them with pandas, and loads them
into PostgreSQL, where a Power BI dashboard reads them.

Configuration comes from environment variables (see .env.example).
Run with:  python youtube_pipeline.py
"""

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd
from dotenv import load_dotenv
from googleapiclient.discovery import build
from sqlalchemy import create_engine

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")

CHANNEL_IDS = [
    "UCnz-ZXXER4jOvuED5trXfEA",  # techTFQ
    "UCChmJrVa8kDg05JfCmxpLRw",  # Darshil Parmar
    "UCCTVrRB5KpIiK6V2GGVsR1Q",  # Kudvenkat
    "UC7cs8q-gJRlGwj4A8OmCmXg",  # Alex the Analyst
    "UCk7NcgnqCmui1AV7MTXZwOw",  # Ankit Bansal
]

API_BATCH_SIZE = 50  # the YouTube API returns at most 50 items per request

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- extract

def get_channel_stats(youtube, channel_ids):
    """One request returns name, subscriber count and uploads playlist for every channel."""
    response = youtube.channels().list(
        part="snippet,contentDetails,statistics",
        id=",".join(channel_ids),
    ).execute()

    return [
        {
            "Channel_id": item["id"],
            "Channel_name": item["snippet"]["title"],
            "Subscribers": item["statistics"].get("subscriberCount"),
            "playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }
        for item in response.get("items", [])
    ]


def get_video_ids(youtube, playlist_id):
    """Page through a channel's uploads playlist and return every video ID."""
    video_ids, page_token = [], None
    while True:
        response = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=API_BATCH_SIZE,
            pageToken=page_token,
        ).execute()
        video_ids += [item["contentDetails"]["videoId"] for item in response.get("items", [])]
        page_token = response.get("nextPageToken")
        if not page_token:
            return video_ids


def get_video_details(youtube, video_ids):
    """Fetch title, publish date and engagement stats, 50 videos per request."""
    videos = []
    for start in range(0, len(video_ids), API_BATCH_SIZE):
        response = youtube.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids[start:start + API_BATCH_SIZE]),
        ).execute()
        for video in response.get("items", []):
            stats = video.get("statistics", {})
            videos.append({
                "Title": video["snippet"]["title"],
                "Published_date": video["snippet"]["publishedAt"],
                # Likes and comments are missing when a creator hides or disables them
                "Views": stats.get("viewCount"),
                "Likes": stats.get("likeCount"),
                "Comments": stats.get("commentCount"),
                "Channel_id": video["snippet"]["channelId"],
            })
    return videos


def extract(youtube):
    channels = get_channel_stats(youtube, CHANNEL_IDS)
    logger.info(f"Fetched {len(channels)} channels")

    video_ids = []
    for channel in channels:
        ids = get_video_ids(youtube, channel["playlist_id"])
        logger.info(f"  {channel['Channel_name']}: {len(ids)} videos")
        video_ids += ids

    videos = get_video_details(youtube, video_ids)
    logger.info(f"Fetched details for {len(videos)} videos")
    return channels, videos


# -------------------------------------------------------------- transform

def transform(channels, videos):
    """Turn API strings into proper types and stamp each row with the extraction time."""
    extracted_at = datetime.now(timezone.utc)

    channel_data = pd.DataFrame(channels)
    channel_data["Subscribers"] = pd.to_numeric(channel_data["Subscribers"]).astype("Int64")
    channel_data["extracted_at"] = extracted_at

    video_data = pd.DataFrame(videos)
    video_data["Published_date"] = pd.to_datetime(video_data["Published_date"]).dt.date
    for column in ["Views", "Likes", "Comments"]:
        video_data[column] = pd.to_numeric(video_data[column]).astype("Int64")
    video_data["extracted_at"] = extracted_at

    return channel_data, video_data


# ------------------------------------------------------------------- load

def load(channel_data, video_data):
    """Replace both tables in one transaction, so Power BI never sees half a refresh."""
    engine = create_engine(
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    with engine.begin() as conn:
        channel_data.to_sql("channel_data", conn, if_exists="replace", index=False)
        video_data.to_sql("video_data", conn, if_exists="replace", index=False, chunksize=500)
    logger.info(f"Loaded {len(channel_data)} channels and {len(video_data)} videos into {DB_NAME}")


def main():
    if not API_KEY:
        logger.error("YOUTUBE_API_KEY is not set - add it to your .env file")
        sys.exit(1)

    try:
        youtube = build("youtube", "v3", developerKey=API_KEY)
        channels, videos = extract(youtube)
        channel_data, video_data = transform(channels, videos)
        load(channel_data, video_data)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
