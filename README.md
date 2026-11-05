# Unified Job Portal

A comprehensive job portal that combines both Government and Private job opportunities into a single platform. Built with Python Flask backend and SQLite database.

## Features

### Premium UI/UX Design
- **Enterprise-Grade Interface**: Modern, clean design inspired by LinkedIn, Naukri, and Indeed
- **Premium Color Palette**: Blue + Teal gradient theme with smooth shadows and rounded components
- **Modern Typography**: Poppins + Inter fonts for professional appearance
- **Smooth Animations**: Micro-interactions and transitions throughout
- **Responsive Design**: Beautiful layout on all devices
- **Collapsible Filters**: Advanced filtering with elegant UI
- **Premium Cards**: Glassy shadows and neumorphic highlights

### User Features
- **User Registration & Authentication**: Secure user registration and login system
- **Job Search & Filter**: Advanced search and filtering options for jobs
  - Search by keywords, location, job type, category
  - Filter by Government/Private jobs
  - Filter by industry category (IT, Healthcare, Education, etc.)
  - Collapsible filter panel with premium design
- **Job Listings**: Browse all available jobs with detailed information and premium job cards
- **Job Applications**: Apply for jobs with cover letter support
- **Resume Upload**: Upload and manage your resume (PDF, DOC, DOCX) with drag-and-drop interface
- **Job Alerts**: Create personalized job alerts based on keywords, location, and category
- **Dashboard**: View your applications and profile information with analytics widgets

### Admin Features
- **Separate Admin Login**: Dedicated admin login page at `/admin/login`
- **Admin Dashboard**: Premium analytics dashboard with statistics widgets
- **Job Management**: Add, edit, and delete job postings with modern forms
- **Application Management**: View and update application statuses with premium tables
- **User Management**: Complete user management system - view user profiles, applications, and resumes

## Technology Stack

- **Backend**: Python Flask
- **Database**: SQLite (SQLAlchemy ORM)
- **Frontend**: Bootstrap 5, HTML5, CSS3
- **Authentication**: Flask-Login
- **File Upload**: Werkzeug

## Installation

1. **Clone or navigate to the project directory**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python app.py
   ```

4. **Access the application**:
   - Open your browser and go to: `http://localhost:5000`
   - **Admin Login**: Go to `/admin/login` or click "Admin Login" from regular login page
   - Admin credentials (created automatically):
     - Username: `admin`
     - Password: `admin123`

## Project Structure

```
RAJATH/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── README.md             # Project documentation
├── templates/            # HTML templates
│   ├── base.html         # Base template
│   ├── index.html        # Home page
│   ├── login.html        # Login page
│   ├── register.html     # Registration page
│   ├── dashboard.html    # User dashboard
│   ├── jobs.html         # Job listings
│   ├── job_detail.html   # Job details
│   ├── apply_job.html    # Job application
│   ├── upload_resume.html # Resume upload
│   ├── job_alerts.html   # Job alerts
│   └── admin/            # Admin templates
│       ├── dashboard.html
│       ├── jobs.html
│       ├── add_job.html
│       ├── edit_job.html
│       └── applications.html
├── static/               # Static files
│   ├── css/
│   │   └── style.css    # Custom styles
│   └── js/
├── uploads/             # Uploaded files
│   └── resumes/         # User resumes
└── job_portal.db        # SQLite database (created automatically)
```

## Usage

### For Job Seekers

1. **Register/Login**: Create an account or login to existing account
2. **Upload Resume**: Upload your resume from the dashboard
3. **Browse Jobs**: Search and filter jobs based on your preferences
4. **Apply for Jobs**: Click on job details and submit your application
5. **Set Job Alerts**: Create alerts to get notified about new matching jobs
6. **Track Applications**: View all your applications and their status from dashboard

### For Administrators

