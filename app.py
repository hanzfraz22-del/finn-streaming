import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))
sys.path.insert(0, os.path.join(BASE_DIR, 'MeinStreamingProjekt'))

from MeinStreamingProjekt.backend import app
from waitress import serve

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"Starte Finn Streaming auf Port {port}...")
    serve(app, host='0.0.0.0', port=port, threads=12)
