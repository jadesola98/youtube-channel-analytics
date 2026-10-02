
# imported necessary libraries
from googleapiclient.discovery import build
from dotenv import load_dotenv
import pandas as pd
import seaborn as sns
import os

load_dotenv()

api_key = os.getenv("YOUTUBE_API_KEY")
user = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")
host = os.getenv("DB_HOST")
dbname = os.getenv("DB_NAME")


pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)


# defined necessary configurations
channel_ids = ['UCnz-ZXXER4jOvuED5trXfEA', # techTFQ
               'UCChmJrVa8kDg05JfCmxpLRw', # Darshil Parmar 
               'UCCTVrRB5KpIiK6V2GGVsR1Q', # Kudvenkat
               'UC7cs8q-gJRlGwj4A8OmCmXg', # Alex the analyst
               'UCk7NcgnqCmui1AV7MTXZwOw' # Ankit Bansal
              ]

youtube = build('youtube', 'v3', developerKey=api_key)


# created a function to get channel details(channel name, id, subscribers)
def get_channel_stats(youtube, channel_ids):
    all_data = []
    request = youtube.channels().list(
                part='snippet,contentDetails,statistics',
                id=','.join(channel_ids))
    response = request.execute() 
    
    for i in range(len(response['items'])):
        data = dict(Channel_id = response['items'][i]['id'],
                    Channel_name = response['items'][i]['snippet']['title'],
                    Subscribers = response['items'][i]['statistics']['subscriberCount'],
                    playlist_id = response['items'][i]['contentDetails']['relatedPlaylists']['uploads'])
        all_data.append(data)
    
    return all_data


channel_statistics = get_channel_stats(youtube, channel_ids)


# saved data into a dataframe
channel_data = pd.DataFrame(channel_statistics)


print(channel_data)


# convert subscribers column to a numeric field
channel_data['Subscribers'] = pd.to_numeric(channel_data['Subscribers'])



# created a function get video ids in other to pass the video ids into a function that will get the video details
def get_video_ids(youtube, playlist_id):
    
    request = youtube.playlistItems().list(
                part='contentDetails',
                playlistId = playlist_id,
                maxResults = 50)
    response = request.execute()
    
    video_ids = []
    
    for i in range(len(response['items'])):
        video_ids.append(response['items'][i]['contentDetails']['videoId'])
        
    next_page_token = response.get('nextPageToken')
    more_pages = True
    
    while more_pages:
        if next_page_token is None:
            more_pages = False
        else:
            request = youtube.playlistItems().list(
                        part='contentDetails',
                        playlistId = playlist_id,
                        maxResults = 50,
                        pageToken = next_page_token)
            response = request.execute()
    
            for i in range(len(response['items'])):
                video_ids.append(response['items'][i]['contentDetails']['videoId'])
            
            next_page_token = response.get('nextPageToken')
        
    return video_ids


# save playlist ids from channel_data dataframe into a list in other to pass it into the get_video_ids function
playlist_id=channel_data['playlist_id'].to_list()


video_ids=[]
for i in playlist_id:
    video_ids.append(get_video_ids(youtube, i))
    
video_ids = [item for sublist in video_ids for item in sublist]


print(len(video_ids))


# created a function to get video details
def get_video_details(youtube, video_ids):
    all_video_stats = []
    
    for i in range(0, len(video_ids), 50):
        request = youtube.videos().list(
                    part='snippet,statistics',
                    id=','.join(video_ids[i:i+50]))
        response = request.execute()
        
        for video in response['items']:
            video_stats = dict(Title = video['snippet']['title'],
                               Published_date = video['snippet']['publishedAt'],
                               Views = video['statistics']['viewCount'],
                               Likes = video['statistics']['likeCount'],
                               Comments = video['statistics']['commentCount'],
                               Channel_id = video['snippet']['channelId']
                               )
            all_video_stats.append(video_stats)
    
    return all_video_stats


v1=get_video_details(youtube, video_ids)



# saved the data into a dataframe
video_data = pd.DataFrame(v1)



print(len(video_data))


# converted the date column into a date data type and the numeric columns into numeric data type
video_data['Published_date'] = pd.to_datetime(video_data['Published_date']).dt.date
video_data['Views'] = pd.to_numeric(video_data['Views'])
video_data['Likes'] = pd.to_numeric(video_data['Likes'])
video_data['Comments'] = pd.to_numeric(video_data['Comments'])
video_data.dtypes


#### This part of the script involves the steps taken to insert the data extracted from youtube's api into tables in a postgres database
from sqlalchemy import create_engine


engine = create_engine(f"postgres://{user}:{password}@{host}/{dbname}")


engine.connect()


#print(pd.io.sql.get_schema(channel_data, name='channel_data', con=engine))


# created the channel data table in postgres database
channel_data.head(n=0).to_sql(name='channel_data', con=engine, if_exists='replace')


# created the video data table in postgres database
video_data.head(n=0).to_sql(name='video_data', con=engine, if_exists='replace')


# saved channel_data into channel data table in the postgres database
channel_data.to_sql(name='channel_data', con=engine, if_exists='append')


# saved video_data into video data table in the postgres database
video_data.to_sql(name='video_data', con=engine, if_exists='append', chunksize=200)


