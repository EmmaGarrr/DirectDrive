## OVHcloud VPS Deployment Guide for DirectDrive


This document outlines the complete process for deploying the DirectDrive full-stack application (Angular frontend and FastAPI backend) onto a fresh OVHcloud Virtual Private Server (VPS) running Ubuntu.

## Project Overview :

•	Frontend: Angular (emmagarrr-directdrive-frontend)
•	Backend: Python/FastAPI with Docker (emmagarrr-directdrive)
•	Server: OVHcloud VPS
•	IP Address: 135.148.33.247
•	Username: ubuntu
•	Password:


## Deployment Strategy :
-	Backend Deployment: The FastAPI application will run inside Docker containers managed by docker-compose. This isolates its dependencies.
-	Frontend Deployment: The Angular application will be built into static HTML, CSS, and JS files. These files will be served by Nginx, a high-performance web server.
-	Firewall: A UFW (Uncomplicated Firewall) will be configured to only allow necessary traffic (SSH, HTTP, and the backend API port).


## Part 1: Initial Server Setup & Backend Deployment

## Step 1.1: Connect to the Server
-	Connect to the VPS from your local machine using an SSH client (like PowerShell, Terminal, or PuTTY).
-	Generated bash
-	# Connects to the server using the 'ubuntu' username and the server's IP.
-	# You will be prompted for the password.
-	ssh ubuntu@135.148.33.247


## Step 1.2: Update System and Install Core Tools
-	Update the server's package list and install all necessary software: git (for code), docker & docker-compose (for the backend), and nginx (for the frontend).
-	Generated bash
-	# 'sudo' is used to run commands with administrative privileges.
-	# 'apt update' refreshes the list of available packages.
-	# 'apt upgrade -y' installs all available updates without prompting.
-	sudo apt update && sudo apt upgrade -y

-	# Installs git, docker.io, docker-compose, and nginx in a single command.
-	sudo apt install git docker.io docker-compose nginx -y


## Step 1.3: Configure Docker Permissions
-	Add the ubuntu user to the docker group. This allows running docker commands without sudo, which is required by docker-compose.
-	Generated bash
-	# 'usermod -aG' adds a user to a supplementary group.
-	sudo usermod -aG docker ubuntu

-	# Log out for the group change to take effect.
-	exit

-	Action Required: After running exit, you must log back in using the ssh command from Step 1.1.

## Step 1.4: Clone Backend Repository
-	Download the backend source code from GitHub onto the server.
-	Generated bash
-	# Clones the repository into a new directory named 'emmagarrr-directdrive.git'.
-	git clone https://github.com/emmagarrr/directdrive.git emmagarrr-directdrive.git

-	# Navigate into the Backend's directory.
-	cd emmagarrr-directdrive.git/Backend/


## Step 1.5: Create Backend Environment File
-	The backend requires a .env file containing secret keys and configuration.
-	Generated bash
-	# 'nano' is a simple command-line text editor. This creates/opens the .env file.
-	nano .env

-	Paste the following content into the editor, filling in the real secret values:
-	Generated env
-	MONGODB_URI=mongodb+srv://<user>:<password>@<cluster-url>/
-	DATABASE_NAME=your_db_name
-	JWT_SECRET_KEY=YOUR_SUPER_SECRET_KEY_HERE
-	JWT_ALGORITHM=HS256
-	ACCESS_TOKEN_EXPIRE_MINUTES=1440
-	OAUTH_CLIENT_ID=your_google_client_id
-	OAUTH_CLIENT_SECRET=your_google_client_secret
-	OAUTH_REFRESH_TOKEN=your_google_refresh_token
-	GOOGLE_DRIVE_FOLDER_ID=your_google_drive_folder_id
-	Use code with caution.
-	Env
-	Save and exit with Ctrl+X, then Y, then Enter.

## Step 1.6: Start the Backend Application
-	Use docker-compose to build the Docker image and start the application containers in the background.
-	Generated bash
-	# '--build' forces a rebuild of the image from the Dockerfile.
-	# '-d' runs the containers in detached mode (in the background).
-	docker-compose up --build -d


## Part 2: Frontend Deployment & Nginx Configuration

## Step 2.1: Configure the Firewall
-	Open the necessary ports for web traffic and the API.
-	Generated bash
-	# 'ufw' is the Uncomplicated Firewall.
-	# 'allow' creates a rule to permit traffic on a specific port/service.
-	sudo ufw allow OpenSSH     # Port 22 for SSH connections
-	sudo ufw allow 80/tcp       # Port 80 for HTTP web traffic (Nginx)
-	sudo ufw allow 5000/tcp     # Port 5000 for the backend API