1. **Admin Login**: Go to `/admin/login` and use admin credentials
2. **Dashboard**: View analytics and statistics on the premium admin dashboard
3. **Add Jobs**: Post new government or private job opportunities with modern forms
4. **Manage Jobs**: Edit or delete existing job postings
5. **Review Applications**: View all applications and update their status with dropdown selectors
6. **Manage Users**: View user profiles, their applications, and download resumes
7. **Monitor Statistics**: Real-time statistics on jobs, applications, and users

## Database Models

- **User**: User accounts with authentication
- **Job**: Job postings (Government/Private)
- **Application**: Job applications submitted by users
- **JobAlert**: User-defined job alerts

## Security Features

- Password hashing using Werkzeug
- Session management with Flask-Login
- Admin-only routes protection
- File upload validation
- SQL injection protection (SQLAlchemy ORM)

## Configuration

The application uses SQLite database by default. To use a different database:

1. Update `SQLALCHEMY_DATABASE_URI` in `app.py`
2. Change `SECRET_KEY` for production use

## Deployment

### Local Deployment

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Vikas79-gif/Unified_Job_Portal.git
   cd Unified_Job_Portal
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python app.py
   ```

4. **Access the app**: http://localhost:5000

---

### Deploy to Render.com (Free Tier)

Render offers a free tier that includes:
- 750 hours/month of instance time
- 512 MB RAM
- 10 GB bandwidth/month
- Auto-sleep after 90 minutes of inactivity

**Steps:**

1. Go to **https://render.com** and sign up/login with GitHub
2. Click **"New +"** → **"Web Service"**
3. Connect your repository: `Vikas79-gif/Unified_Job_Portal`
4. Configure the service:
   | Setting | Value |
   |---------|-------|
   | Name | `unified-job-portal` |
   | Environment | `Python 3` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT` |
   | Region | Select closest to your users |
5. Click **"Create Web Service"**
6. Wait 3-5 minutes for deployment
7. Your live URL: **https://unified-job-portal.onrender.com**

**Optional Environment Variables** (add in Render dashboard):
- `SECRET_KEY` - Generate a random secure key
- `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` - For email notifications

---

### Deploy to PythonAnywhere (Free Tier)

PythonAnywhere offers a completely free plan with no sleep:
- 24/7 uptime (no auto-sleep)
- 512 MB RAM
- 1 GB storage

**Steps:**

1. Go to **https://www.pythonanywhere.com** and sign up (free tier)
2. Go to **"Web"** tab → **"Add a new web app"**
3. Choose **"Manual configuration"** → **Next**
4. Select **Python 3.11** → **Next**
5. In the **WSGI Configuration File** section, paste:
   ```python
   import sys
   sys.path.insert(0, '/home/YourUsername/Unified_Job_Portal')
   from app import app as application
   ```
   Replace `YourUsername` with your PythonAnywhere username
6. Go to **"Consoles"** → **"Bash"** and run:
   ```bash
   cd ~/Unified_Job_Portal
   pip install -r requirements.txt
   ```
7. Go back to **"Web"** tab and click **"Reload"**
8. Your live URL: **https://YourUsername.pythonanywhere.com**

---

### Deploy to Railway (Free Tier)

Railway offers 500 free execution hours per month.

**Steps:**

1. Go to **https://railway.app** and sign up with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select `Unified_Job_Portal` repository
4. Railway will auto-detect it's a Python project
5. Add a **Procfile** with content:
   ```
   web: gunicorn app:app --bind 0.0.0.0:$PORT
   ```
6. Click **"Deploy"**
7. Get your live URL from the dashboard

---

### Required Files for Deployment

Create these files in your project root before deploying:

**Procfile** (for Railway/Gunicorn):
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

**render.yaml** (for Render):
```yaml
services:
  - type: web
    name: unified-job-portal
    env: python
    region: oregon
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
```

---

## Future Enhancements

- Email notifications for job alerts
- Advanced search with multiple filters
- Resume parsing and auto-fill
- Company profiles
- User profile pages
- Application tracking with email updates
- Export functionality for applications
- API endpoints for mobile apps

## License

This project is open source and available for educational purposes.

## Support

For issues or questions, please check the code comments or create an issue in the repository.

