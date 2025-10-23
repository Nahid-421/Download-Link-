from flask import Flask, request, render_template_string, redirect, url_for, session, Response
from werkzeug.middleware.proxy_fix import ProxyFix
import re
import requests
import base64
import time

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)
app.secret_key = "my_secret_key_123"

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


# ========== CORE FUNCTIONALITY: Google Drive Direct Download Fix (Unchanged) ========== #

def _get_final_external_link(url):
    # Google Drive Link
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            return f"gdrive:{file_id}" 

    # Dropbox Link
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
    return url_for('proxy_download', encoded_url=encoded_url, _external=True, _scheme='https')


# ========== PROXY ROUTE: Handles Download Streaming (FINAL FIX) ========== #
@app.route("/download/<encoded_url>")
def proxy_download(encoded_url):
    try:
        original_url_tag = base64.urlsafe_b64decode(encoded_url.encode()).decode()
    except Exception:
        return "Invalid download link format.", 400

    # কমন রিকোয়েস্ট হেডার
    headers = {
        # ব্রাউজারের মতো দেখতে শক্তিশালী User-Agent
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/', # রেফারার সেট করা
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8'
    }
    
    original_url = original_url_tag # ডিফল্ট ইউআরএল

    # === Google Drive স্পেশাল হ্যান্ডলিং ===
    if original_url_tag.startswith("gdrive:"):
        file_id = original_url_tag.split(":")[1]
        original_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        
        try:
            # 1. প্রথম রিকোয়েস্ট: কনফার্মেশন টোকেন খোঁজা
            r = requests.get(original_url, stream=True, allow_redirects=True, timeout=15, headers=headers)
            r.raise_for_status()
            
            # টোকেন খোঁজা
            match = re.search(r"confirm=([0-9A-Za-z_-]+)", r.text)
            
            if match:
                # টোকেন পাওয়া গেলে, URL পরিবর্তন করা (ভাইরাস স্ক্যান বাইপাস)
                confirm_token = match.group(1)
                final_download_url = f"{original_url}&confirm={confirm_token}"
                
                # 2. কনফার্মেশন টোকেন ও কুকিজ সহ দ্বিতীয় রিকোয়েস্ট
                r = requests.get(final_download_url, 
                                 stream=True, 
                                 allow_redirects=True, 
                                 timeout=60, 
                                 headers=headers, 
                                 cookies=r.cookies) 
                
                r.raise_for_status()

            # পরীক্ষা করা যে আমরা নিশ্চিতভাবে কোনো HTML পেজ পাচ্ছি না
            content_type = r.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type and r.headers.get('Content-Length') is not None and int(r.headers.get('Content-Length')) < 10000:
                 # যদি ছোট HTML পেজ পাওয়া যায়, তবে এটি ব্যর্থ
                 return f"Download failed: Google Drive returned an unexpected page instead of the file stream. ID: {file_id}", 500

            original_response = r
            
        except requests.exceptions.RequestException as e:
            print(f"Google Drive Error: {e}")
            return f"Error accessing Google Drive file. Source might be down or restricted: {e}", 500
            
        
    # === অন্যান্য ফাইল (Dropbox, Mediafire, etc.) হ্যান্ডলিং ===
    else:
        # এটা নন-Google Drive URL
        original_url = original_url_tag
        try:
            original_response = requests.get(original_url, stream=True, allow_redirects=True, timeout=60, headers=headers)
            original_response.raise_for_status()
        
        except requests.exceptions.RequestException as e:
            print(f"General Proxy Error: {e}")
            return f"Error accessing external file. Source might be down or restricted: {e}", 500

    
    # === রেসপন্স স্ট্রিম করা এবং হেডার সেট করা ===
    
    r = original_response
    
    # ফাইলের নাম নির্ধারণ
    filename = "downloaded_file.bin"
    if 'content-disposition' in r.headers:
        name_match = re.search(r'filename=["\']?(.+?)["\']?$', r.headers['content-disposition'])
        if name_match:
            try:
                # ফাইলনাম ডিকোড করা (বাংলা বা অন্য ভাষার নাম থাকলে)
                filename = name_match.group(1).encode('latin-1').decode('utf-8')
            except:
                filename = name_match.group(1).strip()
    
    # যদি নাম না পাওয়া যায়, URL এর শেষ অংশ ব্যবহার করা
    if filename == "downloaded_file.bin" and original_url:
        path_parts = original_url.split('/')
        temp_name = path_parts[-1].split('?')[0]
        if temp_name:
            filename = temp_name
    
    
    response_headers = {
        'Content-Type': r.headers.get('content-type', 'application/octet-stream'), 
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Content-Length': r.headers.get('content-length'),
        # Cache Control headers
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
