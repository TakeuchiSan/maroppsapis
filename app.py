from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__)
CORS(app)

SPOTIFY_HEADERS = {
    'authority': 'spotdown.org',
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
    'referer': 'https://spotdown.org/search',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
}

TIKTOK_HEADERS = {
    'authority': 'ttsave.app',
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
    'content-type': 'application/json',
    'origin': 'https://ttsave.app',
    'referer': 'https://ttsave.app/en',
    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Mobile Safari/537.36',
}

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "Active",
        "endpoints": {
            "tiktok": "/ttdown/download",
            "mp3_search": "/mp3down/search",
            "mp3_download": "/mp3down/download"
        }
    })

@app.route('/ttdown/download', methods=['GET', 'POST'])
def tiktok_download():
    try:
        url = request.args.get('url')
        if not url:
            body = request.get_json(silent=True)
            if body and 'url' in body:
                url = body['url']

        if not url:
            return jsonify({"status": "error", "message": "URL parameter required"}), 400
            
        data = {
           'query': url,
           'language_id': '1',
        }

        session = requests.Session()
        req = session.post('https://ttsave.app/download', headers=TIKTOK_HEADERS, json=data)
        
        if req.status_code != 200:
            return jsonify({"status": "error", "message": "Provider unavailable"}), 400

        soup = BeautifulSoup(req.text, 'html.parser')
        
        result = {
            "platform": "tiktok",
            "type": "unknown",
            "video": None,
            "audio": None,
            "slides": []
        }

        video_links = []

        # LOGIC BARU: Parsing lebih rapi untuk mendapatkan No Watermark
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href:
                continue
            
            raw_html = str(a)

            if 'video_mp4' in raw_html or ('nwm' in href and '.mp4' in href):
                # Kumpulkan semua link video
                video_links.append(href)
                result['type'] = "video"
            elif '.mp3' in href:
                result['audio'] = href
            elif 'slide' in href or 'image' in href or '.jpg' in href:
                if href not in result['slides']:
                    result['slides'].append(href)
                    result['type'] = "slide"

        # Ttsave biasanya menaruh link No Watermark di urutan pertama (index 0)
        if video_links:
            result['video'] = video_links[0]

        return jsonify({
            "status": "success",
            "data": result
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mp3down/search', methods=['GET'])
def music_search():
    query = request.args.get('q')
    
    if not query:
        return jsonify({"error": "Parameter 'q' required"}), 400

    try:
        session = requests.Session()
        params = {'url': query}
        
        response = session.get(
            'https://spotdown.org/api/song-details', 
            params=params, 
            headers=SPOTIFY_HEADERS
        )
        
        if response.status_code != 200:
             return jsonify({"error": "Provider unavailable"}), 502
        
        data = response.json()
        
        if 'songs' not in data or not data['songs']:
            return jsonify({"message": "No songs found", "data": []}), 404

        results = []
        base_url = request.host_url.rstrip('/')

        for item in data['songs']:
            raw_url = item.get('url')
            raw_title = item.get('title')
            raw_artist = item.get('artist')
            
            # Membuat link download internal
            dl_link = (
                f"{base_url}/mp3down/download"
                f"?url={raw_url}"
                f"&title={raw_title}"
                f"&artist={raw_artist}"
            )

            results.append({
                "title": raw_title,
                "artist": raw_artist,
                "duration": item.get('duration'),
                "thumbnail": item.get('thumbnail'),
                "download_url": dl_link
            })

        return jsonify({"status": "success", "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/mp3down/download', methods=['GET'])
def music_download():
    target_url = request.args.get('url')
    raw_title = request.args.get('title', 'Unknown Title')
    raw_artist = request.args.get('artist', 'Unknown Artist')
    
    if not target_url:
        return jsonify({"error": "Parameter 'url' required"}), 400

    try:
        session = requests.Session()
        
        check_params = {'url': target_url}
        session.get(
            'https://spotdown.org/api/check-direct-download', 
            params=check_params, 
            headers=SPOTIFY_HEADERS
        )

        json_data = {'url': target_url}
        req_file = session.post(
            'https://spotdown.org/api/download', 
            headers=SPOTIFY_HEADERS, 
            json=json_data,
            stream=True
        )

        clean_title = sanitize_filename(raw_title)
        clean_artist = sanitize_filename(raw_artist)
        filename = f"{clean_title} - {clean_artist}.mp3"

        response_headers = {
            'Content-Type': 'audio/mpeg',
            'Content-Disposition': f'attachment; filename="{filename}"',
        }

        def generate():
            for chunk in req_file.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk

        return Response(stream_with_context(generate()), headers=response_headers)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Menjalankan di port 5000
    app.run(debug=True, port=5000)
