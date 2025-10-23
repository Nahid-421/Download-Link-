from flask import Flask, request, render_template_string, redirect, url_for, session, Response
import re
import requests
import base64 # URL এনকোডিং ও ডিকোডিংয়ের জন্য

app = Flask(__name__)
app.secret_key = "my_secret_key_123"

# ========== ADMIN LOGIN ========== #
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "12345"

# ========== SIMPLE HTML TEMPLATES (Unchanged) ========== #
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

# ========== DIRECT LINK GENERATOR LOGIC (Updated to generate Proxy URL) ========== #

def _get_final_external_link(url):
    """
    বিভিন্ন হোস্টিং সার্ভিস অনুযায়ী URL-কে আসল ডাইরেক্ট ডাউনলোড লিংকে পরিবর্তন করে।
    """
    # 1. Google Drive Link
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            # Google Drive এর uc?export=download আইডি ব্যবহার করা
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    # 2. Dropbox Link
    if "dropbox.com" in url:
        # নিশ্চিত করা যে লিংকে ?dl=1 প্যারামিটার আছে এবং ডোমেন dl.dropboxusercontent.com
        if "?dl=" not in url:
            url += "?dl=1"
        elif "?dl=0" in url:
            url = url.replace("?dl=0", "?dl=1")
        return url.replace("www.dropbox.com", "dl.dropboxusercontent.com")

    # 3. Mediafire Link (মিডিয়াফায়ারের সরাসরি ডাউনলোড লিংক পেতে সাধারণত স্ক্র্যাপিং লাগে।
    # তবে আমরা ধরে নিচ্ছি যে ইনপুট লিংকটি স্ট্রিম করার জন্য যথেষ্ট সহজ।)
    if "mediafire.com" in url:
        # এখানে কোনো সহজ স্ট্রিং পরিবর্তন না করে, আমরা সরাসরি প্রক্সি করব।
        pass

    # Default: যদি কোনো নির্দিষ্ট সার্ভিস না হয়, তাহলে ইনপুট URL-টিই ফেরত দেওয়া হবে।
    return url

def generate_proxy_link(url):
    """
    আসল ডাউনলোড URL-কে এনকোড করে আমাদের সার্ভারের প্রক্সি রুটের লিংক তৈরি করে।
    """
    final_external_url = _get_final_external_link(url)
    
    # URL-কে Base64 দিয়ে এনকোড করা
    encoded_url = base64.urlsafe_b64encode(final_external_url.encode()).decode()
    
    # প্রক্সি ডাউনলোড রুটের লিংক জেনারেট করা
    return url_for('proxy_download', encoded_url=encoded_url, _external=True)


# ========== NEW PROXY ROUTE: Handles Download Streaming ========== #
@app.route("/download/<encoded_url>")
def proxy_download(encoded_url):
    # 1. URL ডিকোড করা
    try:
        original_url = base64.urlsafe_b64decode(encoded_url.encode()).decode()
    except Exception:
        return "Invalid download link format or expired link.", 400

    # 2. আসল ফাইলটি রিকোয়েস্ট করা
    try:
        # stream=True ব্যবহার করা হয় যাতে ফাইলটি সরাসরি সার্ভারের মেমরিতে লোড না হয়ে স্ট্রিম হয়
        r = requests.get(original_url, stream=True, allow_redirects=True, timeout=30)
        r.raise_for_status() # HTTP ত্রুটি হলে (যেমন 404, 500) ValueError দেবে

        # 3. ফাইলের নাম নির্ণয় করা
        filename = "file_download" # Default name
        
        # Content-Disposition Header থেকে ফাইলের নাম নেওয়ার চেষ্টা
        if 'content-disposition' in r.headers:
            match = re.search(r'filename=["\']?(.+?)["\']?$', r.headers['content-disposition'])
            if match:
                filename = match.group(1).strip()
        
        # যদি ফাইলের নাম না পাওয়া যায়, তবে URL এর শেষ অংশ ব্যবহার করা
        if filename == "file_download":
            path_parts = original_url.split('/')
            if path_parts[-1]:
                filename = path_parts[-1].split('?')[0]
                if not filename:
                     filename = "downloaded_file"
        
        # 4. রেসপন্স হেডার সেট করা (সোর্স হাইড এবং ডাউনলোড ফোরসিং)
        headers = {
            'Content-Type': r.headers.get('content-type', 'application/octet-stream'),
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': r.headers.get('content-length'),
        }

        # 5. কন্টেন্ট স্ট্রিম করা (chunk by chunk)
        def generate():
            # 8kb করে ডেটা স্ট্রিম করা
            for chunk in r.iter_content(chunk_size=8192):
                yield chunk

        return Response(generate(), headers=headers)

    except requests.exceptions.RequestException as e:
        # রিকোয়েস্ট করতে সমস্যা হলে
        print(f"Proxy Error for {original_url}: {e}")
        return f"Error accessing external file: The source link may be invalid or down. Details: {e}", 500


# ========== ROUTES (Mostly Unchanged) ========== #

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
    # এখানে generate_proxy_link ব্যবহার করা হয়েছে
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
