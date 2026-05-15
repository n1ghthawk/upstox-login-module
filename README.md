# Upstox Login Module
This module automates the login process for Upstox and retrieves access tokens. Access token is stored in windows credentials globally, so that a centralized login system can be used across multiple projects.


## How to use:
    1. Create a config.yaml file in the same directory as the script.
    2. Add the following credentials to the config.yaml file:
        api:
            api_key: "your_api_key"
            api_secret: "your_api_secret"
            redirect_uri: "your_redirect_uri"
        user:
            mobile_number: "your_mobile_number"
            pin: "your_pin"
            totp_secret: "your_totp_secret"
    3. Run the script:
        python login.py


### How to use as a package in other projects (via Git):
Instead of copying files, you can install this module directly from Git into your other projects.

1. **Install the package:**
   Using `pip`:
   ```bash
   pip install git+https://github.com/n1ghthawk/upstox-login-module.git
   ```
   Or using `uv`:
   ```bash
   uv add git+https://github.com/n1ghthawk/upstox-login-module.git
   ```

2. **Configure Credentials:**
   Ensure your target project has a `config.yaml` file in its root directory with the necessary Upstox credentials, or set the corresponding OS Environment variables (e.g., `UPSTOX_API_KEY`).

3. **Import and use in your code:**
   ```python
   from login import get_access_token

   # This will automatically use cached tokens or trigger a new login if expired
   access_token = get_access_token()

   # Use the token in your Upstox API requests
   headers = {
       'Authorization': f'Bearer {access_token}',
       'Accept': 'application/json'
   }
   ```
## Prerequisites:
- Python 3.6+
- pip
- Chrome browser installed


## Running with Docker

```bash
# Build the Docker image
docker build -t upstox-login .

# Run the script (this will trigger the login flow and save tokens to keyring)
docker run -it upstox-login
```


