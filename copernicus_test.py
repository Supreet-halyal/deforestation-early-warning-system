import os
import requests

from dotenv import load_dotenv


load_dotenv()


CLIENT_ID = os.getenv("COPERNICUS_CLIENT_ID")
CLIENT_SECRET = os.getenv("COPERNICUS_CLIENT_SECRET")


TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/"
    "auth/realms/CDSE/protocol/openid-connect/token"
)


def get_access_token():

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=30
    )

    response.raise_for_status()

    token_data = response.json()

    return token_data["access_token"]


if __name__ == "__main__":

    try:

        token = get_access_token()

        print("✅ Copernicus authentication successful!")
        print("✅ Access token received.")
        print("🔐 Token is being kept private.")

    except Exception as error:

        print("❌ Copernicus authentication failed.")
        print(error)