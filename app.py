#!/usr/bin/env python3
"""
Simple Flask web UI for youtube_cutter.py.
Allows entering pause, fade, and segment triples, runs the cutter,
and serves the resulting output file for download.
"""
import os
import uuid
import subprocess
from flask import Flask, render_template, request, send_from_directory

# Create outputs directory
OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), 'outputs')
os.makedirs(OUTPUT_ROOT, exist_ok=True)

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def index():
    logs = None
    download_url = None
    if request.method == 'POST':
        pause = request.form.get('pause', '').strip()
        fade = request.form.get('fade', '').strip()
        segments_text = request.form.get('segments', '').strip().splitlines()

        # Build args list
        args = [pause, fade]
        for line in segments_text:
            parts = line.strip().split()
            if len(parts) == 3:
                args.extend(parts)

        # Prepare output directory
        job_id = uuid.uuid4().hex
        out_dir = os.path.join(OUTPUT_ROOT, job_id)
        os.makedirs(out_dir, exist_ok=True)
        out_base = os.path.join(out_dir, 'output')

        # Invoke youtube_cutter script
        cmd = ['python3', 'youtube_cutter.py'] + args + ['-o', out_base]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        logs, _ = proc.communicate()

        # Determine output file name
        files = os.listdir(out_dir)
        if files:
            download_url = f'/download/{job_id}/{files[0]}'

    return render_template('index.html', logs=logs, download_url=download_url)


@app.route('/download/<job_id>/<filename>')
def download(job_id, filename):
    dirpath = os.path.join(OUTPUT_ROOT, job_id)
    return send_from_directory(dirpath, filename, as_attachment=True)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8020, debug=True)
