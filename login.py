import os
import json
import logging
from typing import Optional, Dict, Any

import yaml
import keyring
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import auth

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SERVICE = "upstox"

def _load_config() -> Dict[str, Any]:
    """Loads configuration from config.yaml."""
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    if not os.path.exists(config_path):
        logger.warning(f"Config file not found at {config_path}")
        return {}
    
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config.yaml: {e}")
        return {}

config_data = _load_config()

# Load credentials from config or environment variables (avoid hardcoded secrets)
API_KEY = config_data.get('api', {}).get('api_key') or os.getenv("UPSTOX_API_KEY")
API_SECRET = config_data.get('api', {}).get('api_secret') or os.getenv("UPSTOX_API_SECRET")
REDIRECT_URI = config_data.get('api', {}).get('redirect_uri', "https://www.google.com")
MOBILE_NUMBER = str(config_data.get('user', {}).get('mobile_number') or os.getenv("UPSTOX_MOBILE_NUMBER", ""))
PIN = str(config_data.get('user', {}).get('pin') or os.getenv("UPSTOX_PIN", ""))
TOTP_SECRET = config_data.get('user', {}).get('totp_secret') or os.getenv("UPSTOX_TOTP_SECRET")

if not API_KEY:
    logger.warning("API_KEY is missing. Please provide it in config.yaml or UPSTOX_API_KEY env var.")

ACCOUNT = f"{SERVICE}-{API_KEY}" if API_KEY else SERVICE

def _load_tokens() -> Optional[Dict[str, Any]]:
    """Loads tokens from the secure OS keyring."""
    raw = keyring.get_password(SERVICE, ACCOUNT)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Failed to parse tokens from keyring: {e}")
        return None


def _save_tokens(token_data: Dict[str, Any]) -> None:
    """Saves tokens to the secure OS keyring."""
    try:
        keyring.set_password(SERVICE, ACCOUNT, json.dumps(token_data))
        logger.info("Tokens successfully saved to keyring.")
    except Exception as e:
        logger.error(f"Failed to save tokens to keyring: {e}")


def _is_valid(token_data: Dict[str, Any]) -> bool:
    """
    Validates the token by making a request to a secured API endpoint.
    Uses the /v2/user/profile endpoint.
    """
    access_token = token_data.get("access_token")
    if not access_token:
        return False

    url = "https://api.upstox.com/v2/user/profile"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        response = session.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                logger.info("Token validation successful.")
                return True
        elif response.status_code == 401:
            logger.info("Token is invalid or expired (401 Unauthorized).")
            return False
            
        logger.warning(f"Unexpected status code during token validation: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        return False






def ensure_login(open_browser: bool = True) -> Dict[str, Any]:
    """
    Triggers the automated login flow using UpstoxClient and saves the tokens.
    
    Args:
        open_browser (bool): Unused parameter (kept for backward compatibility).
        
    Returns:
        dict: The new token payload.
        
    Raises:
        RuntimeError: If the token exchange fails or API details are missing.
    """
    if not all([API_KEY, API_SECRET, MOBILE_NUMBER, PIN, TOTP_SECRET]):
        raise RuntimeError("Missing required credentials for login. Check config.yaml.")
        
    logger.info("Initiating login flow...")
    client = auth.UpstoxClient(API_KEY, API_SECRET, MOBILE_NUMBER, PIN, TOTP_SECRET, REDIRECT_URI)
    code = client.automate_login()
    tokens = client.set_access_token(code)
    
    if not tokens.get("access_token"):
        raise RuntimeError(f"Token exchange succeeded but no access_token in response: {tokens}")
        
    # Extract essential fields to minimize storage footprint
    new_tokens = {
        "access_token": tokens["access_token"],
        "extended_token": tokens.get("extended_token"),
        "issued_at": tokens.get("issued_at")
    }
    _save_tokens(new_tokens)
    return new_tokens


def get_access_token(force_login: bool = False) -> str:
    """
    Main entry point for obtaining a valid access token.
    Checks the secure keyring for a valid token, and triggers a new login if missing/invalid.
    
    Args:
        force_login (bool): If True, bypass the cache and force a new login.
        
    Returns:
        str: A valid Upstox access token.
    """
    if not force_login:
        tokens = _load_tokens()
        if tokens and _is_valid(tokens):
            logger.info("Using cached valid token.")
            return tokens["access_token"]
        elif tokens:
            logger.info("Cached token is invalid. Re-authenticating...")
        else:
            logger.info("No cached token found. Authenticating...")

    tokens = ensure_login()
    return tokens["access_token"]

if __name__ == "__main__":
    # Test the token retrieval
    try:
        token = get_access_token()
        logger.info(f"Successfully obtained token starting with: {token[:10]}...")
    except Exception as e:
        logger.error(f"Failed to get access token: {e}", exc_info=True)