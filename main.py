import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_caching import Cache
import google.generativeai as genai
from google.cloud import secretmanager
import json
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler


# Create the Secret Manager client
client = secretmanager.SecretManagerServiceClient()

# Construct the secret name
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
print("Project ID Found.")
secret_name = "GEMINI_API_KEY"
name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

# Access the secret
print("Accessing Secret:")
try:
    response = client.access_secret_version(name=name)
    GEMINI_API_KEY = response.payload.data.decode("UTF-8")
    print("Key Found.")
except:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

# Initialize the scheduler
scheduler = BackgroundScheduler()

# Database setup
print("Database Setup:")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///videos.db")  # Default to SQLite
engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)
session = Session()

class Video(Base):
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String, unique=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.now(timezone.utc))  # Default to current time
    frequency = Column(Integer, default=1)  # How often this video has been accessed
    ai_content = Column(Text, nullable=False)  # JSON string of chapters
    transcript = Column(Text, nullable=False)  # Text transcript info
    likes = Column(Integer, default=0)
    dislikes = Column(Integer, default=0)
    version = Column(String, default=1)

# Create tables
Base.metadata.create_all(engine)
print("Database Setup Done.")

# Initialize Gemini model
print("Agent Initialization:")
genai.configure(api_key=GEMINI_API_KEY)
print("Agent Initialized.")

# Generation Configuration
generation_config_structured_data = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

# Pre-configure Gemini agent
print("Agent Configuration:")
agent = genai.GenerativeModel(
    model_name="models/gemini-1.5-flash-8b",
    generation_config=generation_config_structured_data,
    system_instruction = """
        Role: Expert content analyzer, focused on extracting the most impactful and relevant insights from the provided input.
        Goal: Minimize user's time spent on watching videos by extracting the most impactful and relevant insights from the provided input by at least 66%.
        Task: Analyze the transcript of a video, group related content into coherent chapter segments, and assess their significance. Ensure that chapters contain complete sentences, logically group information by topic, and avoid splitting mid-sentence.
        
        ### Categories and Significance Codes <Significance>:
        1. Very Significant chapter (label as: very_significant): Crucial insights that summarize key points, most important part of the content.
        2. Significant chapter (label as: significant): Important but non-critical content that provides meaningful information.
        3. Insignificant chapter (label as: insignificant): Skippable, redundant, slow-paced, or low-value content if you're short on time, as it offers minimal informational benefit.
        4. Out of Topic & Promotional chapter (label as: out_of_topic): Skippable, irrelevant content (intro, outro, bumper, stinger, etc.) that deviates from the main topic or skippable advertisements, sponsorships, or any form of self-promotion
        
        ### Instructions:
        1. **Understand Context**: Thoroughly analyze the entire transcript to grasp the main topic, subtopics, and overall narrative flow.
        2. **Segmentation Rules**:
            - Divide the transcript into chapters based on logical breaks in the content.
            - Ensure each chapter contains complete sentences and avoids splitting mid-sentence.
            - Group related content into coherent chapters based on themes, ideas, or subtopics.
            - If a sentence spans multiple ideas, place it entirely in the chapter where the majority of its content belongs.
        3. **Significance Assessment**:
            - Assign one of the five color categories to each chapter based on its importance and relevance to the main topic.
            - Use the following distribution guidelines:
                - Max 20% of chapters can be labeled as very_significant.
                - Max 35% of chapters can be labeled as significant.
                - Min 35% of chapters must be labeled as insignificant.
                - Min 5% of chapters must be labeled as out_of_topic
                - Promotional content must always be labeled as out_of_topic.
        4. **Chapter Details**:
            - For each chapter, generate:
                - A concise and descriptive chapter name (max 5 words).
                - A short summary (max 20 words) that captures the essence of the chapter.
        5. **Output Format**:
            - Provide results in the following JSON-like format:
                { start: <Start time in seconds>, end: <End time in seconds>, significance: <Significance>, chapter: <Chapter name>, summary: <Chapter summary> }
            - Example output:
                [{start: 0, end: 4, significance: 'out_of_topic', chapter: 'Intro Music', summary: 'Background music plays during the opening.'}, 
                 {start: 5, end: 75, color: 'very_significant', chapter: 'Key Insights', summary: 'The speaker outlines the main argument of the video.'},
                 {start: 76, end: 106, significance: 'significant', chapter: 'General Overview', summary: 'Brief mention of the video topic.'},
                 {start: 107, end: 122, significance: 'insignificant', chapter: 'Minor Details', summary: 'A minor not so important example is given to support the argument.'},  
                 {start: 123, end: 150, significance: 'out_of_topic', chapter: 'Self Promotion', summary: 'The speaker invites viewers to like and subscribe to the channel.'}]
        
        6. **Additional Guidelines**:
            - Avoid excessively short or long chapters (aim for 30-180 seconds per chapter unless the content demands otherwise).
            - Consolidate repeated points into fewer chapters and label them as yellow if they add minimal value.
            - For ambiguous cases, prioritize the category that aligns most closely with the main topic or purpose of the video.
            - If promotional content overlaps with informative content, label it as red unless the informative portion is substantial enough to warrant a separate chapter.
        7. **Final Output**:
            - Return the resulting list without any additional commentary or additions.
            - DO NOT ADD ANY ESCAPE SEQUENCES OR NEWLINES.
    """,
)
print("Agent Configuration Done.")
print("System Instructions Set.")

