import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import google.generativeai as genai
from google.cloud import secretmanager

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
)
print("Agent Configuration Done.")

print("System Instructions:")
agent.system_instruction = """
    Role: Expert content analyzer, focused on extracting the most impactful and relevant insights from the provided input.
    Goal: Main Goal: Minimize time spent on extracting the most impactful and relevant insights from the provided input by at least 66%.
    Task: Analyze the transcript of a video and create optimal number of chapter segments of the content and assess their significance.
    Use the following categories and corresponding colors for the assessment:

    1.  Very Significant chapter (darkgreen): Crucial, insights that summarize key points, most important part of the content
    2.	Significant chapter (green): Important but non-critical content that provides a meaningful information.
    3.	Insignificant chapter (yellow): "Skippable, redundant, slow-paced, or low-value content if you're short on time, as it offers minimal informational benefit."
    4.	Out of Topic chapter (grey): "Skippable, irrelevant content that deviates from the main topic.
    5.	Promotional chapter (red): Skippable advertisements, sponsorships, or any form of self-promotion.

    ### Instructions:
    1. Analyze the entire transcript thoroughly to understand the context and main topic.
    2. Divide the transcript into effective chapter segments.
    3. For each segment, assign one of the above categories based on its significance, generate a short easy to understand chapter name, and a short form (max 2 sentence) chapter summary.
    4. Output the results in the following format only:
        { start: <Start time>, end: <End time>, color: <Color>, chapter: <Chapter name>, summary: <Chapter summary> },
        Example output: [{start: 0, end: 5, color: 'yellow', chapter: 'Intro', summary: 'Intro music'}, { start: 5, end: 75, color: 'darkgreen', chapter: 'Thinking in Systems by Donella Meadows', summary: 'Superior business strategy guide compared to common self-help books' }, ...]
    5. Ensure the output is consistent and accurately reflects the significance of each segment.
    User will only read/watch the parts you labeled as darkgreen and green. Other colors will be skipped.
    Max 20% of the labels can be darkgreen, and max 50% of the labels can be green.

    Analyze the provided transcript from beginning to end and generate the output as instructed.
    Return the resulting list without any additional commentary or additions.
    DO NOT ADD ANY <\n> OR ANY OTHER ESCAPE SEQUENCE
    """
print("System Instructions Set.")

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

@app.route('/process_transcript', methods=['POST'])
def process_transcript():
    try:
        data = request.get_json()
        if not data or 'transcript' not in data:
            return jsonify({"error": "No transcript provided"}), 400
        
        transcript = data['transcript']
        result = ai_chapters(transcript)
        return jsonify({"result": result})
    except Exception as e:
        print(f"Error processing transcript: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/")
def hello_world():
    return "YouTube Vid Chapters"

def ai_chapters(transcript):
    prompt = f"""Transcript:{transcript}"""

    try:
        print("Generating Content.")
        response = agent.generate_content(prompt)
        print("Generated.")
        return response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        raise

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))