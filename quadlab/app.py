import hashlib
import random
import socket
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from solver import solve

app = Flask(__name__)
HOSTNAME = socket.gethostname()


@app.get('/')
def index():
    return app.send_static_file('index.html')


@app.get('/health')
def health():
    return jsonify(status='ok', hostname=HOSTNAME)


@app.get('/api/solve')
def equation():
    # Optional synthetic CPU work. Plain /api/solve has no extra work.
    try:
        work = int(request.args.get('work', '0'))
        if not 0 <= work <= 1000000:
            raise ValueError
    except ValueError:
        return jsonify(error='work must be an integer between 0 and 1000000'), 400
    if work:
        hashlib.pbkdf2_hmac('sha256', b'quadratic-lab', b'synthetic-work', work)
    a = random.choice([x for x in range(-10, 11) if x != 0])
    b, c = random.randint(-10, 10), random.randint(-10, 10)
    d, case, roots = solve(a, b, c)
    return jsonify(timestamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                   a=a, b=b, c=c, discriminant=d, case=case, roots=roots,
                   hostname=HOSTNAME, ip=socket.gethostbyname(HOSTNAME), work=work)


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Backend-Hostname'] = HOSTNAME
    return response
