from flask import Flask, request, render_template_string, redirect, url_for, session, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import re
import requests
import base64
import time

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

app.secret_key = "my_secret_key_123"

# ========== ADMIN LOGIN (Unchanged) ========== #
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "12345"

# [ login_page and admin_panel templates remain the same ]
# (আপনার আগের কোড থেকে টেমপ্লেট দুটি যুক্ত করে দিন)

login_page = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Login</title>
  <style>
    body {font-family: Arial; background: #121212; color: white; text-align: center;}
    form {margin-top: 150px;}
    input {padding: 10px; margin: 5px; border-radius: 5px;}
    button {padding: 10px 20px; border: none; background: #007bff; color: white; border-radius: 5px;}
  </style>
</head>
<body>
  <h2>🔐 Admin Login</h2>
  <form method="post" action="/login">
    <input type="text" name="username" placeholder="Username" required><br>
    <input type="password" name="password" placeholder="Password" required><br>
    <button type="submit">Login</button>
  </form>
</body>
</html>
"""

admin_panel = """
<!DOCTYPE html>
<html>
<head>
  <title>Admin Panel</title>
  <style>
    body {font-family: Arial; background: #121212; color: white; text-align: center;}
    input {padding: 10px; width: 50%; margin: 10px; border-radius: 5px;}
    button {padding: 10px 20px; border: none; background: #28a745; color: white; border-radius: 5px;}
    a {color: #ff4757; text-decoration: none;}
    .link-container { word-break: break-all; margin: 20px 10%; border: 1px solid #333; padding: 15px; background: #1e1e1e; border-radius: 5px;}
  </style>
</head>
<body>
  <h2>⚙️ Direct Link Generator</h2>
  <form method="post" action="/generate">
    <input type="text" name="url" placeholder="Enter your link here..." required><br>
    <button type="submit">Generate Direct Link</button>
  </form>
  {% if link %}
    <h3>✅ Proxy Download Link:</h3>
    <div class="link-container">
        <a href="{{ link }}" target="_blank">{{ link }}</a>
    </div>
    <p style="color: #ccc; font-size: 14px;">(এই লিংকটি আপনার সার্ভারের মাধ্যমে ফাইল স্ট্রিম করবে, ফলে সোর্স হাইড থাকবে)</p>
  {% endif %}
  <br><a href="/logout">Logout</a>
</body>
</html>
"""


# ========== CORE FUNCTIONALITY: Google Drive Direct Download Fix ========== #

def _get_final_external_link(url):
    """
    বিভিন্ন হোস্টিং সার্ভিস অনুযায়ী URL-কে আসল ডাইরেক্ট ডাউনলোড লিংকে পরিবর্তন করে।
    """
    # 1. Google Drive Link
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            # Google Drive-এর জন্য আমরা শুধুমাত্র ফাইল আইডি পাঠাবো,
            # এবং নিশ্চিত ডাইরেক্ট লিংক পাওয়ার কাজটি প্রক্সি ফাংশনে (proxy_download) করব।
            return f"gdrive:{file_id}" 

    # 2. Dropbox Link
    if "dropbox.com" in url:
        if "?dl=" not in url:
            url += "?dl=1"
        elif "?dl=0" in url:
            url = url.replace("?dl=0", "?dl=1")
        return url.replace("www.dropbox.com", "dl.dropboxusercontent.com")

    # Default
    return url

def generate_proxy_link(url):
    final_external_url = _get_final_external_link(url)
    encoded_url = base64.urlsafe_b64encode(final_external_url.encode()).decode()
    
    # HTTPS স্কিম জোর করে ব্যবহার করা
    return url_for('proxy_download', encoded_url=encoded_url, _external=True, _scheme='https')


# ========== PROXY ROUTE: Handles Download Streaming (MAJOR UPDATE) ========== #
@app.route("/download/<encoded_url>")
def proxy_download(encoded_url):
    try:
        original_url_tag = base64.urlsafe_b64decode(encoded_url.encode()).decode()
    except Exception:
        return "Invalid download link format.", 400

    # কমন রিকোয়েস্ট হেডার
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # === Google Drive স্পেশাল হ্যান্ডলিং ===
    if original_url_tag.startswith("gdrive:"):
        file_id = original_url_tag.split(":")[1]
        
        # 1. ডাইরেক্ট ডাউনলোড URL তৈরি
        gdrive_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        try:
            # 2. প্রথম রিকোয়েস্ট পাঠানো: এটি কনফার্মেশন পেজ নিয়ে আসে
            r = requests.get(gdrive_url, stream=True, allow_redirects=True, timeout=15, headers=headers)
            r.raise_for_status()
            
            # 3. টোকেন খোঁজা: যদি ভাইরাস স্ক্যান ওয়ার্নিং আসে, তবে টোকেন বের করা
            match = re.search(r"confirm=([0-9A-Za-z_-]+)", r.text)
            
            if match:
                # টোকেন পাওয়া গেলে, URL পরিবর্তন করা (ভাইরাস স্ক্যান বাইপাস)
                confirm_token = match.group(1)
                final_download_url = f"{gdrive_url}&confirm={confirm_token}"
                
                # 4. কনফার্মেশন টোকেন দিয়ে দ্বিতীয় রিকোয়েস্ট পাঠানো
                # এখানে কুকিজ সেট করা জরুরি, যাতে গুগল বুঝতে পারে যে কনফার্ম করা হয়েছে।
                r = requests.get(final_download_url, 
                                 stream=True, 
                                 allow_redirects=True, 
                                 timeout=60, 
                                 headers=headers, 
                                 cookies=r.cookies) # আগের রিকোয়েস্টের কুকিজ ব্যবহার করা
                
                r.raise_for_status()
                
            # যদি ম্যাচ না করে, তবে ফাইলটি ছোট ছিল বা সরাসরি ডাউনলোড শুরু হয়ে গেছে (প্রথম রিকোয়েস্টের রেসপন্স r ব্যবহার করা হবে)
            
            # ফাইলের নাম বের করা (Content-Disposition থেকে)
            filename = "downloaded_file.bin"
            if 'content-disposition' in r.headers:
                name_match = re.search(r'filename=["\']?(.+?)["\']?$', r.headers['content-disposition'])
                if name_match:
                    try:
                        filename = name_match.group(1).encode('latin-1').decode('utf-8')
                    except:
                        filename = name_match.group(1).strip()
            
            original_response = r
            
        except requests.exceptions.RequestException as e:
            print(f"Google Drive Error: {e}")
            return f"Error accessing Google Drive file. Source might be down or restricted: {e}", 500
            
        original_url = "Google Drive File" # শুধু লগের জন্য

    # === অন্যান্য ফাইল (Dropbox, Mediafire, etc.) হ্যান্ডলিং ===
    else:
        # এটা নন-Google Drive URL
        try:
            original_response = requests.get(original_url_tag, stream=True, allow_redirects=True, timeout=60, headers=headers)
            original_response.raise_for_status()
            
            # ফাইলের নাম নির্ধারণ
            filename = "downloaded_file.bin"
            if 'content-disposition' in original_response.headers:
                name_match = re.search(r'filename=["\']?(.+?)["\']?$', original_response.headers['content-disposition'])
                if name_match:
                    try:
                        filename = name_match.group(1).encode('latin-1').decode('utf-8')
                    except:
                        filename = name_match.group(1).strip()
            
            # যদি নাম না পাওয়া যায়, তবে URL এর শেষ অংশ ব্যবহার করা
            if filename == "downloaded_file.bin":
                path_parts = original_url_tag.split('/')
                temp_name = path_parts[-1].split('?')[0]
                if temp_name:
                    filename = temp_name
        
        except requests.exceptions.RequestException as e:
            print(f"General Proxy Error: {e}")
            return f"Error accessing external file. Source might be down or restricted: {e}", 500

    # === রেসপন্স স্ট্রিম করা ===
    
    r = original_response
    
    response_headers = {
        'Content-Type': r.headers.get('content-type', 'application/octet-stream'), 
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Length': r.headers.get('content-length'),
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
    }
    
    def generate():
        for chunk in r.iter_content(chunk_size=8192):
            yield chunk

    return Response(generate(), headers=response_headers)


# [ROUTES: /, /login, /admin, /generate, /logout, /health অপরিবর্তিত]

@app.route("/")
def home():
    if "logged_in" in session:
        return redirect(url_for("admin"))
    return render_template_string(login_page)

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["logged_in"] = True
        return redirect(url_for("admin"))
    return "<h3 style='color:red;'>❌ Wrong username or password</h3><a href='/'>Go Back</a>"

@app.route("/admin")
def admin():
    if "logged_in" not in session:
        return redirect("/")
    return render_template_string(admin_panel)

@app.route("/generate", methods=["POST"])
def generate():
    if "logged_in" not in session:
        return redirect("/")
    url = request.form.get("url")
    link = generate_proxy_link(url)
    return render_template_string(admin_panel, link=link)

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/")

@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
