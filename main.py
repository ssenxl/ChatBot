import os
from dotenv import load_dotenv
load_dotenv()

from chatbot_app import app


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(debug=debug, host='0.0.0.0', port=5000, use_reloader=False)
