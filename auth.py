import requests
import os
import pandas as pd
from datetime import datetime
import pyotp
import re
from urllib.parse import urlparse, parse_qs
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import logging
import keyring
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Optional, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

logger = logging.getLogger(__name__)

class UpstoxAuthError(Exception):
    """Exception raised for authentication errors such as 401 Unauthorized or invalid tokens."""
    pass

class UpstoxClient:
    """Client for interacting with the Upstox API and managing authentication."""
    
    BASE_URL = "https://api.upstox.com/v2"

    def __init__(
        self, 
        api_key: str, 
        api_secret: str, 
        mobile_number: str, 
        pin: str, 
        totp_secret: str, 
        redirect_uri: str
    ) -> None:
        """
        Initializes the UpstoxClient with necessary credentials.
        
        Args:
            api_key (str): The Upstox API key (client ID).
            api_secret (str): The Upstox API secret.
            mobile_number (str): The registered mobile number for login.
            pin (str): The 6-digit PIN for login.
            totp_secret (str): The secret key for generating TOTP.
            redirect_uri (str): The registered redirect URI.
        """
        self.session = requests.Session()
        self.api_key = api_key
        self.api_secret = api_secret
        self.mobile_number = mobile_number
        self.pin = pin
        self.totp_secret = totp_secret
        self.redirect_uri = redirect_uri
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_auth_url(self) -> str:
        """Generates the authorization URL for the initial login step."""
        return f"{self.BASE_URL}/login/authorization/dialog?response_type=code&client_id={self.api_key}&redirect_uri={self.redirect_uri}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=4, max=15),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    def automate_login(self) -> str:
        """
        Automates the login process using Selenium to bypass Cloudflare/API 401 issues.
        Follows the working pattern: Mobile -> TOTP -> PIN.
        
        Returns:
            str: The authorization code extracted from the redirect URI.
            
        Raises:
            UpstoxAuthError: If credentials are missing or the process fails.
        """
        if not all([self.mobile_number, self.pin, self.totp_secret]):
            raise UpstoxAuthError("Missing mobile_number, pin, or totp_secret in configuration.")

        logger.info("Starting automated login (via Selenium)...")
        
        chrome_options = Options()
        chrome_options.add_argument("--headless=new") # Modern headless mode

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--log-level=3")

        driver = None
        try:
            # Setup Chrome Driver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            wait = WebDriverWait(driver, 20)

            auth_url = self.get_auth_url()
            driver.get(auth_url)

            # Step 1: Enter Mobile Number
            logger.info("Entering mobile number...")
            try:
                mobile_field = wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="text"]')))
            except Exception as e:
                # Check for common error message in page source
                if "UDAPI100068" in driver.page_source:
                    raise UpstoxAuthError("Upstox rejected the Client ID or Redirect URI. Please ensure the Redirect URI matches exactly (case-sensitive).")
                raise UpstoxAuthError(f"Failed to find mobile number field: {e}")
                
            mobile_field.send_keys(self.mobile_number)
            
            # Click Get OTP
            get_otp_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="getOtp"]')))
            get_otp_btn.click()

            # Step 2: Enter TOTP
            logger.info("Generating and entering TOTP...")
            totp = pyotp.TOTP(self.totp_secret.replace(" ", "")).now()
            otp_field = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="otpNum"]')))
            otp_field.send_keys(totp)
                
            # Click Continue
            continue_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="continueBtn"]')))
            continue_btn.click()

            # Step 3: Enter PIN
            logger.info("Entering PIN...")
            pin_field = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="pinCode"]')))
            pin_field.send_keys(self.pin)
            
            # Click Continue
            pin_continue_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="pinContinueBtn"]')))
            pin_continue_btn.click()

            # Step 4: Capture Redirected URL for Authorization Code
            logger.info("Waiting for authorization code...")
            # Wait for URL to change to localhost (or whatever redirect_uri is)
            time.sleep(3) # Short sleep to let redirects happen
            
            final_url = driver.current_url
            parsed_url = urlparse(final_url)
            params = parse_qs(parsed_url.query)
            
            if 'code' not in params:
                 raise UpstoxAuthError(f"Failed to get authorization code from URL: {final_url}")
            
            code = params['code'][0]
            logger.info("Authorization code obtained successfully.")
            return code

        finally:
            if driver:
                driver.quit()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    def set_access_token(self, code: str) -> Dict[str, Any]:
        """
        Exchanges the authorization code for an access token.
        
        Args:
            code (str): The authorization code obtained from the login flow.
            
        Returns:
            dict: Token payload containing access_token, extended_token, etc.
            
        Raises:
            UpstoxAuthError: If the token exchange fails.
        """
        url = f"{self.BASE_URL}/login/authorization/token"
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'code': code,
            'client_id': self.api_key,
            'client_secret': self.api_secret,
            'redirect_uri': self.redirect_uri,
            'grant_type': 'authorization_code'
        }
        response = self.session.post(url, headers=headers, data=data, timeout=30)
        
        if response.status_code == 200:
            payload = response.json()
            logger.info("Access token obtained successfully.")
            return {
                "access_token": payload.get('access_token'),
                "extended_token": payload.get('extended_token'),
                "issued_at": datetime.now().isoformat(),
                "raw": payload
            }
        else:
            logger.error(f"Failed to get access token. Status Code: {response.status_code}, Response: {response.text}")
            raise UpstoxAuthError(f"Failed to get access token: {response.text}")


    