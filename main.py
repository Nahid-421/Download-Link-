import os, uuid, shutil, subprocess, asyncio
from flask import Flask, request, render_template_string, send_from_directory, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message
from threading import Thread

# -----------------------------
# Configuration
# -----------------------------
# Ensure these environment variables are set up in your deployment environment
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
STREAM_FOLDER = "streams"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STREAM_FOLDER, exist_ok=True)

# -----------------------------
# Telegram Bot (Pyrogram)
# -----------------------------
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Dictionary to store user files: {user_id: [file_path_1, file_path_2, ...]}
user_files = {}

# -----------------------------
# HLS Conversion Function (Asynchronous)
# -----------------------------
async def convert_and_stream(message: Message, file_paths: list):
    """Converts a list of video files to HLS using FFmpeg and sends the stream link."""
    
    vid_id = str(uuid.uuid4())
    stream_dir = os.path.join(STREAM_FOLDER, vid_id)
    os.makedirs(stream_dir, exist_ok=True)
    hls_file = os.path.join(stream_dir, "master.m3u8")

    processing_message = await message.reply_text("⏳ Processing files. HLS link being generated...", quote=True)

    try:
        # Create a safe input argument list for FFmpeg
        if len(file_paths) > 1:
            # For multiple files, use the 'concat' demuxer
            temp_dir = os.path.dirname(file_paths[0])
            concat_file_path = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_file_path, "w") as f:
                for path in file_paths:
                    f.write(f"file '{path}'\n")
            
            input_args = ["-f", "concat", "-safe", "0", "-i", concat_file_path]
        else:
            # Single file input
            input_args = ["-i", file_paths[0]]
        
        
        # FFmpeg command for HLS conversion (using copy mode for speed)
        cmd = [
            "ffmpeg", *input_args,
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls", "-hls_time", "6", "-hls_list_size", "0",
            "-hls_flags", "delete_segments+temp_file",
            hls_file
        ]

        # Execute FFmpeg asynchronously to avoid blocking the bot
        process = await asyncio.create_subprocess_exec(*cmd, 
                                                       stdout=subprocess.PIPE, 
                                                       stderr=subprocess.PIPE)
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg failed: {stderr.decode()}")
        
        # Clean up uploaded files and temp folder
        temp_dir = os.path.dirname(file_paths[0])
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        # Send back watch link
        host_url = "https://YOUR_RENDER_URL"  # CHANGE THIS
        await processing_message.edit_text(
            f"✅ Video processed!\nWatch here: {host_url}/watch/{vid_id}"
        )

    except Exception as e:
        # Cleanup stream directory if conversion fails
        shutil.rmtree(stream_dir, ignore_errors=True)
        try:
            temp_dir = os.path.dirname(file_paths[0])
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
            
        await processing_message.edit_text(f"❌ Processing Error: {str(e)}")
            

# -----------------------------
# Telegram Handlers
# -----------------------------
@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "👋 Send me your video files (480p/720p/1080p). "
        "When finished, reply with the text **done** or **ডান**."
    )
    user_files[message.chat.id] = [] # Reset file list

@bot.on_message(filters.private & (filters.document | filters.text))
async def handle_user_input(client, message: Message):
    user_id = message.chat.id

    # 1. 'DONE' Command Handling
    if message.text and message.text.lower() in ["done", "ডান"]:
        if user_id not in user_files or not user_files[user_id]:
            await message.reply_text("🤷‍♂️ You haven't sent any video files yet.", quote=True)
            return
        
        # Start conversion process
        file_paths_to_process = user_files.pop(user_id) # Get files and clear state
        
        # Run conversion as an asynchronous task
        asyncio.create_task(convert_and_stream(message, file_paths_to_process))
        return

    # 2. Video File Handling
    if message.document and message.document.mime_type.startswith("video/"):
        
        # Create unique and secure folder
        vid_id = str(uuid.uuid4())
        temp_dir = os.path.join(UPLOAD_FOLDER, vid_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        # Use a random file name for security (avoiding shell injection via file names)
        safe_file_name = str(uuid.uuid4()) + "_" + message.document.file_name
        file_path = os.path.join(temp_dir, safe_file_name)
        
        # Download file
        await message.download(file_path)

        # Update file list
        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append(file_path)
        
        count = len(user_files[user_id])
        await message.reply_text(
            f"✅ File {count} added. Send more or reply with **done**.",
            quote=True
        )
        return
    
    # Ignore other text messages if the user is not in a 'file collection' state
    if user_id not in user_files or not user_files[user_id]:
        if not (message.text and message.text.lower() in ["done", "ডান"]):
             await message.reply_text("Please send a video file or the command **done**.", quote=True)


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
# Run Bot + Flask Concurrently (FIXED)
# -----------------------------

def run_flask():
    """Function to run Flask in a blocking thread."""
    # Production deployment should use a proper WSGI server like Gunicorn/Waitress
    app.run(host='0.0.0.0', port=5000)

async def main():
    """Starts both the Pyrogram bot and the Flask server concurrently."""
    print("Starting Flask server...")
    # 1. Start Flask server in a dedicated thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    print("Starting Pyrogram bot...")
    # 2. Start Pyrogram bot in the main asyncio event loop
    await bot.start()
    
    # Keep the main loop running indefinitely to handle bot updates
    await asyncio.Future() 
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot and server stopped by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
