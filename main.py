import os, uuid, shutil, subprocess
from flask import Flask, request, render_template_string, send_from_directory, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message

# Load env
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
STREAM_FOLDER = "streams"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STREAM_FOLDER, exist_ok=True)

# -----------------------------
# Telegram Bot
# -----------------------------
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.command("start"))
def start_cmd(client, message):
    message.reply_text("Send me 2-3 video files (480p/720p/1080p), I will create HLS streaming link!")

@bot.on_message(filters.document)
def handle_videos(client, message: Message):
    # Only video files
    if not message.document.mime_type.startswith("video/"):
        message.reply_text("Please send a video file only.")
        return

    vid_id = str(uuid.uuid4())
    temp_dir = os.path.join(UPLOAD_FOLDER, vid_id)
    os.makedirs(temp_dir, exist_ok=True)

    file_path = os.path.join(temp_dir, message.document.file_name)
    message.download(file_path)

    # Convert to HLS
    stream_dir = os.path.join(STREAM_FOLDER, vid_id)
    os.makedirs(stream_dir, exist_ok=True)
    hls_file = os.path.join(stream_dir, "master.m3u8")

    # FFmpeg copy mode for low CPU load
    cmd = [
        "ffmpeg", "-i", file_path,
        "-c:v", "copy", "-c:a", "copy",
        "-f", "hls", "-hls_time", "6", "-hls_list_size", "0",
        "-hls_flags", "delete_segments+temp_file",
        hls_file
    ]
    subprocess.run(cmd)

    # Clean up uploaded file
    shutil.rmtree(temp_dir, ignore_errors=True)

    # Send back watch link
    host_url = "https://YOUR_RENDER_URL"  # Change to your server URL
    message.reply_text(f"✅ Video processed!\nWatch here: {host_url}/watch/{vid_id}")

# -----------------------------
# Flask Web
# -----------------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Stream Video</title>
<link href="https://vjs.zencdn.net/7.15.4/video-js.css" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script src="https://vjs.zencdn.net/7.15.4/video.min.js"></script>
<style>
body { background:#000; color:#fff; text-align:center; margin-top:30px; }
video { width:90%; height:auto; border-radius:15px; }
</style>
</head>
<body>
<h2>{{title}}</h2>
<video id="video" class="video-js vjs-default-skin" controls></video>
<script>
var video = document.getElementById('video');
if(Hls.isSupported()){
  var hls = new Hls();
  hls.loadSource('{{stream_url}}');
  hls.attachMedia(video);
  hls.on(Hls.Events.MANIFEST_PARSED,function(){video.play();});
}else if(video.canPlayType('application/vnd.apple.mpegurl')){
  video.src='{{stream_url}}';
  video.addEventListener('loadedmetadata',function(){video.play();});
}
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return jsonify({"status":"running","message":"Telegram HLS Streaming Server Live!"})

@app.route('/stream/<vid>/<path:filename>')
def stream(vid, filename):
    return send_from_directory(os.path.join(STREAM_FOLDER, vid), filename)

@app.route('/watch/<vid>')
def watch(vid):
    stream_url = f"/stream/{vid}/master.m3u8"
    return render_template_string(HTML_TEMPLATE, title="Now Streaming", stream_url=stream_url)

# -----------------------------
# Run Bot + Flask
# -----------------------------
if __name__ == "__main__":
    from threading import Thread
    # Start Bot in separate thread
    Thread(target=lambda: bot.run()).start()
    # Start Flask Server
    app.run(host='0.0.0.0', port=5000)