-	# Enables the firewall with the new rules.
-	sudo ufw enable

## Step 2.2: Prepare and Build the Frontend (Local Machine)
-	These steps are performed on your local computer.
-	Modify Environment: Edit the file src/environments/environment.prod.ts to point to the server's IP address.
-	Generated typescript
-	export const environment = {
-	production: true,
-	apiUrl: 'http://135.148.33.247:5000',
-	wsUrl: 'ws://135.148.33.247:5000/ws_api'
-	};
-	Use code with caution.
-	TypeScript
-	Build the App: Run the Angular build command. This compiles the TypeScript code into a dist/ folder containing static files.
-	Generated bash
-	ng build

## Step 2.3: Upload Frontend Files to Server (Local & Server)
-	Because the ubuntu user cannot write directly to /var/www/html, we use a two-step process.
-	On the Server: Create a temporary upload directory.
-	Generated bash
-	# 'mkdir' creates a new directory in the user's home folder.
-	mkdir ~/temp_upload

-	On the Local Machine: Use scp (secure copy) to upload the built files to the temporary directory on the server.
-	Generated bash
-	# '-r' copies directories recursively.
-	# The source is everything inside the build output folder.
-	# The destination is the temp_upload folder in the ubuntu user's home directory.
-	scp -r dist/frontend-test/* ubuntu@135.148.33.247:~/temp_upload/

-	On the Server: Move the files from the temporary directory to the final Nginx web root and set the correct permissions.
-	Generated bash
-	# 'sudo rm -rf' forcefully removes all existing files in the web root.
-	sudo rm -rf /var/www/html/*

-	# 'sudo mv' moves the uploaded files to the final destination.
-	sudo mv ~/temp_upload/* /var/www/html/

-	# 'chown' changes the owner of the files to the Nginx user ('www-data').
-	sudo chown -R www-data:www-data /var/www/html

-	# 'chmod' sets file permissions. '755' is standard for web content.
-	sudo chmod -R 755 /var/www/html

-	# Clean up the temporary directory.
-	rm -rf ~/temp_upload

## Step 2.4: Update Backend CORS Settings
-	The backend must be configured to accept requests from the server's own IP address.
-	On the Server, navigate back to the backend directory.
-	Generated bash
-	cd ~/emmagarrr-directdrive.git/Backend/

-	Edit the main application file.
-	Generated bash
-	nano app/main.py

-	Add the server's IP to the origins list.
-	Generated python
-	origins = [
-	"http://localhost:4200",
-	"https://teletransfer.vercel.app",
-	"http://135.148.33.247"  # <-- ADDED LINE
-	]
-	Rebuild and restart the backend to apply the changes.
-	Generated bash
-	docker-compose up --build -d

## Step 2.5: Configure Nginx (Final Fix)
-	Edit the Nginx configuration to point to the correct sub-directory where index.html is located.
-	Open the Nginx configuration file.
-	Generated bash
-	sudo nano /etc/nginx/sites-available/default

-	Modify the root directive to point to the /browser sub-directory. The final file should look like this:
-	Generated nginx
-	server {
-	listen 80;
-	root /var/www/html/browser;  # <-- This was the critical change
-	index index.html;

-	location / {
-	try_files $uri $uri/ /index.html;
-	}
-	}
-	Use code with caution.
-	Nginx
-	Test the configuration and restart Nginx.
-	Generated bash
-	# 'nginx -t' tests the syntax of configuration files.
-	sudo nginx -t

-	# 'systemctl restart' restarts the Nginx service to apply changes.
-	sudo systemctl restart nginx


## Part 3: Useful Debugging Commands

•	These commands were used to diagnose the "403 Forbidden" error.
•	Generated bash
•	# Check the contents and permissions of the web root folder.
•	ls -la /var/www/html/

•	# Check the permissions of the parent directories.
•	ls -ld /var /var/www /var/www/html

•	# View the last 20 lines of the Nginx error log in real-time.
•	sudo tail -f -n 20 /var/log/nginx/error.log

•	# View the logs for the backend Docker containers in real-time.
•	# (Must be in the 'Backend' directory)
•	docker-compose logs -f

•	# Check the status of the AppArmor security module.
•	sudo aa-status

•	# Display the content of the Nginx config file.
•	cat /etc/nginx/sites-available/default

•	At the end of this process, the application is live and accessible at http://135.148.33.247.
