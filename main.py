# ... (Imports and boilerplate code remain the same) ...
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

# [ Templates are here ]
login_page = "..."
admin_panel = "..."

# [ _get_final_external_link and generate_proxy_link remain the same ]

def _get_final_external_link(url):
    # Google Drive Link
    if "drive.google.com" in url:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            file_id = match.group(1)
            return f"gdrive:{file_id}" 
    # Dropbox Link
    if "dropbox.com" in url:
        if "?dl=" not in url: url += "?dl=1"
        elif "?dl=0" in url: url = url.replace("?dl=0", "?dl=1")
        return url.replace("www.dropbox.com", "dl.dropboxusercontent.com")
    return url

def generate_proxy_link(url):
    final_external_url = _get_final_external_link(url)
    encoded_url = base64.urlsafe_b64encode(final_external_url.encode()).decode()
    return url_for('proxy_download', encoded_url=encoded_url, _external=True, _scheme='https')


# ========== PROXY ROUTE: Handles Download Streaming (Session Use Fix) ========== #
@app.route("/download/<encoded_url>")
def proxy_download(encoded_url):
    try:
        original_url_tag = base64.urlsafe_b64decode(encoded_url.encode()).decode()
    except Exception:
        return "Invalid download link format.", 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.google.com/',
        'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8'
    }
    
    original_url = original_url_tag 

    # requests.Session() ব্যবহার করা
    with requests.Session() as session:
        session.headers.update(headers)
        
        # === Google Drive স্পেশাল হ্যান্ডলিং ===
        if original_url_tag.startswith("gdrive:"):
            file_id = original_url_tag.split(":")[1]
            original_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            
            try:
                # 1. প্রথম রিকোয়েস্ট
                r = session.get(original_url, stream=True, allow_redirects=True, timeout=15)
                r.raise_for_status()
                
                # 2. টোকেন খোঁজা
                match = re.search(r"confirm=([0-9A-Za-z_-]+)", r.text)
                
                if match:
                    # টোকেন পাওয়া গেলে, URL পরিবর্তন করা 
                    confirm_token = match.group(1)
                    final_download_url = f"{original_url}&confirm={confirm_token}"
                    
                    # 3. কনফার্মেশন টোকেন দিয়ে দ্বিতীয় রিকোয়েস্ট (Session নিজেই কুকি ম্যানেজ করবে)
                    r = session.get(final_download_url, 
                                     stream=True, 
                                     allow_redirects=True, 
                                     timeout=60) 
                    r.raise_for_status()

                # কন্টেন্ট টাইপ চেক: যদি এটি এখনও ছোট HTML পেজ হয়, তবে ত্রুটি দেখাও
                content_type = r.headers.get('Content-Type', '').lower()
                content_length = r.headers.get('Content-Length')

                # যদি এটি text/html হয় এবং সাইজ খুব ছোট হয় (50kb এর কম), তবে ব্যর্থ
                if 'text/html' in content_type and (content_length is None or int(content_length) < 50000):
                     print(f"FAILED: Google returned small HTML page for ID: {file_id}")
                     return f"Download failed: Google Drive returned an unexpected page instead of the file stream. ID: {file_id}", 500

                original_response = r
                
            except requests.exceptions.RequestException as e:
                print(f"Google Drive Error: {e}")
                return f"Error accessing Google Drive file. Source might be down or restricted: {e}", 500
                
        # === অন্যান্য ফাইল হ্যান্ডলিং ===
        else:
            # নন-Google Drive URL
            original_url = original_url_tag
            try:
                original_response = session.get(original_url, stream=True, allow_redirects=True, timeout=60)
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
                filename = name_match.group(1).encode('latin-1').decode('utf-8')
            except:
                filename = name_match.group(1).strip()
    
    # যদি নাম না পাওয়া যায়
    if filename == "downloaded_file.bin" and original_url:
        path_parts = original_url.split('/')
        temp_name = path_parts[-1].split('?')[0]
        if temp_name:
            filename = temp_name
    
    
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