def update_cache_with_top_videos():
    """
    Update the cache with the top 30% of the highest frequency video_ids.
    """
    print("Updating cache with top 30% videos...")
    # Query all videos sorted by frequency in descending order
    all_videos = session.query(Video).order_by(Video.frequency.desc()).all()

    # Calculate the number of videos to cache (top 30%)
    total_videos = len(all_videos)
    top_videos_count = max(1, int(total_videos * 0.3))  # Ensure at least 1 video is cached

    # Select the top 30% videos
    top_videos = all_videos[:top_videos_count]

    # Update the cache with these videos
    for video in top_videos:
        video_id = video.video_id
        ai_content = json.loads(video.ai_content)
        cache.set(video_id, ai_content)  # Cache the AI content
        print(f"Cached video_id: {video_id}")

    print(f"Cache updated with {len(top_videos)} videos.")

# Schedule the task to run every 15 minutes
scheduler.add_job(update_cache_with_top_videos, 'interval', minutes=15)
scheduler.start()

def ai_chapters(transcript):
    prompt = f"""Transcript:{transcript}
    Analyze this transcript and create chapter segments as specified in the instructions. Return only the JSON array of chapters."""

    try:
        print("Generating Content.")
        response = agent.generate_content(prompt)
        print("Generated.")
        
        # Parse the response text as JSON to avoid double encoding
        try:
            chapters = json.loads(response.text)
            return chapters  # Return the parsed JSON directly
        except json.JSONDecodeError as e:
            print(f"Error parsing Gemini response as JSON: {e}")
            return response.text  # Fallback to raw text if parsing fails
            
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        raise

app = Flask(__name__)
print("Flask up and running.")

# Enable CORS for all routes
CORS(app,
     resources={
         r"/*": {
             "origins": ["https://www.youtube.com", "chrome-extension://*"],
             "methods": ["POST"],  # Changed from GET to POST
             "allow_headers": ["Content-Type"]
         }
     })

# Configure caching
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 900})  # 15-minute timeout

@app.route('/check_video_id', methods=['GET'])
def check_video_id():
    """
    Check if video_id exists in the cache or database.
    - If found in the cache, return the cached AI content.
    - If found in the database but not in the cache, return the stored AI content and cache it.
    - If not found, return a 404 error.
    """
    # Get the video_id from query parameters
    video_id = request.args.get('video_id')
    if not video_id:
        return jsonify({"error": "Missing video_id parameter"}), 400

    # Check the cache first
    cached_result = cache.get(video_id)
    if cached_result:
        print(f"Cache hit for video_id: {video_id}")
        return jsonify({"result": cached_result})

    # Check the database
    video = session.query(Video).filter_by(video_id=video_id).first()
    if video:
        print(f"Database hit for video_id: {video_id}")
        # Increment access frequency
        video.frequency += 1
        session.commit()

        # Parse the AI content from the database
        ai_content = json.loads(video.ai_content)

        return jsonify({"result": ai_content})

    # If the video_id is not found in the cache or database
    return jsonify({"error": "Video ID not found"}), 404
  
@app.route('/process_video', methods=['POST'])
def process_video():
    """
    Process a video request and generate AI content, store it, and return it.
    """
    # Parse the incoming JSON data
    data = request.get_json()
    video_id = data.get('video_id')
    transcript = data.get('transcript')

    # Validate input
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400
    if not transcript:
        return jsonify({"error": "Missing transcript for new video_id"}), 400

    # Generate chapters using AI
    try:
        chapters = ai_chapters(transcript)
        ai_content = json.dumps(chapters)  # Convert chapters to JSON string for storage
    except Exception as e:
        return jsonify({"error": f"Failed to generate chapters: {str(e)}"}), 500

    # Store the new video entry in the database
    new_video = Video(
        video_id=video_id,
        timestamp=datetime.now(timezone.utc),
        ai_content=ai_content,
        transcript=transcript
    )
    session.add(new_video)
    session.commit()

    # Return the generated content
    return jsonify({"result": chapters}), 201

@app.route("/")
def hello_world():
    return "YouTube Video Chapters"

if __name__ == "__main__":
    
    # Start the scheduler
    scheduler.start()
    print("Scheduler started.")
    
    # Run the Flask app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
