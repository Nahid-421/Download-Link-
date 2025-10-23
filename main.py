from flask import Flask, request, render_template_string, redirect, url_for, session, Response
from werkzeug.middleware.proxy_fix import ProxyFix # HTTPS ফিক্স করার জন্য
import re
import requests
import base64

app = Flask(__name__)
# Production এনভায়রনমেন্টে সিকিউরিটি নিশ্চিত করার জন্য ProxyFix ব্যবহার করা জরুরি
# এটি সার্ভারকে বুঝতে সাহায্য করে যে এটি একটি রিভার্স প্রক্সি (যেমন রেন্ডার) এর পিছনে চলছে
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

app.secret_key = "my_secret_key_123"

# ========== ADMIN LOGIN ========== #
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "12345"

# [ login_page এবং admin_panel টেমপ্লেট অপরিবর্তিত থাকবে ]

# ========== SIMPLE HTML TEMPLATES (Unchanged for brevity, assume they are here) ========== #
login_page = """...""" # (আপনার আগের কোড থেকে যোগ করুন)
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


# ========== DIRECT LINK GENERATOR LOGIC (Updated) ========== #

def _get_final_external_link(url):
    # Google Drive, Dropbox ইত্যাদির জন্য আসল ডাইরেক্ট লিংক তৈরি করা
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    if "dropbox.com" in url:
        if "?dl=" not in url:
            url += "?dl=1"
        elif "?dl=0" in url:
            url = url.replace("?dl=0", "?dl=1")
        return url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
    return url

def generate_proxy_link(url):
    final_external_url = _get_final_external_link(url)
    
    # URL-কে Base64 দিয়ে এনকোড করা
    encoded_url = base64.urlsafe_b64encode(final_external_url.encode()).decode()
    
    # HTTPS স্কিম জোর করে ব্যবহার করা, যাতে ব্রাউজারের "Insecure Download" ওয়ার্নিং না আসে
    return url_for('proxy_download', encoded_url=encoded_url, _external=True, _scheme='https')


# ========== PROXY ROUTE: Handles Download Streaming (Updated with User-Agent) ========== #
@app.route("/download/<encoded_url>")
def proxy_download(encoded_url):
    try:
        original_url = base64.urlsafe_b64decode(encoded_url.encode()).decode()
    except Exception:
        return "Invalid download link format.", 400

    # শক্তিশালী হেডার ব্যবহার করা, যাতে সোর্স সার্ভার এটিকে বট মনে করে ব্লক না করে
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        r = requests.get(original_url, stream=True, allow_redirects=True, timeout=60, headers=headers)
        r.raise_for_status()

        # 1. ফাইলের নাম নির্ধারণ করা
        filename = "downloaded_file"
        
        # Content-Disposition থেকে নাম নেওয়ার চেষ্টা
        if 'content-disposition' in r.headers:
            match = re.search(r'filename=["\']?(.+?)["\']?$', r.headers['content-disposition'])
            if match:
                # ডিকোড করে সঠিক ফাইলনাম নেওয়া
                try:
                    filename = match.group(1).encode('latin-1').decode('utf-8')
                except:
                    filename = match.group(1).strip()
        
        # যদি নাম না পাওয়া যায়, তবে URL এর শেষ অংশ ব্যবহার করা
        if filename == "downloaded_file":
            path_parts = original_url.split('/')
            temp_name = path_parts[-1].split('?')[0]
            if temp_name:
                filename = temp_name
        
        # 2. রেসপন্স হেডার সেট করা
        response_headers = {
            # Content-Type যদি সোর্স থেকে পাওয়া না যায়, তবে ডিফল্ট binary টাইপ ব্যবহার
            'Content-Type': r.headers.get('content-type', 'application/octet-stream'), 
            # এই হেডারটি ব্রাউজারকে ডাউনলোড শুরু করতে বাধ্য করে
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': r.headers.get('content-length'),
            # Cache Control headers যোগ করা যাতে দ্রুত ডাউনলোড হয়
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
        }
        
        # 3. কন্টেন্ট স্ট্রিম করা
        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                yield chunk

        return Response(generate(), headers=response_headers)

    except requests.exceptions.RequestException as e:
        print(f"Proxy Error: {e}")
        return f"Error accessing external file. Source might be down or restricted: {e}", 500


# ========== ROUTES (Unchanged) ========== #

@app.route("/")
def home():
    if "logged_in" in session:
        return redirect(url_for("admin"))
    return render_template_string(login_page)

@app.route("/login", methods=["POST"])
def login():
    # ... (login logic)
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
    # DEBUG=True মোডে চালালে, রেন্ডার বা অন্যান্য হোস্টিং প্ল্যাটফর্মে এটি 10000 পোর্টে চলবে।
    # লোকাল টেস্টের জন্য, আপনি host="127.0.0.1", port=5000 ব্যবহার করতে পারেন।
    app.run(host="0.0.0.0", port=10000, debug=True)
