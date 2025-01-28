import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "Hello, World! This is a Python web server on Google Cloud Run."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))