import os, uuid, shutil, subprocess, asyncio
from flask import Flask, request, render_template_string, send_from_directory, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message
from threading import Thread

# -----------------------------
# Configuration (পরিবেশের ভ্যারিয়েবল লোড করুন)
# -----------------------------
# ধরে নেওয়া হচ্ছে আপনি পরিবেশের ভ্যারিয়েবল (Environment Variables) সেট করেছেন।
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
STREAM_FOLDER = "streams"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STREAM_FOLDER, exist_ok=True)

# -----------------------------
# টেলিগ্রাম বট (Pyrogram)
# -----------------------------
# Pyrogram Asynchronous হওয়া উচিত
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ব্যবহারকারীর ফাইল স্টোর করার জন্য ডিকশনারি
# Key: user_id, Value: list of file_paths
user_files = {}

# -----------------------------
# HLS কনভার্সন ফাংশন (অ্যাসিঙ্ক্রোনাস)
# -----------------------------
async def convert_and_stream(message: Message, file_paths: list):
    """FFmpeg ব্যবহার করে ভিডিওগুলিকে HLS-এ রূপান্তর করে এবং লিঙ্ক পাঠায়।"""
    
    # একাধিক ফাইল থেকে একটি HLS স্ট্রিম তৈরি করার প্রক্রিয়া এখানে পরিবর্তন করা হয়েছে।
    # এখন আমরা একটি একক, অনন্য স্ট্রিম ID ব্যবহার করে কনভার্সন করব।
    vid_id = str(uuid.uuid4())
    stream_dir = os.path.join(STREAM_FOLDER, vid_id)
    os.makedirs(stream_dir, exist_ok=True)
    hls_file = os.path.join(stream_dir, "master.m3u8")

    try:
        # Concatenating multiple files (যদি একাধিক ভিডিও থাকে)
        # Note: Concatenating in 'copy' mode requires consistent codecs.
        # এর জন্য একটি temporary 'concat' file তৈরি করা হচ্ছে।
        
        if len(file_paths) > 1:
            concat_file_path = os.path.join(os.path.dirname(file_paths[0]), "concat_list.txt")
            with open(concat_file_path, "w") as f:
                for path in file_paths:
                    f.write(f"file '{path}'\n")
            
            input_args = ["-f", "concat", "-safe", "0", "-i", concat_file_path]
        else:
            input_args = ["-i", file_paths[0]]
        
        
        # FFmpeg copy mode for low CPU load (দ্রুত এবং রিসোর্স-সহায়ক)
        cmd = [
            "ffmpeg", *input_args,
            "-c:v", "copy", "-c:a", "copy",
            "-f", "hls", "-hls_time", "6", "-hls_list_size", "0",
            "-hls_flags", "delete_segments+temp_file",
            hls_file
        ]

        # অ্যাসিঙ্ক্রোনাসভাবে FFmpeg প্রক্রিয়া চালানো
        process = await asyncio.create_subprocess_exec(*cmd, 
                                                       stdout=subprocess.PIPE, 
                                                       stderr=subprocess.PIPE)
        
        # প্রক্রিয়া শেষ হওয়ার জন্য অপেক্ষা করুন
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg failed with error:\n{stderr.decode()}")
        
        # Clean up uploaded files and temp folder
        temp_dir = os.path.dirname(file_paths[0])
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        # Send back watch link
        host_url = "https://YOUR_RENDER_URL"  # Change to your server URL
        await message.reply_text(
            f"✅ ভিডিও প্রক্রিয়াকরণ সম্পূর্ণ!\nদেখুন: {host_url}/watch/{vid_id}",
            quote=True
        )

    except Exception as e:
        await message.reply_text(f"❌ প্রক্রিয়াকরণে ত্রুটি: {str(e)}", quote=True)
        # ব্যর্থ হলে আংশিক ফাইল ও ফোল্ডার পরিষ্কার করা
        shutil.rmtree(stream_dir, ignore_errors=True)
        try:
            temp_dir = os.path.dirname(file_paths[0])
            shutil.rmtree(temp_dir, ignore_errors=True)
        except:
            pass
            

