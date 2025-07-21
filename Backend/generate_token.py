import google.oauth2.credentials
import google_auth_oauthlib.flow

# This is the scope we requested on the consent screen.
# It must match exactly.
SCOPES = ['https://www.googleapis.com/auth/drive']
# The path to the credentials file you just downloaded.
CLIENT_SECRETS_FILE = "credentials/cred.json"

def main():
    # Create a flow instance to manage the authorization process.
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)

    # run_local_server() opens a browser window, lets you log in,
    # and handles the exchange of the authorization code for a token.
    print("\n--- Your browser will now open for you to authorize the application. ---\n")
    credentials = flow.run_local_server(port=0)

    # The credentials object now contains your access_token and refresh_token.
    # We only care about the refresh_token because it's permanent.
    refresh_token = credentials.refresh_token
    
    print("\n--- AUTHORIZATION COMPLETE ---\n")
    print(f"Your Client ID is: {credentials.client_id}")
    print(f"Your Client Secret is: {credentials.client_secret}")
    
    print("\n\n!!! COPY YOUR REFRESH TOKEN !!!\n")
    print("This is the permanent token. Save it in your .env file.")
    print("==========================================================")
    print(refresh_token)
    print("==========================================================")

if __name__ == '__main__':
    main()