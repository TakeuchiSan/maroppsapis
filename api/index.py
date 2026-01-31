from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import time

app = Flask(__name__)
CORS(app)

# Headers untuk meniru browser
SPOTIFY_HEADERS = {
    'authority': 'spotdown.org',
    'accept': 'application/json, text/plain, */*',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://spotdown.org/'
}

TIKTOK_HEADERS = {
    'authority': 'ttsave.app',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://ttsave.app/'
}

def sanitize_filename(name):
    # Membersihkan nama file dari karakter aneh
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    return clean[:50]  # Batasi panjang nama file

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "Online",
        "message": "Maroppp Project Server Proxy is Running",
        "version": "3.1"
    })

# --- GENERIC STREAMER (INTI DARI FITUR PROFESIONAL) ---
@app.route('/stream_content', methods=['GET'])
def stream_content():
    """
    Endpoint ini bertindak sebagai 'Jembatan'.
    Server mendownload file -> Server kirim ke User.
    User tidak melihat URL asli.
    """
    file_url = request.args.get('url')
    filename = request.args.get('filename', f'download_{int(time.time())}')
    file_type = request.args.get('type', 'mp4') # mp4 atau mp3

    if not file_url:
        return jsonify({"error": "URL parameter required"}), 400

    try:
        # Tentukan headers berdasarkan domain source
        req_headers = TIKTOK_HEADERS if 'tiktok' in file_url or 'ttsave' in file_url else SPOTIFY_HEADERS
        
        # Request stream (download bertahap)
        req = requests.get(file_url, headers=req_headers, stream=True)
        
        # Tentukan Content-Type
        content_type = 'video/mp4' if file_type == 'video' else 'audio/mpeg'
        if file_type == 'image': content_type = 'image/jpeg'

        # Nama file final
        final_filename = f"{sanitize_filename(filename)}.{'mp4' if file_type == 'video' else 'mp3'}"
        if file_type == 'image': final_filename = f"{sanitize_filename(filename)}.jpg"

        # Headers response ke user
        response_headers = {
            'Content-Type': content_type,
            'Content-Disposition': f'attachment; filename="{final_filename}"',
            'Cache-Control': 'no-cache'
        }

        # Fungsi generator untuk streaming data (hemat RAM server)
        def generate():
            for chunk in req.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk

        return Response(stream_with_context(generate()), headers=response_headers)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- TIKTOK ENDPOINTS ---
@app.route('/ttdown/download', methods=['POST'])
def tiktok_download():
    try:
        body = request.get_json(silent=True)
        url = body.get('url') if body else request.args.get('url')

        if not url:
            return jsonify({"status": "error", "message": "URL required"}), 400
            
        data = {'query': url, 'language_id': '1'}
        
        session = requests.Session()
        req = session.post('https://ttsave.app/download', headers=TIKTOK_HEADERS, json=data)
        
        if req.status_code != 200:
            return jsonify({"status": "error", "message": "Gagal menghubungi provider"}), 400

        soup = BeautifulSoup(req.text, 'html.parser')
        result = {"platform": "tiktok", "type": "unknown", "video": None, "audio": None, "slides": [], "cover": None, "author": "MaropppUser"}

        # Ambil Username (Opsional untuk nama file)
        user_tag = soup.find('h2')
        if user_tag: result['author'] = user_tag.text.strip()

        video_links = []
        for a in soup.find_all('a'):
            href = a.get('href', '')
            if 'video_mp4' in str(a) or ('nwm' in href and '.mp4' in href):
                video_links.append(href)
                result['type'] = "video"
            elif '.mp3' in href:
                result['audio'] = href
            elif 'slide' in href or 'image' in href or '.jpg' in href:
                if href not in result['slides']:
                    result['slides'].append(href)
                    result['type'] = "slide"
        
        if video_links: result['video'] = video_links[0]

        return jsonify({"status": "success", "data": result})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --- SPOTIFY ENDPOINTS ---
@app.route('/mp3down/search', methods=['GET'])
def music_search():
    query = request.args.get('q')
    if not query: return jsonify({"error": "Query required"}), 400

    try:
        session = requests.Session()
        resp = session.get('https://spotdown.org/api/song-details', params={'url': query}, headers=SPOTIFY_HEADERS)
        data = resp.json()
        
        if 'songs' not in data or not data['songs']:
            return jsonify({"message": "Not found", "data": []}), 404

        results = []
        base_url = request.host_url.rstrip('/')

        for item in data['songs']:
            # Kita tidak membuat link download di sini, tapi di frontend
            # Kita kirim raw_url ke frontend, frontend yang request ke /stream_content
            
            # Khusus Spotdown, kita butuh step tambahan untuk dapat direct link
            # Jadi kita arahkan ke endpoint internal khusus prepare
            results.append({
                "title": item.get('title'),
                "artist": item.get('artist'),
                "duration": item.get('duration'),
                "thumbnail": item.get('thumbnail'),
                "original_url": item.get('url') # Link spotify asli
            })

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/mp3down/get_link', methods=['POST'])
def music_get_direct_link():
    # Helper untuk mendapatkan direct link audio dari spotdown sebelum di stream
    body = request.get_json()
    url = body.get('url')
    
    try:
        session = requests.Session()
        session.get('https://spotdown.org/api/check-direct-download', params={'url': url}, headers=SPOTIFY_HEADERS)
        req_file = session.post('https://spotdown.org/api/download', headers=SPOTIFY_HEADERS, json={'url': url}, stream=True)
        
        # Spotdown kadang mereturn JSON error, kadang stream langsung
        # Karena kita mau stream via /stream_content, kita butuh URL finalnya.
        # Sayangnya spotdown post-request langsung return file blob.
        # Jadi untuk spotify, kita pakai metode pass-through stream langsung di sini.
        
        def generate():
            for chunk in req_file.iter_content(chunk_size=4096):
                if chunk: yield chunk

        filename = f"Music_{int(time.time())}.mp3"
        return Response(stream_with_context(generate()), headers={
            'Content-Type': 'audio/mpeg',
            'Content-Disposition': f'attachment; filename="{filename}"'
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