# -----------------------------
# টেলিগ্রাম হ্যান্ডলার
# -----------------------------
@bot.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "👋 স্বাগতম! আপনি যতগুলো ভিডিও ফাইল (480p/720p/1080p) HLS-এ রূপান্তর করতে চান, সেগুলো পাঠান।\n\n"
        "সব ফাইল পাঠানো হলে, শুধু **ডান** (বা **done**) লিখে দিন।"
    )
    user_files[message.chat.id] = [] # ব্যবহারকারী শুরু করলে তালিকাটি রিসেট করুন

@bot.on_message(filters.private & (filters.document | filters.text))
async def handle_user_input(client, message: Message):
    user_id = message.chat.id

    # 1. 'ডান' কমান্ড হ্যান্ডলিং
    if message.text and message.text.lower() in ["ডান", "done"]:
        if user_id not in user_files or not user_files[user_id]:
            await message.reply_text("🤷‍♂️ আপনি এখনও কোনো ভিডিও ফাইল পাঠাননি।", quote=True)
            return
        
        # কনভার্সন প্রক্রিয়া শুরু করুন
        await message.reply_text("⏳ ফাইল পেয়েছি। HLS স্ট্রিমিং লিঙ্ক তৈরি হচ্ছে, একটু অপেক্ষা করুন...", quote=True)
        file_paths_to_process = user_files.pop(user_id) # ফাইলগুলো প্রসেস করে ডিকশনারি থেকে মুছে দিন
        
        # কনভার্সন প্রক্রিয়াটিকে অ্যাসিঙ্ক্রোনাস টাস্কে চালান
        asyncio.create_task(convert_and_stream(message, file_paths_to_process))
        return

    # 2. ভিডিও ফাইল হ্যান্ডলিং
    if message.document and message.document.mime_type.startswith("video/"):
        await message.reply_text("📥 ভিডিও ফাইলটি ডাউনলোড করা হচ্ছে...", quote=True)
        
        # অনন্য ও নিরাপদ ফোল্ডার তৈরি
        vid_id = str(uuid.uuid4())
        temp_dir = os.path.join(UPLOAD_FOLDER, vid_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        # নিরাপত্তা বাড়াতে র্যান্ডম ফাইল নাম ব্যবহার করুন
        safe_file_name = str(uuid.uuid4()) + "_" + message.document.file_name
        file_path = os.path.join(temp_dir, safe_file_name)
        
        # ফাইল ডাউনলোড
        await message.download(file_path)

        # ফাইলের তালিকা আপডেট করুন
        if user_id not in user_files:
            user_files[user_id] = []
        user_files[user_id].append(file_path)
        
        count = len(user_files[user_id])
        await message.reply_text(
            f"✅ {count}টি ফাইল যুক্ত হয়েছে। আরও পাঠাতে পারেন বা **ডান** লিখুন।",
            quote=True
        )
        return

    # 3. অন্যান্য মেসেজ হ্যান্ডলিং (যদি কনভার্সনের জন্য অপেক্ষা না করে)
    if user_id not in user_files or not user_files[user_id]:
        # যদি ব্যবহারকারী অন্য কিছু লিখে এবং কোনো ফাইল না থাকে, তাহলে স্টার্ট করার কথা বলুন।
        if not (message.text and message.text.lower() in ["ডান", "done"]):
             await message.reply_text("অনুগ্রহ করে একটি ভিডিও ফাইল বা **ডান** লিখুন।", quote=True)
    
# -----------------------------
# ফ্লাস্ক ওয়েব (Flask Web) - কোনো পরিবর্তন নেই
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
# বট + ফ্লাস্ক রান করুন
# -----------------------------
def run_bot():
    """Pyrogram ক্লায়েন্ট চালানোর জন্য একটি সহায়ক ফাংশন।"""
    # Pyrogram ক্লায়েন্ট রান করার জন্য এটি সঠিক উপায়
    try:
        bot.run()
    except Exception as e:
        print(f"Pyrogram Bot Error: {e}")

if __name__ == "__main__":
    # 1. বটকে একটি পৃথক থ্রেডে শুরু করুন (যাতে এটি ইনপুট হ্যান্ডেল করতে পারে)
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
    
    # 2. ফ্ল্যাস্ক সার্ভারকে মূল থ্রেডে শুরু করুন
    # এটি অবশ্যই 0.0.0.0 তে রান করতে হবে যাতে বাইরের থেকে অ্যাক্সেস করা যায়।
    app.run(host='0.0.0.0', port=5000)
