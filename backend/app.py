from flask import Flask, jsonify, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
import os
from dotenv import load_dotenv
import logging
import uuid
from flask_cors import CORS

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")  # Use a secure key

# Enable CORS for your Flask app
CORS(app, supports_credentials=True, origins=["https://guillermos-amazing-site-b0c75a.webflow.io"])


# Fetch credentials from environment variables
LWA_APP_ID = os.getenv("LWA_APP_ID")
LWA_CLIENT_SECRET = os.getenv("LWA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
DATABASE_URL = os.getenv("DATABASE_URL")  # Use DATABASE_URL provided by Render

# Ensure critical credentials are available
if not LWA_APP_ID or not LWA_CLIENT_SECRET or not REDIRECT_URI:
    raise Exception("Amazon SP-API credentials are missing. Check your environment variables.")

if not DATABASE_URL:
    raise Exception("Database URL is missing. Ensure DATABASE_URL is set in your environment variables.")

# Flask application setup
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_NAME'] = 'session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_NAME'] = 'session'  # Explicitly name the session cookie


# Initialize the SQLAlchemy instance globally
db = SQLAlchemy()

# Bind the SQLAlchemy instance to the app
db.init_app(app)

# Initialize database tables
with app.app_context():
    db.create_all()

# Define database models
class AmazonSeller(db.Model):
    __tablename__ = "amazon_sellers"

    id = db.Column(db.Integer, primary_key=True)
    selling_partner_id = db.Column(db.String(255), unique=True, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Utility function to generate a unique state
def generate_state():
    return str(uuid.uuid4())

# Start OAuth Flow
@app.route('/start-oauth', methods=['GET'])
def start_oauth():
    try:
        # Generate a unique state value
        state = generate_state()
        session['oauth_state'] = state  # Store state in session

      # Log the generated state and session state for debugging  
        logging.debug(f"Generated state: {state}")
        logging.debug(f"Session state stored: {session['oauth_state']}")

        # Construct the authorization URL
        amazon_auth_url = (
            f"https://sellercentral.amazon.com.mx/apps/authorize/consent"
            f"?application_id={LWA_APP_ID}"
            f"&state={state}"            # Use the dynamically generated state
            f"&version=beta"             # Add version parameter
            f"&redirect_uri={REDIRECT_URI}"
        )

      # Log the authorization URL
        logging.debug(f"Generated OAuth URL: {amazon_auth_url}")

        return redirect(amazon_auth_url)
    except Exception as e:
        logging.error(f"Error during start-oauth: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500



# Handle Callback from Amazon
@app.route('/callback', methods=['GET', 'POST'])
def handle_callback():
    try:
        if request.method == 'GET':
            # Extract parameters from GET request
            auth_code = request.args.get('spapi_oauth_code')
            state = request.args.get('state')
            selling_partner_id = request.args.get('selling_partner_id')

            # Debugging logs
            logging.debug(f"Received spapi_oauth_code: {auth_code}")
            logging.debug(f"Received state: {state}")
            logging.debug(f"Session stored state: {session.get('oauth_state')}")
            logging.debug(f"Received selling_partner_id: {selling_partner_id}")

            # Validate state
            session_state = session.get('oauth_state')
            if state != session_state:
                logging.error(f"State mismatch: expected {session_state}, got {state}")
                return jsonify({'error': 'Invalid state parameter in GET request'}), 400

            if not auth_code or not state or not selling_partner_id:
                logging.error(f"Missing parameters: spapi_oauth_code={auth_code}, state={state}, selling_partner_id={selling_partner_id}")
                return jsonify({'error': 'Missing required parameters in GET request'}), 400

            return jsonify({'message': 'GET request successful', 'auth_code': auth_code}), 200

        elif request.method == 'POST':
            # Extract parameters from POST request
            data = request.json
            auth_code = data.get('code')
            state = data.get('state')
            selling_partner_id = data.get('selling_partner_id')

            # Debugging logs
            logging.debug(f"Received spapi_oauth_code: {auth_code}")
            logging.debug(f"Received state: {state}")
            logging.debug(f"Session stored state: {session.get('oauth_state')}")
            logging.debug(f"Received selling_partner_id: {selling_partner_id}")

            # Validate state
            session_state = session.get('oauth_state')
            if state != session_state:
                logging.error(f"State mismatch: expected {session_state}, got {state}")
                return jsonify({'error': 'Invalid state parameter in POST request'}), 400

            if not auth_code or not state or not selling_partner_id:
                logging.error(f"Missing parameters: code={auth_code}, state={state}, selling_partner_id={selling_partner_id}")
                return jsonify({'error': 'Missing required parameters in POST request'}), 400

            # Proceed with token exchange logic (log if successful)
            token_url = "https://api.amazon.com/auth/o2/token"
            payload = {
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": LWA_APP_ID,
                "client_secret": LWA_CLIENT_SECRET,
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            token_response = requests.post(token_url, data=payload, headers=headers)

            if token_response.status_code != 200:
                logging.error(f"Token exchange failed: {token_response.json()}")
                return jsonify({'error': 'Failed to exchange authorization code', 'details': token_response.json()}), 400

            token_data = token_response.json()
            refresh_token = token_data.get("refresh_token")

            # Save seller credentials
            existing_seller = AmazonSeller.query.filter_by(selling_partner_id=selling_partner_id).first()
            if existing_seller:
                existing_seller.refresh_token = refresh_token
            else:
                new_seller = AmazonSeller(
                    selling_partner_id=selling_partner_id,
                    refresh_token=refresh_token
                )
                db.session.add(new_seller)

            db.session.commit()
            logging.debug("Authorization and token exchange successful")
            return jsonify({'message': 'Authorization successful'}), 200
    except Exception as e:
        logging.error(f"Error during callback: {str(e)}")
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500



@app.route('/webhook', methods=['POST'])
def handle_webhook():
    try:
        # Log the incoming request for debugging
        data = request.json
        logging.debug(f"Webhook data received: {data}")
        
        # Respond to Webflow with success
        return jsonify({"message": "Webhook received successfully"}), 200
    except Exception as e:
        logging.error(f"Error handling webhook: {str(e)}")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500



# Refresh Token Utility
def refresh_access_token(refresh_token):
    try:
        token_url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": LWA_APP_ID,
            "client_secret": LWA_CLIENT_SECRET,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(token_url, data=payload, headers=headers)

        if response.status_code != 200:
            logging.error(f"Failed to refresh access token: {response.json()}")
            return None

        token_data = response.json()
        return token_data.get("access_token")
    except Exception as e:
        logging.error(f"Error refreshing access token: {str(e)}")
        return None

# Health Check Route
@app.route('/')
def home():
    return "Welcome to the Flask App! API is running."

# Logging setup
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "https://guillermos-amazing-site-b0c75a.webflow.io"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response
