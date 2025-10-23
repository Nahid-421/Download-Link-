import os, uuid, shutil, subprocess, asyncio
from flask import Flask, request, render_template_string, send_from_directory, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message
from threading import Thread

# ... (আপনার Configuration এবং Flask app ইনিশিয়ালাইজেশন একই থাকবে)
# -----------------------------
# Configuration
# -----------------------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
STREAM_FOLDER = "streams"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STREAM_FOLDER, exist_ok=True)

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# {user_id: {"dir": "path/to/user_dir", "files": ["file1.mp4", "file2.mp4"]}}
user_files = {}

# -----------------------------
# HLS Conversion Function (Asynchronous) - FIXED
# -----------------------------
async def convert_and_stream(message: Message, user_session: dict):
    """Converts a list of video files to HLS using FFmpeg and sends the stream link."""
    
    file_paths = user_session["files"]
    temp_dir = user_session["dir"] # The single directory containing all files

    vid_id = str(uuid.uuid4())
    stream_dir = os.path.join(STREAM_FOLDER, vid_id)
    os.makedirs(stream_dir, exist_ok=True)
    hls_file = os.path.join(stream_dir, "master.m3u8")

    processing_message = await message.reply_text("⏳ Processing files. HLS link being generated...", quote=True)

    try:
        if len(file_paths) > 1:
            concat_file_path = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_file_path, "w") as f:
                for path in file_paths:
                    # Use only the filename as FFmpeg will run from this directory
                    f.write(f"file '{os.path.basename(path)}'\n")
            
            input_args = ["-f", "concat", "-safe", "0", "-i", concat_file_path]
        else:
            input_args = ["-i", file_paths[0]]
        
        # FFmpeg command for HLS conversion (RE-ENCODING for reliability)
        # This is slower but works for videos with different properties
        cmd = [
            "ffmpeg", *input_args,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", # Video re-encoding
            "-c:a", "aac", "-b:a", "128k", # Audio re-encoding
            "-f", "hls", "-hls_time", "6", "-hls_list_size", "0",
            "-hls_flags", "delete_segments+temp_file",
            hls_file
        ]

        # If you are SURE all videos are identical, you can use the faster copy method:
        # cmd = [
        #     "ffmpeg", *input_args,
        #     "-c", "copy",
        #     "-f", "hls", "-hls_time", "6", "-hls_list_size", "0",
        #     "-hls_flags", "delete_segments+temp_file",
        #     hls_file
        # ]

        process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_message = stderr.decode()
            # Log the full error for debugging
            print(f"FFMPEG ERROR: {error_message}") 
            # Show a simpler error to the user
            raise Exception(f"FFmpeg failed. Could not process the videos.")
        
        # Clean up uploaded files and temp folder
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        # !! CHANGE THIS URL !!
        host_url = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
        await processing_message.edit_text(
            f"✅ Video processed!\nWatch here: {host_url}/watch/{vid_id}"
        )

    except Exception as e:
        shutil.rmtree(stream_dir, ignore_errors=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        await processing_message.edit_text(f"❌ Processing Error: {str(e)}")

# -----------------------------
# Telegram Handlers - FIXED
# -----------------------------
@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    # Clean up any old data for the user
    if message.chat.id in user_files:
        shutil.rmtree(user_files[message.chat.id]["dir"], ignore_errors=True)
        del user_files[message.chat.id]
        
    await message.reply_text(
        "👋 Send me your video files (e.g., 480p/720p/1080p). "
        "When finished, reply with the text **done** or **ডান**."
    )

@bot.on_message(filters.private & (filters.document | filters.text))
async def handle_user_input(client, message: Message):
    user_id = message.chat.id

    if message.text and message.text.lower() in ["done", "ডান"]:
        if user_id not in user_files or not user_files[user_id]["files"]:
            await message.reply_text("🤷‍♂️ You haven't sent any video files yet.", quote=True)
            return
        
        user_session = user_files.pop(user_id)
        asyncio.create_task(convert_and_stream(message, user_session))
        return

    if message.document and message.document.mime_type and message.document.mime_type.startswith("video/"):
        
        # If this is the first file for the user, create a session and directory
        if user_id not in user_files:
            session_id = str(uuid.uuid4())
            user_dir = os.path.join(UPLOAD_FOLDER, session_id)
            os.makedirs(user_dir, exist_ok=True)
            user_files[user_id] = {"dir": user_dir, "files": []}
        
        # Define file path inside the user's specific session directory
        file_name = message.document.file_name
        file_path = os.path.join(user_files[user_id]["dir"], file_name)
        
        download_msg = await message.reply_text(f"📥 Downloading '{file_name}'...", quote=True)
        await message.download(file_path)

        user_files[user_id]["files"].append(file_path)
        
        count = len(user_files[user_id]["files"])
        await download_msg.edit_text(
            f"✅ File {count} ('{file_name}') added.\nSend more files or reply with **done** or **ডান**."
        )
        return
    
    # Ignore other text messages
    if message.text:
         await message.reply_text("Please send a video file, or type **done** to process.", quote=True)

# ... (বাকি Flask এবং main ফাংশন একই থাকবে)
# Just make sure to update the host_url in the conversion function.

# -----------------------------
# Flask Web Server
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
<h2>Now Streaming</h2>
<video id="video" class="video-js vjs-default-skin" controls preload="auto"></video>
<script>
var video = document.getElementById('video');
var videoSrc = '{{stream_url}}';
if (Hls.isSupported()) {
  var hls = new Hls();
  hls.loadSource(videoSrc);
  hls.attachMedia(video);
  hls.on(Hls.Events.MANIFEST_PARSED, function() {
    video.play();
  });
} else if (video.canPlayType('application/vnd.apple.mpegurl')) {
  video.src = videoSrc;
  video.addEventListener('loadedmetadata', function() {
    video.play();
  });
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
    return render_template_string(HTML_TEMPLATE, stream_url=stream_url)

# -----------------------------
# Run Bot + Flask Concurrently
# -----------------------------
def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

async def main():
    print("Starting Flask server...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print("Starting Pyrogram bot...")
    await bot.start()
    
    print("Bot and Server are running!")
    await asyncio.Future() 
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot and server stopped by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
